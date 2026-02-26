from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin

from app.services.domains.ingestion.constants import (
    HTML_TAG_RE,
    INITIAL_PAGE_FINGERPRINT_MAX_PUBLICATIONS,
    SPACE_RE,
    TITLE_ALNUM_RE,
    WORD_RE,
)
from app.services.domains.scholar.parser import ParseState, ParsedProfilePage, PublicationCandidate

# Scholar-specific noise patterns stripped before canonical comparison.
# Applied in order; each targets a different Scholar metadata injection style.
_NOISE_DOI_RE = re.compile(r"[,.\s]+doi\s*:\s*\S+.*$", re.IGNORECASE)
_NOISE_ARXIV_RE = re.compile(r"[,.\s]+arxiv\b.*$", re.IGNORECASE)
_NOISE_PREPRINT_RE = re.compile(
    r"[,\s]+(?:preprint|extended\s+version|technical\s+report|working\s+paper)\b.*$",
    re.IGNORECASE,
)
_NOISE_TRAILING_YEAR_RE = re.compile(r"\s*[,(]\s*\d{4}\s*[),]?\s*$")
# Strips ". Capitalised sentence" appended as venue: ". Comput. Sci…", ". Journal of…"
_NOISE_VENUE_SENTENCE_RE = re.compile(r"(?<=\w{3})\.\s+[A-Z][a-z].*$")

_CANONICAL_DEDUP_THRESHOLD = 0.82


def normalize_title(value: str) -> str:
    lowered = value.lower()
    return TITLE_ALNUM_RE.sub("", lowered)


def canonical_title_for_dedup(title: str) -> str:
    """Strip Scholar-specific noise suffixes then normalize for dedup comparison."""
    t = title.strip()
    t = _NOISE_DOI_RE.sub("", t)
    t = _NOISE_ARXIV_RE.sub("", t)
    t = _NOISE_PREPRINT_RE.sub("", t)
    t = _NOISE_TRAILING_YEAR_RE.sub("", t)
    t = _NOISE_VENUE_SENTENCE_RE.sub("", t)
    return normalize_title(t.strip())


def _stripped_title_for_canonical(title: str) -> str:
    """Apply noise-stripping and lowercase but PRESERVE spaces (for later tokenization)."""
    t = title.strip()
    t = _NOISE_DOI_RE.sub("", t)
    t = _NOISE_ARXIV_RE.sub("", t)
    t = _NOISE_PREPRINT_RE.sub("", t)
    t = _NOISE_TRAILING_YEAR_RE.sub("", t)
    t = _NOISE_VENUE_SENTENCE_RE.sub("", t)
    return t.lower().strip()


def _canonical_title_tokens(title: str) -> set[str]:
    """Word tokens of the noise-stripped title (preserves token boundaries)."""
    return set(WORD_RE.findall(_stripped_title_for_canonical(title)))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _first_author_last_name(authors_text: str | None) -> str:
    if not authors_text:
        return ""
    first_author = authors_text.split(",", maxsplit=1)[0].strip().lower()
    words = WORD_RE.findall(first_author)
    if not words:
        return ""
    return words[-1]


def _first_venue_word(venue_text: str | None) -> str:
    if not venue_text:
        return ""
    words = WORD_RE.findall(venue_text.lower())
    if not words:
        return ""
    return words[0]


def build_publication_fingerprint(candidate: PublicationCandidate) -> str:
    canonical = "|".join(
        [
            normalize_title(candidate.title),
            str(candidate.year) if candidate.year is not None else "",
            _first_author_last_name(candidate.authors_text),
            _first_venue_word(candidate.venue_text),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_initial_page_fingerprint(parsed_page: ParsedProfilePage) -> str | None:
    if parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
        return None

    normalized_rows: list[dict[str, Any]] = []
    for publication in parsed_page.publications[:INITIAL_PAGE_FINGERPRINT_MAX_PUBLICATIONS]:
        normalized_rows.append(
            {
                "cluster_id": publication.cluster_id or "",
                "title_normalized": normalize_title(publication.title),
                "year": publication.year,
                "citation_count": publication.citation_count,
            }
        )

    payload = {
        "state": parsed_page.state.value,
        "articles_range": parsed_page.articles_range or "",
        "has_show_more_button": parsed_page.has_show_more_button,
        "profile_name": parsed_page.profile_name or "",
        "publications": normalized_rows,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_publication_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    return urljoin("https://scholar.google.com", path_or_url)


def _next_cstart_value(*, articles_range: str | None, fallback: int) -> int:
    if articles_range:
        numbers = re.findall(r"\d+", articles_range)
        if len(numbers) >= 2:
            try:
                return int(numbers[1])
            except ValueError:
                pass
    return int(fallback)


def _title_tokens(value: str) -> set[str]:
    """Extract normalized word tokens for fuzzy title comparison."""
    return set(WORD_RE.findall(value.lower()))


def fuzzy_titles_match(
    title_a: str,
    title_b: str,
    *,
    threshold: float = 0.85,
) -> bool:
    """Return True if two titles are near-duplicates by token-level Jaccard similarity.

    A threshold of 0.85 catches common academic duplicate patterns:
    differences in punctuation, minor word variations, subtitle changes.
    """
    tokens_a = _title_tokens(title_a)
    tokens_b = _title_tokens(title_b)
    return _jaccard(tokens_a, tokens_b) >= threshold


def _dedupe_publication_candidates(
    publications: list[PublicationCandidate],
    *,
    seen_canonical: set[str] | None = None,
) -> list[PublicationCandidate]:
    """Deduplicate candidates using canonical title matching.

    Args:
        publications: candidates to filter
        seen_canonical: optional mutable set shared across pages.  Stores the
            noise-stripped *lowercased* (but space-preserved) canonical string
            so it can be tokenized on the next page for cross-page fuzzy dedup.
            Accepted canonicals are added; existing entries are consulted.
    """
    deduped: list[PublicationCandidate] = []
    seen_exact: set[str] = set()
    # Token sets for fuzzy comparison; seeded from cross-page state.
    seen_tokens: list[set[str]] = []

    if seen_canonical:
        for stripped in seen_canonical:
            seen_tokens.append(set(WORD_RE.findall(stripped)))

    for pub in publications:
        identity = _publication_identity(pub)
        if identity in seen_exact:
            continue

        # Use space-preserving stripped form for token-level fuzzy match.
        tokens = _canonical_title_tokens(pub.title)
        if _is_fuzzy_dup(tokens, seen_tokens):
            continue

        seen_exact.add(identity)
        seen_tokens.append(tokens)
        if seen_canonical is not None:
            # Store the noise-stripped lowercased (space-preserved) form.
            seen_canonical.add(_stripped_title_for_canonical(pub.title))
        deduped.append(pub)

    return deduped


def _publication_identity(pub: PublicationCandidate) -> str:
    if pub.cluster_id:
        return f"cluster:{pub.cluster_id}"
    canonical = canonical_title_for_dedup(pub.title)
    return "|".join(
        [
            "fallback",
            canonical,
            str(pub.year) if pub.year is not None else "",
            _first_author_last_name(pub.authors_text),
        ]
    )


def _is_fuzzy_dup(tokens: set[str], seen: list[set[str]]) -> bool:
    for existing in seen:
        if _jaccard(tokens, existing) >= _CANONICAL_DEDUP_THRESHOLD:
            return True
    return False


def _build_body_excerpt(body: str, *, max_chars: int = 220) -> str | None:
    if not body:
        return None
    flattened = SPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", body)).strip()
    if not flattened:
        return None
    if len(flattened) <= max_chars:
        return flattened
    return f"{flattened[:max_chars - 1]}..."

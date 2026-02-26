from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any
from urllib.parse import urljoin

from app.services.domains.ingestion.constants import (
    HTML_TAG_RE,
    INITIAL_PAGE_FINGERPRINT_MAX_PUBLICATIONS,
    SPACE_RE,
    TITLE_ALNUM_RE,
    WORD_RE,
)
from app.services.domains.scholar.parser import ParsedProfilePage, ParseState, PublicationCandidate

# Scholar-specific noise patterns stripped before canonical comparison.
# Applied in order; each targets a different Scholar metadata injection style.
_NOISE_DOI_RE = re.compile(r"[,.\s]+doi\s*:\s*\S+.*$", re.IGNORECASE)
_NOISE_ARXIV_RE = re.compile(r"[,.\s]+arxiv\b.*$", re.IGNORECASE)
_NOISE_PREPRINT_RE = re.compile(
    r"[,\s]+(?:preprint|extended\s+version|technical\s+report|working\s+paper)\b.*$",
    re.IGNORECASE,
)
_NOISE_TRAILING_YEAR_RE = re.compile(r"\s*[,(]\s*\d{4}\s*[),]?\s*$")
_NOISE_TRAILING_MONTH_YEAR_RE = re.compile(
    r"\s*[,(]\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}\s*[),]?\s*$",
    re.IGNORECASE,
)
_NOISE_TRAILING_PUBLICATION_TYPE_RE = re.compile(
    r"[,.\s]+(?:conference\s+paper|journal\s+article)\s*$",
    re.IGNORECASE,
)
_NOISE_IN_PROCEEDINGS_SUFFIX_RE = re.compile(r"\s+in:\s+proceedings\b.*$", re.IGNORECASE)
# Strips ". Capitalised sentence" appended as venue: ". Comput. Sci…", ". Journal of…"
_NOISE_VENUE_SENTENCE_RE = re.compile(r"(?<=\w{3})\.\s+[A-Z][a-z].*$")
_MOJIBAKE_HINT_RE = re.compile(r"[ÃÂâ]")
_MOJIBAKE_CHAR_RE = re.compile(r"[ÃÂâ€œ”€™]")
_METADATA_ORDINAL_RE = re.compile(r"^\d+(st|nd|rd|th)$")
_NOISE_LEADING_DATE_PREFIX_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?\)?[,\.\s:;-]+",
    re.IGNORECASE,
)
_NOISE_LEADING_AUTHOR_FRAGMENT_RE = re.compile(r"^(?:and|&)\s+[a-z.\s]{1,40}:\s*", re.IGNORECASE)
_METADATA_SEPARATORS = (" - ", " — ", ",", ";", ". ")
_VENUE_HINT_TOKENS = {
    "aaai",
    "conference",
    "conf",
    "cvpr",
    "eccv",
    "iclr",
    "icml",
    "journal",
    "nips",
    "neurips",
    "proceedings",
    "proc",
    "symposium",
    "workshop",
}
_PUBLICATION_TYPE_TOKENS = {"conference", "paper", "journal", "article"}
_MIN_METADATA_HINT_TOKENS = 2
_MIN_METADATA_CONTEXT_TOKENS = 4

_CANONICAL_DEDUP_THRESHOLD = 0.82


def normalize_title(value: str) -> str:
    lowered = _normalized_text(value).lower()
    return TITLE_ALNUM_RE.sub("", lowered)


def canonical_title_for_dedup(title: str) -> str:
    """Strip Scholar-specific noise suffixes then normalize for dedup comparison."""
    return normalize_title(_canonical_title_text(title))


def canonical_title_text_for_dedup(title: str) -> str:
    """Noise-stripped lowercase title with spaces preserved for token-level matching."""
    return _stripped_title_for_canonical(title)


def canonical_title_tokens_for_dedup(title: str) -> set[str]:
    """Word tokens of the noise-stripped title."""
    return _canonical_title_tokens(title)


def _stripped_title_for_canonical(title: str) -> str:
    """Apply noise-stripping and lowercase but PRESERVE spaces (for later tokenization)."""
    t = _canonical_title_text(title)
    return t.lower().strip()


def _canonical_title_text(title: str) -> str:
    t = _normalized_text(title)
    t = _strip_noise_suffixes(t)
    t = _strip_venue_metadata_suffixes(t)
    return _NOISE_VENUE_SENTENCE_RE.sub("", t).strip()


def _strip_noise_suffixes(value: str) -> str:
    t = _strip_leading_noise_prefixes(value.strip())
    t = _NOISE_DOI_RE.sub("", t)
    t = _NOISE_ARXIV_RE.sub("", t)
    t = _NOISE_PREPRINT_RE.sub("", t)
    t = _NOISE_TRAILING_YEAR_RE.sub("", t)
    t = _NOISE_TRAILING_MONTH_YEAR_RE.sub("", t)
    t = _NOISE_TRAILING_PUBLICATION_TYPE_RE.sub("", t)
    t = _NOISE_IN_PROCEEDINGS_SUFFIX_RE.sub("", t)
    return t.strip()


def _strip_venue_metadata_suffixes(value: str) -> str:
    stripped = value.strip()
    while True:
        cut_index = _metadata_cut_index(stripped)
        if cut_index is None:
            return stripped
        stripped = stripped[:cut_index].strip()


def _metadata_cut_index(value: str) -> int | None:
    candidates: list[int] = []
    for candidate in _METADATA_SEPARATORS:
        start = 0
        while True:
            index = value.find(candidate, start)
            if index <= 0:
                break
            suffix = value[index + len(candidate) :].strip()
            if suffix and _looks_like_venue_metadata(suffix):
                candidates.append(index)
            start = index + len(candidate)
    if not candidates:
        return None
    return min(candidates)


def _looks_like_venue_metadata(value: str) -> bool:
    tokens = WORD_RE.findall(value.lower())
    if len(tokens) < _MIN_METADATA_HINT_TOKENS:
        return False
    has_hint = any(_is_venue_hint_token(token) for token in tokens)
    if not has_hint:
        return False
    has_year = any(_is_year_token(token) for token in tokens)
    has_ordinal = any(_METADATA_ORDINAL_RE.match(token) for token in tokens)
    publication_type_only = all(token in _PUBLICATION_TYPE_TOKENS for token in tokens)
    return has_year or has_ordinal or publication_type_only or len(tokens) >= _MIN_METADATA_CONTEXT_TOKENS


def _strip_leading_noise_prefixes(value: str) -> str:
    stripped = value
    while True:
        next_value = _NOISE_LEADING_DATE_PREFIX_RE.sub("", stripped).strip()
        next_value = _NOISE_LEADING_AUTHOR_FRAGMENT_RE.sub("", next_value).strip()
        if next_value == stripped:
            return stripped
        stripped = next_value


def _is_venue_hint_token(token: str) -> bool:
    if token in _VENUE_HINT_TOKENS:
        return True
    return token.startswith("conf") or token.startswith("proceed")


def _is_year_token(token: str) -> bool:
    if len(token) != 4 or not token.isdigit():
        return False
    year = int(token)
    return 1900 <= year <= 2100


def _normalized_text(value: str) -> str:
    repaired = _repair_mojibake(value.strip())
    normalized = unicodedata.normalize("NFKC", repaired)
    cleaned = _MOJIBAKE_CHAR_RE.sub(" ", normalized)
    return SPACE_RE.sub(" ", cleaned).strip()


def _repair_mojibake(value: str) -> str:
    if not value or not _MOJIBAKE_HINT_RE.search(value):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    if _mojibake_score(repaired) < _mojibake_score(value):
        return repaired
    return value


def _mojibake_score(value: str) -> int:
    return len(_MOJIBAKE_HINT_RE.findall(value))


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
    return f"{flattened[: max_chars - 1]}..."

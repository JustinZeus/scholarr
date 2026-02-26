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


def normalize_title(value: str) -> str:
    lowered = value.lower()
    return TITLE_ALNUM_RE.sub("", lowered)


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
    if not tokens_a or not tokens_b:
        return False
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return (len(intersection) / len(union)) >= threshold


def _dedupe_publication_candidates(
    publications: list[PublicationCandidate],
) -> list[PublicationCandidate]:
    deduped: list[PublicationCandidate] = []
    seen: set[str] = set()
    seen_titles: list[tuple[str, int]] = []  # (normalized_title, index into deduped)

    for publication in publications:
        if publication.cluster_id:
            identity = f"cluster:{publication.cluster_id}"
        else:
            identity = "|".join(
                [
                    "fallback",
                    normalize_title(publication.title),
                    str(publication.year) if publication.year is not None else "",
                    _first_author_last_name(publication.authors_text),
                    _first_venue_word(publication.venue_text),
                ]
            )
        if identity in seen:
            continue

        # Fuzzy title check — catch near-identical titles not caught by exact fingerprint
        norm_title = normalize_title(publication.title)
        is_fuzzy_dup = False
        for existing_title, _idx in seen_titles:
            if fuzzy_titles_match(norm_title, existing_title):
                is_fuzzy_dup = True
                break
        if is_fuzzy_dup:
            continue

        seen.add(identity)
        seen_titles.append((norm_title, len(deduped)))
        deduped.append(publication)
    return deduped


def _build_body_excerpt(body: str, *, max_chars: int = 220) -> str | None:
    if not body:
        return None
    flattened = SPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", body)).strip()
    if not flattened:
        return None
    if len(flattened) <= max_chars:
        return flattened
    return f"{flattened[:max_chars - 1]}..."

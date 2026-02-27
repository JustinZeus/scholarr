from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.arxiv.constants import (
    ARXIV_STRONG_IDENTIFIER_CONFIDENCE,
    ARXIV_TITLE_MIN_ALPHA_TOKENS,
    ARXIV_TITLE_MIN_TOKENS,
    ARXIV_TITLE_TOKEN_MIN_LENGTH,
)
from app.services.doi.normalize import normalize_doi
from app.services.publication_identifiers.normalize import normalize_arxiv_id

if TYPE_CHECKING:
    from app.services.publications.types import PublicationListItem, UnreadPublicationItem

_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")


def arxiv_skip_reason_for_item(
    *,
    item: PublicationListItem | UnreadPublicationItem,
    has_strong_doi: bool = False,
    has_existing_arxiv: bool = False,
) -> str | None:
    if has_existing_arxiv or _has_arxiv_identifier_evidence(item):
        return "arxiv_identifier_present"
    if has_strong_doi or _has_strong_doi_evidence(item):
        return "strong_doi_present"
    if not _title_passes_quality_guard(item.title):
        return "title_quality_below_threshold"
    return None


def _has_arxiv_identifier_evidence(item: PublicationListItem | UnreadPublicationItem) -> bool:
    if _display_identifier_matches(item, expected_kind="arxiv"):
        return True
    return _has_normalized_identifier(item, normalizer=normalize_arxiv_id)


def _has_strong_doi_evidence(item: PublicationListItem | UnreadPublicationItem) -> bool:
    if _display_identifier_matches(item, expected_kind="doi"):
        return True
    return _has_normalized_identifier(item, normalizer=normalize_doi)


def _display_identifier_matches(
    item: PublicationListItem | UnreadPublicationItem,
    *,
    expected_kind: str,
) -> bool:
    display = getattr(item, "display_identifier", None)
    if display is None:
        return False
    if str(display.kind).lower() != expected_kind:
        return False
    return float(display.confidence_score) >= ARXIV_STRONG_IDENTIFIER_CONFIDENCE


def _has_normalized_identifier(
    item: PublicationListItem | UnreadPublicationItem,
    *,
    normalizer,
) -> bool:
    if normalizer(item.pub_url):
        return True
    return normalizer(item.pdf_url) is not None


def _title_passes_quality_guard(title: str | None) -> bool:
    tokens = _normalized_tokens(title or "")
    if len(tokens) < ARXIV_TITLE_MIN_TOKENS:
        return False
    alpha_tokens = [token for token in tokens if _is_alpha_token(token)]
    return len(alpha_tokens) >= ARXIV_TITLE_MIN_ALPHA_TOKENS


def _normalized_tokens(value: str) -> list[str]:
    return [token for token in _TITLE_TOKEN_RE.findall(value.lower()) if token]


def _is_alpha_token(token: str) -> bool:
    if len(token) < ARXIV_TITLE_TOKEN_MIN_LENGTH:
        return False
    return any(char.isalpha() for char in token)

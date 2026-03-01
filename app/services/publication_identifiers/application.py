from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication, PublicationIdentifier
from app.services.arxiv.guards import arxiv_skip_reason_for_item
from app.services.doi.normalize import normalize_doi
from app.services.publication_identifiers.normalize import (
    normalize_arxiv_id,
    normalize_pmcid,
    normalize_pmid,
)
from app.services.publication_identifiers.types import (
    DisplayIdentifier,
    IdentifierCandidate,
    IdentifierKind,
)

if TYPE_CHECKING:
    from app.services.publications.pdf_queue_queries import PdfQueueListItem
    from app.services.publications.types import PublicationListItem, UnreadPublicationItem

CONFIDENCE_HIGH = 0.98
CONFIDENCE_MEDIUM = 0.9
CONFIDENCE_LOW = 0.6
CONFIDENCE_FALLBACK = 0.4
PRIORITY_DOI = 400
PRIORITY_ARXIV = 300
PRIORITY_PMCID = 200
PRIORITY_PMID = 100


def derive_display_identifier_from_values(
    *,
    doi: str | None,
    pub_url: str | None = None,
    pdf_url: str | None = None,
) -> DisplayIdentifier | None:
    candidates = _fallback_candidates_from_values(doi=doi, pub_url=pub_url, pdf_url=pdf_url)
    return _best_display_identifier(candidates)


def _fallback_candidates_from_values(
    *,
    doi: str | None,
    pub_url: str | None,
    pdf_url: str | None,
) -> list[IdentifierCandidate]:
    values = [value for value in [pub_url, pdf_url] if value]
    candidates = []
    if doi:
        normalized_doi = normalize_doi(doi)
        if normalized_doi:
            candidates.append(
                _candidate(IdentifierKind.DOI, doi, normalized_doi, "legacy_doi", CONFIDENCE_HIGH, pub_url)
            )
    candidates.extend(_url_identifier_candidates(values=values, source="legacy_urls"))
    return _dedup_candidates(candidates)


def _url_identifier_candidates(*, values: list[str], source: str) -> list[IdentifierCandidate]:
    candidates: list[IdentifierCandidate] = []
    for value in values:
        candidates.extend(_url_candidates_for_value(value=value, source=source))
    return candidates


def _url_candidates_for_value(*, value: str, source: str) -> list[IdentifierCandidate]:
    candidates: list[IdentifierCandidate] = []
    arxiv = normalize_arxiv_id(value)
    if arxiv:
        candidates.append(_candidate(IdentifierKind.ARXIV, value, arxiv, source, CONFIDENCE_MEDIUM, value))
    pmcid = normalize_pmcid(value)
    if pmcid:
        candidates.append(_candidate(IdentifierKind.PMCID, value, pmcid, source, CONFIDENCE_LOW, value))
    pmid = normalize_pmid(value)
    if pmid:
        candidates.append(_candidate(IdentifierKind.PMID, value, pmid, source, CONFIDENCE_FALLBACK, value))
    return candidates


def _candidate(
    kind: IdentifierKind,
    value_raw: str,
    value_normalized: str,
    source: str,
    confidence_score: float,
    evidence_url: str | None,
) -> IdentifierCandidate:
    return IdentifierCandidate(
        kind=kind,
        value_raw=value_raw,
        value_normalized=value_normalized,
        source=source,
        confidence_score=float(confidence_score),
        evidence_url=evidence_url,
    )


def _dedup_candidates(candidates: list[IdentifierCandidate]) -> list[IdentifierCandidate]:
    deduped: dict[tuple[str, str], IdentifierCandidate] = {}
    for candidate in candidates:
        key = (candidate.kind.value, candidate.value_normalized)
        current = deduped.get(key)
        if current is None or candidate.confidence_score > current.confidence_score:
            deduped[key] = candidate
    return list(deduped.values())


async def sync_identifiers_for_publication_fields(
    db_session: AsyncSession,
    *,
    publication: Publication,
) -> None:
    candidates = _publication_field_candidates(publication)
    await _upsert_publication_candidates(db_session, publication_id=int(publication.id), candidates=candidates)


async def discover_and_sync_identifiers_for_publication(
    db_session: AsyncSession,
    *,
    publication: Publication,
    scholar_label: str,
) -> None:
    await sync_identifiers_for_publication_fields(db_session, publication=publication)

    publication_id = int(publication.id)
    if await _has_confident_identifier(
        db_session,
        publication_id=publication_id,
        kind=IdentifierKind.DOI.value,
        confidence_floor=0.0,
    ):
        return

    item = _identifier_lookup_item(publication=publication, scholar_label=scholar_label)
    has_strong_doi = await _discover_crossref_doi(
        db_session,
        publication_id=publication_id,
        item=item,
    )
    existing_arxiv = await _existing_identifier_by_kind(
        db_session,
        publication_id=publication_id,
        kind=IdentifierKind.ARXIV.value,
    )
    skip_reason = arxiv_skip_reason_for_item(
        item=item,
        has_strong_doi=has_strong_doi,
        has_existing_arxiv=existing_arxiv is not None,
    )
    if skip_reason is not None:
        return
    await _discover_arxiv_identifier(db_session, publication_id=publication_id, item=item)


def _identifier_lookup_item(
    *,
    publication: Publication,
    scholar_label: str,
) -> UnreadPublicationItem:
    from app.services.publications.types import UnreadPublicationItem

    return UnreadPublicationItem(
        publication_id=int(publication.id),
        scholar_profile_id=0,
        scholar_label=scholar_label,
        title=str(publication.title_raw or ""),
        year=publication.year,
        citation_count=publication.citation_count,
        venue_text=publication.venue_text,
        pub_url=publication.pub_url,
        pdf_url=publication.pdf_url,
    )


async def _discover_crossref_doi(
    db_session: AsyncSession,
    *,
    publication_id: int,
    item: UnreadPublicationItem,
) -> bool:
    from app.services.crossref import application as crossref_service

    discovered_doi = await crossref_service.discover_doi_for_publication(item=item)
    normalized_doi = normalize_doi(discovered_doi)
    if discovered_doi is None or normalized_doi is None:
        return False
    candidate = _candidate(
        IdentifierKind.DOI,
        discovered_doi,
        normalized_doi,
        "crossref_api",
        CONFIDENCE_MEDIUM,
        None,
    )
    await _upsert_publication_candidate(
        db_session,
        publication_id=publication_id,
        candidate=candidate,
    )
    return candidate.confidence_score >= CONFIDENCE_MEDIUM


async def _discover_arxiv_identifier(
    db_session: AsyncSession,
    *,
    publication_id: int,
    item: UnreadPublicationItem,
) -> None:
    from app.services.arxiv import application as arxiv_service

    discovered_arxiv = await arxiv_service.discover_arxiv_id_for_publication(item=item)
    normalized_arxiv = normalize_arxiv_id(discovered_arxiv)
    if discovered_arxiv is None or normalized_arxiv is None:
        return
    candidate = _candidate(
        IdentifierKind.ARXIV,
        discovered_arxiv,
        normalized_arxiv,
        "arxiv_api",
        CONFIDENCE_MEDIUM,
        None,
    )
    await _upsert_publication_candidate(
        db_session,
        publication_id=publication_id,
        candidate=candidate,
    )


async def _has_confident_identifier(
    db_session: AsyncSession,
    *,
    publication_id: int,
    kind: str,
    confidence_floor: float,
) -> bool:
    existing = await _existing_identifier_by_kind(
        db_session,
        publication_id=publication_id,
        kind=kind,
    )
    if existing is None:
        return False
    return float(existing.confidence_score) >= float(confidence_floor)


def _publication_field_candidates(publication: Publication) -> list[IdentifierCandidate]:
    return _fallback_candidates_from_values(
        doi=None,
        pub_url=publication.pub_url,
        pdf_url=publication.pdf_url,
    )


async def sync_identifiers_for_publication_resolution(
    db_session: AsyncSession,
    *,
    publication: Publication,
    source: str | None,
) -> None:
    candidates = _publication_field_candidates(publication)
    rewritten = [_candidate_with_source(candidate, source=source) for candidate in candidates]
    await _upsert_publication_candidates(db_session, publication_id=int(publication.id), candidates=rewritten)


def _candidate_with_source(candidate: IdentifierCandidate, *, source: str | None) -> IdentifierCandidate:
    if not source:
        return candidate
    return IdentifierCandidate(
        kind=candidate.kind,
        value_raw=candidate.value_raw,
        value_normalized=candidate.value_normalized,
        source=source,
        confidence_score=candidate.confidence_score,
        evidence_url=candidate.evidence_url,
    )


async def _upsert_publication_candidates(
    db_session: AsyncSession,
    *,
    publication_id: int,
    candidates: list[IdentifierCandidate],
) -> None:
    for candidate in _dedup_candidates(candidates):
        await _upsert_publication_candidate(db_session, publication_id=publication_id, candidate=candidate)


async def _upsert_publication_candidate(
    db_session: AsyncSession,
    *,
    publication_id: int,
    candidate: IdentifierCandidate,
) -> None:
    existing = await _existing_identifier(
        db_session,
        publication_id=publication_id,
        kind=candidate.kind.value,
        value_normalized=candidate.value_normalized,
    )
    if existing is None:
        db_session.add(_new_identifier_row(publication_id=publication_id, candidate=candidate))
        return
    _merge_identifier_row(existing, candidate=candidate)


async def _existing_identifier(
    db_session: AsyncSession,
    *,
    publication_id: int,
    kind: str,
    value_normalized: str,
) -> PublicationIdentifier | None:
    result = await db_session.execute(
        select(PublicationIdentifier).where(
            PublicationIdentifier.publication_id == publication_id,
            PublicationIdentifier.kind == kind,
            PublicationIdentifier.value_normalized == value_normalized,
        )
    )
    return result.scalar_one_or_none()


async def _existing_identifier_by_kind(
    db_session: AsyncSession,
    *,
    publication_id: int,
    kind: str,
) -> PublicationIdentifier | None:
    result = await db_session.execute(
        select(PublicationIdentifier)
        .where(
            PublicationIdentifier.publication_id == publication_id,
            PublicationIdentifier.kind == kind,
        )
        .order_by(PublicationIdentifier.confidence_score.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _new_identifier_row(
    *,
    publication_id: int,
    candidate: IdentifierCandidate,
) -> PublicationIdentifier:
    return PublicationIdentifier(
        publication_id=publication_id,
        kind=candidate.kind.value,
        value_raw=candidate.value_raw,
        value_normalized=candidate.value_normalized,
        source=candidate.source,
        confidence_score=candidate.confidence_score,
        evidence_url=candidate.evidence_url,
    )


def _merge_identifier_row(existing: PublicationIdentifier, *, candidate: IdentifierCandidate) -> None:
    if candidate.confidence_score >= float(existing.confidence_score):
        existing.value_raw = candidate.value_raw
        existing.source = candidate.source
        existing.confidence_score = candidate.confidence_score
        if candidate.evidence_url:
            existing.evidence_url = candidate.evidence_url


async def overlay_publication_items_with_display_identifiers(
    db_session: AsyncSession,
    *,
    items: list[PublicationListItem],
) -> list[PublicationListItem]:
    if not items:
        return []
    mapping = await _display_identifier_map(db_session, publication_ids=[item.publication_id for item in items])
    return [_overlay_publication_item(item, mapping.get(item.publication_id)) for item in items]


def _overlay_publication_item(
    item: PublicationListItem,
    display_identifier: DisplayIdentifier | None,
) -> PublicationListItem:
    fallback = display_identifier or derive_display_identifier_from_values(
        doi=None, pub_url=item.pub_url, pdf_url=item.pdf_url
    )
    return replace(item, display_identifier=fallback)


async def overlay_pdf_queue_items_with_display_identifiers(
    db_session: AsyncSession,
    *,
    items: list[PdfQueueListItem],
) -> list[PdfQueueListItem]:
    if not items:
        return []
    mapping = await _display_identifier_map(db_session, publication_ids=[item.publication_id for item in items])
    return [_overlay_queue_item(item, mapping.get(item.publication_id)) for item in items]


def _overlay_queue_item(
    item: PdfQueueListItem,
    display_identifier: DisplayIdentifier | None,
) -> PdfQueueListItem:
    fallback = display_identifier or derive_display_identifier_from_values(doi=None, pdf_url=item.pdf_url)
    return replace(item, display_identifier=fallback)


async def display_identifier_for_publication_id(
    db_session: AsyncSession,
    *,
    publication_id: int,
) -> DisplayIdentifier | None:
    normalized_id = int(publication_id)
    if normalized_id <= 0:
        raise ValueError("publication_id must be positive.")
    mapping = await _display_identifier_map(db_session, publication_ids=[normalized_id])
    display = mapping.get(normalized_id)
    if display is not None:
        return display
    publication = await db_session.get(Publication, normalized_id)
    if publication is None:
        return None
    return derive_display_identifier_from_values(
        doi=None,
        pub_url=publication.pub_url,
        pdf_url=publication.pdf_url,
    )


async def _display_identifier_map(
    db_session: AsyncSession,
    *,
    publication_ids: list[int],
) -> dict[int, DisplayIdentifier]:
    normalized_ids = sorted({int(value) for value in publication_ids if int(value) > 0})
    if not normalized_ids:
        return {}
    result = await db_session.execute(
        select(PublicationIdentifier).where(PublicationIdentifier.publication_id.in_(normalized_ids))
    )
    rows = list(result.scalars().all())
    return _best_display_identifier_map(rows)


def _best_display_identifier_map(rows: list[PublicationIdentifier]) -> dict[int, DisplayIdentifier]:
    grouped: dict[int, list[IdentifierCandidate]] = {}
    for row in rows:
        grouped.setdefault(int(row.publication_id), []).append(_candidate_from_row(row))
    return {
        publication_id: display
        for publication_id, display in (
            (publication_id, _best_display_identifier(candidates)) for publication_id, candidates in grouped.items()
        )
        if display is not None
    }


def _candidate_from_row(row: PublicationIdentifier) -> IdentifierCandidate:
    return IdentifierCandidate(
        kind=IdentifierKind(str(row.kind)),
        value_raw=str(row.value_raw),
        value_normalized=str(row.value_normalized),
        source=str(row.source),
        confidence_score=float(row.confidence_score),
        evidence_url=row.evidence_url,
    )


def _best_display_identifier(candidates: list[IdentifierCandidate]) -> DisplayIdentifier | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=_display_sort_key, reverse=True)
    return _display_identifier_from_candidate(ordered[0])


def _display_sort_key(candidate: IdentifierCandidate) -> tuple[int, float]:
    return (_kind_priority(candidate.kind), float(candidate.confidence_score))


def _kind_priority(kind: IdentifierKind) -> int:
    if kind == IdentifierKind.DOI:
        return PRIORITY_DOI
    if kind == IdentifierKind.ARXIV:
        return PRIORITY_ARXIV
    if kind == IdentifierKind.PMCID:
        return PRIORITY_PMCID
    return PRIORITY_PMID


def _display_identifier_from_candidate(candidate: IdentifierCandidate) -> DisplayIdentifier:
    value = candidate.value_normalized
    return DisplayIdentifier(
        kind=candidate.kind.value,
        value=value,
        label=_display_label(candidate.kind, value),
        url=_identifier_url(candidate.kind, value),
        confidence_score=float(candidate.confidence_score),
    )


def _display_label(kind: IdentifierKind, value: str) -> str:
    if kind == IdentifierKind.DOI:
        return f"DOI: {value}"
    if kind == IdentifierKind.ARXIV:
        return f"arXiv: {value}"
    if kind == IdentifierKind.PMCID:
        return f"PMCID: {value}"
    return f"PMID: {value}"


def _identifier_url(kind: IdentifierKind, value: str) -> str | None:
    if kind == IdentifierKind.DOI:
        return f"https://doi.org/{value}"
    if kind == IdentifierKind.ARXIV:
        return f"https://arxiv.org/abs/{value}"
    if kind == IdentifierKind.PMCID:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{value}/"
    if kind == IdentifierKind.PMID:
        return f"https://pubmed.ncbi.nlm.nih.gov/{value}/"
    return None

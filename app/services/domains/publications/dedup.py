from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Publication, PublicationIdentifier, ScholarPublication
from app.services.domains.ingestion.fingerprints import (
    canonical_title_text_for_dedup,
    canonical_title_tokens_for_dedup,
    normalize_title,
)

logger = logging.getLogger(__name__)

NEAR_DUP_DEFAULT_SIMILARITY_THRESHOLD = 0.78
NEAR_DUP_DEFAULT_CONTAINMENT_THRESHOLD = 0.92
NEAR_DUP_DEFAULT_MIN_SHARED_TOKENS = 3
NEAR_DUP_DEFAULT_MAX_YEAR_DELTA = 1
NEAR_DUP_MIN_TOKEN_LENGTH = 3
NEAR_DUP_CLUSTER_KEY_LENGTH = 16
NEAR_DUP_STOPWORDS = {
    "a",
    "an",
    "and",
    "approach",
    "for",
    "in",
    "method",
    "of",
    "on",
    "the",
    "to",
    "using",
    "via",
    "with",
}


@dataclass(frozen=True)
class NearDuplicateMember:
    publication_id: int
    title: str
    year: int | None
    citation_count: int


@dataclass(frozen=True)
class NearDuplicateCluster:
    cluster_key: str
    winner_publication_id: int
    similarity_score: float
    members: tuple[NearDuplicateMember, ...]


@dataclass(frozen=True)
class _NearDuplicateCandidate:
    publication_id: int
    title: str
    year: int | None
    citation_count: int
    canonical_text: str
    tokens: frozenset[str]


async def find_identifier_duplicate_pairs(
    db_session: AsyncSession,
) -> list[tuple[int, int]]:
    """Return (winner_id, dup_id) pairs where two publications share the same identifier."""
    pi1 = aliased(PublicationIdentifier, name="pi1")
    pi2 = aliased(PublicationIdentifier, name="pi2")
    rows = await db_session.execute(
        select(pi1.publication_id, pi2.publication_id)
        .join(
            pi2,
            (pi1.kind == pi2.kind)
            & (pi1.value_normalized == pi2.value_normalized)
            & (pi1.publication_id < pi2.publication_id),
        )
        .distinct()
    )
    return [(winner_id, dup_id) for winner_id, dup_id in rows]


async def merge_duplicate_publication(
    db_session: AsyncSession,
    *,
    winner_id: int,
    dup_id: int,
) -> None:
    """Merge dup_id into winner_id: migrate metadata/links/identifiers, then delete dup."""
    if winner_id == dup_id:
        raise ValueError("winner_id and dup_id must differ.")
    winner = await _load_publication(db_session, publication_id=winner_id)
    dup = await _load_publication(db_session, publication_id=dup_id)
    if winner is None or dup is None:
        raise ValueError("winner_id and dup_id must both exist.")
    _merge_publication_metadata(winner=winner, dup=dup)
    await _migrate_scholar_links(db_session, winner_id=winner_id, dup_id=dup_id)
    await _migrate_identifiers(db_session, winner_id=winner_id, dup_id=dup_id)
    await db_session.execute(delete(Publication).where(Publication.id == dup_id))
    logger.info(
        "publications.identifier_merge",
        extra={
            "event": "publications.identifier_merge",
            "winner_id": winner_id,
            "dup_id": dup_id,
        },
    )


async def _load_publication(
    db_session: AsyncSession,
    *,
    publication_id: int,
) -> Publication | None:
    result = await db_session.execute(
        select(Publication).where(Publication.id == publication_id)
    )
    return result.scalar_one_or_none()


def _merge_publication_metadata(*, winner: Publication, dup: Publication) -> None:
    if winner.year is None and dup.year is not None:
        winner.year = dup.year
    winner.citation_count = max(int(winner.citation_count or 0), int(dup.citation_count or 0))
    if not winner.author_text and dup.author_text:
        winner.author_text = dup.author_text
    if not winner.venue_text and dup.venue_text:
        winner.venue_text = dup.venue_text
    if not winner.pub_url and dup.pub_url:
        winner.pub_url = dup.pub_url
    if not winner.pdf_url and dup.pdf_url:
        winner.pdf_url = dup.pdf_url
    if not winner.cluster_id and dup.cluster_id:
        winner.cluster_id = dup.cluster_id
    if not winner.canonical_title_hash and dup.canonical_title_hash:
        winner.canonical_title_hash = dup.canonical_title_hash
    winner.title_raw = _preferred_title_text(winner=winner.title_raw, dup=dup.title_raw)
    winner.title_normalized = normalize_title(winner.title_raw)


def _preferred_title_text(*, winner: str, dup: str) -> str:
    winner_score = len(canonical_title_text_for_dedup(winner))
    dup_score = len(canonical_title_text_for_dedup(dup))
    if dup_score > winner_score:
        return dup
    return winner


async def _migrate_scholar_links(
    db_session: AsyncSession,
    *,
    winner_id: int,
    dup_id: int,
) -> None:
    """Move ScholarPublication links from dup to winner, dropping conflicts."""
    dup_links_result = await db_session.execute(
        select(ScholarPublication).where(ScholarPublication.publication_id == dup_id)
    )
    dup_links = dup_links_result.scalars().all()

    winner_profiles_result = await db_session.execute(
        select(ScholarPublication.scholar_profile_id).where(
            ScholarPublication.publication_id == winner_id
        )
    )
    winner_profiles: set[int] = {row for (row,) in winner_profiles_result}

    for link in dup_links:
        if link.scholar_profile_id in winner_profiles:
            await db_session.delete(link)
        else:
            link.publication_id = winner_id


async def _migrate_identifiers(
    db_session: AsyncSession,
    *,
    winner_id: int,
    dup_id: int,
) -> None:
    result = await db_session.execute(
        select(PublicationIdentifier).where(PublicationIdentifier.publication_id == dup_id)
    )
    dup_identifiers = result.scalars().all()
    for identifier in dup_identifiers:
        existing = await _find_identifier(
            db_session,
            publication_id=winner_id,
            kind=identifier.kind,
            value_normalized=identifier.value_normalized,
        )
        if existing is None:
            identifier.publication_id = winner_id
            continue
        _merge_identifier(existing=existing, dup=identifier)
        await db_session.delete(identifier)


async def _find_identifier(
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


def _merge_identifier(*, existing: PublicationIdentifier, dup: PublicationIdentifier) -> None:
    existing.confidence_score = max(
        float(existing.confidence_score),
        float(dup.confidence_score),
    )
    if not existing.evidence_url and dup.evidence_url:
        existing.evidence_url = dup.evidence_url
    if not existing.value_raw and dup.value_raw:
        existing.value_raw = dup.value_raw


async def sweep_identifier_duplicates(db_session: AsyncSession) -> int:
    """Find publications sharing an identifier and merge duplicates into the winner."""
    pairs = await find_identifier_duplicate_pairs(db_session)
    if not pairs:
        return 0

    processed_dups: set[int] = set()
    for winner_id, dup_id in pairs:
        if dup_id in processed_dups:
            continue
        processed_dups.add(dup_id)
        await merge_duplicate_publication(db_session, winner_id=winner_id, dup_id=dup_id)

    await db_session.flush()
    return len(processed_dups)


async def find_near_duplicate_clusters(
    db_session: AsyncSession,
    *,
    similarity_threshold: float = NEAR_DUP_DEFAULT_SIMILARITY_THRESHOLD,
    min_shared_tokens: int = NEAR_DUP_DEFAULT_MIN_SHARED_TOKENS,
    max_year_delta: int = NEAR_DUP_DEFAULT_MAX_YEAR_DELTA,
) -> list[NearDuplicateCluster]:
    candidates = await _load_near_duplicate_candidates(db_session)
    if len(candidates) < 2:
        return []
    groups = _cluster_candidate_groups(
        candidates,
        similarity_threshold=similarity_threshold,
        min_shared_tokens=min_shared_tokens,
        max_year_delta=max_year_delta,
    )
    clusters = [_near_duplicate_cluster(group) for group in groups]
    return sorted(clusters, key=lambda item: (-len(item.members), item.winner_publication_id))


async def merge_near_duplicate_cluster(
    db_session: AsyncSession,
    *,
    cluster: NearDuplicateCluster,
) -> int:
    winner_id = int(cluster.winner_publication_id)
    merged = 0
    for member in cluster.members:
        if int(member.publication_id) == winner_id:
            continue
        await merge_duplicate_publication(
            db_session,
            winner_id=winner_id,
            dup_id=int(member.publication_id),
        )
        merged += 1
    return merged


def near_duplicate_cluster_payload(cluster: NearDuplicateCluster) -> dict[str, object]:
    members = [
        {
            "publication_id": int(member.publication_id),
            "title": member.title,
            "year": member.year,
            "citation_count": int(member.citation_count),
        }
        for member in cluster.members
    ]
    return {
        "cluster_key": cluster.cluster_key,
        "winner_publication_id": int(cluster.winner_publication_id),
        "member_count": len(cluster.members),
        "similarity_score": float(cluster.similarity_score),
        "members": members,
    }


async def _load_near_duplicate_candidates(
    db_session: AsyncSession,
) -> list[_NearDuplicateCandidate]:
    result = await db_session.execute(
        select(
            Publication.id,
            Publication.title_raw,
            Publication.year,
            Publication.citation_count,
        )
    )
    records = [
        _candidate_from_row(
            publication_id=int(publication_id),
            title=str(title_raw or ""),
            year=year,
            citation_count=int(citation_count or 0),
        )
        for publication_id, title_raw, year, citation_count in result.all()
    ]
    return [record for record in records if record is not None]


def _candidate_from_row(
    *,
    publication_id: int,
    title: str,
    year: int | None,
    citation_count: int,
) -> _NearDuplicateCandidate | None:
    canonical = canonical_title_text_for_dedup(title)
    raw_tokens = canonical_title_tokens_for_dedup(title)
    tokens = _normalized_tokens(raw_tokens)
    if not canonical or not tokens:
        return None
    return _NearDuplicateCandidate(
        publication_id=publication_id,
        title=title,
        year=year,
        citation_count=citation_count,
        canonical_text=canonical,
        tokens=frozenset(tokens),
    )


def _normalized_tokens(tokens: Iterable[str]) -> set[str]:
    return {
        token
        for token in tokens
        if len(token) >= NEAR_DUP_MIN_TOKEN_LENGTH and token not in NEAR_DUP_STOPWORDS
    }


def _cluster_candidate_groups(
    candidates: list[_NearDuplicateCandidate],
    *,
    similarity_threshold: float,
    min_shared_tokens: int,
    max_year_delta: int,
) -> list[list[_NearDuplicateCandidate]]:
    by_id = {candidate.publication_id: candidate for candidate in candidates}
    token_index = _candidate_token_index(candidates)
    parent = {candidate.publication_id: candidate.publication_id for candidate in candidates}
    for candidate in candidates:
        peers = _candidate_peer_ids(candidate=candidate, token_index=token_index)
        for peer_id in sorted(peers):
            if peer_id <= candidate.publication_id:
                continue
            peer = by_id[peer_id]
            if _is_near_duplicate_pair(
                candidate,
                peer,
                similarity_threshold=similarity_threshold,
                min_shared_tokens=min_shared_tokens,
                max_year_delta=max_year_delta,
            ):
                _union(parent, candidate.publication_id, peer_id)
    return _grouped_candidates(candidates, parent)


def _candidate_token_index(
    candidates: list[_NearDuplicateCandidate],
) -> dict[str, set[int]]:
    index: dict[str, set[int]] = {}
    for candidate in candidates:
        for token in candidate.tokens:
            index.setdefault(token, set()).add(candidate.publication_id)
    return index


def _candidate_peer_ids(
    *,
    candidate: _NearDuplicateCandidate,
    token_index: dict[str, set[int]],
) -> set[int]:
    peers: set[int] = set()
    for token in candidate.tokens:
        peers.update(token_index.get(token, set()))
    peers.discard(candidate.publication_id)
    return peers


def _is_near_duplicate_pair(
    left: _NearDuplicateCandidate,
    right: _NearDuplicateCandidate,
    *,
    similarity_threshold: float,
    min_shared_tokens: int,
    max_year_delta: int,
) -> bool:
    if left.canonical_text == right.canonical_text:
        return True
    if not _years_compatible(left.year, right.year, max_year_delta=max_year_delta):
        return False
    shared_tokens = len(left.tokens & right.tokens)
    if shared_tokens < min_shared_tokens:
        return False
    jaccard = _jaccard(left.tokens, right.tokens)
    containment = shared_tokens / max(1, min(len(left.tokens), len(right.tokens)))
    return jaccard >= similarity_threshold or containment >= NEAR_DUP_DEFAULT_CONTAINMENT_THRESHOLD


def _years_compatible(left: int | None, right: int | None, *, max_year_delta: int) -> bool:
    if left is None or right is None:
        return True
    return abs(int(left) - int(right)) <= int(max_year_delta)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _find_root(parent: dict[int, int], value: int) -> int:
    root = parent[value]
    while root != parent[root]:
        root = parent[root]
    while value != root:
        next_value = parent[value]
        parent[value] = root
        value = next_value
    return root


def _union(parent: dict[int, int], left: int, right: int) -> None:
    left_root = _find_root(parent, left)
    right_root = _find_root(parent, right)
    if left_root == right_root:
        return
    if left_root < right_root:
        parent[right_root] = left_root
        return
    parent[left_root] = right_root


def _grouped_candidates(
    candidates: list[_NearDuplicateCandidate],
    parent: dict[int, int],
) -> list[list[_NearDuplicateCandidate]]:
    groups: dict[int, list[_NearDuplicateCandidate]] = {}
    for candidate in candidates:
        root = _find_root(parent, candidate.publication_id)
        groups.setdefault(root, []).append(candidate)
    clustered = [members for members in groups.values() if len(members) > 1]
    for members in clustered:
        members.sort(key=lambda item: item.publication_id)
    return clustered


def _near_duplicate_cluster(members: list[_NearDuplicateCandidate]) -> NearDuplicateCluster:
    winner = _winner_candidate(members)
    member_ids = [member.publication_id for member in members]
    joined = ",".join(str(publication_id) for publication_id in member_ids)
    cluster_key = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:NEAR_DUP_CLUSTER_KEY_LENGTH]
    similarity_score = _cluster_similarity_score(members)
    return NearDuplicateCluster(
        cluster_key=cluster_key,
        winner_publication_id=winner.publication_id,
        similarity_score=similarity_score,
        members=tuple(
            NearDuplicateMember(
                publication_id=member.publication_id,
                title=member.title,
                year=member.year,
                citation_count=member.citation_count,
            )
            for member in members
        ),
    )


def _winner_candidate(members: list[_NearDuplicateCandidate]) -> _NearDuplicateCandidate:
    return min(
        members,
        key=lambda member: (-int(member.citation_count), member.publication_id),
    )


def _cluster_similarity_score(members: list[_NearDuplicateCandidate]) -> float:
    best = 0.0
    for index, left in enumerate(members):
        for right in members[index + 1 :]:
            shared_tokens = len(left.tokens & right.tokens)
            jaccard = _jaccard(left.tokens, right.tokens)
            containment = shared_tokens / max(1, min(len(left.tokens), len(right.tokens)))
            best = max(best, jaccard, containment)
    return round(best, 4)

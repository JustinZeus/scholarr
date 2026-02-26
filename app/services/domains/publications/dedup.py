from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication, PublicationIdentifier, ScholarPublication

logger = logging.getLogger(__name__)


async def find_identifier_duplicate_pairs(
    db_session: AsyncSession,
) -> list[tuple[int, int]]:
    """Return (winner_id, dup_id) pairs where two publications share the same identifier.

    Winner is always the lower publication_id (earlier-created). Uses the existing
    ix_publication_identifiers_kind_value index for the self-join.
    """
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
    """Merge dup_id into winner_id: migrate scholar links, then delete the dup."""
    await _migrate_scholar_links(db_session, winner_id=winner_id, dup_id=dup_id)
    await db_session.execute(
        delete(Publication).where(Publication.id == dup_id)
    )
    logger.info(
        "publications.identifier_merge",
        extra={
            "event": "publications.identifier_merge",
            "winner_id": winner_id,
            "dup_id": dup_id,
        },
    )


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


async def sweep_identifier_duplicates(db_session: AsyncSession) -> int:
    """Find publications sharing an identifier and merge duplicates into the winner.

    Returns the number of duplicate publications removed.
    """
    pairs = await find_identifier_duplicate_pairs(db_session)
    if not pairs:
        return 0

    # Deduplicate the pairs — a dup may appear multiple times if it shares
    # several identifiers with the winner; process each dup only once.
    processed_dups: set[int] = set()
    for winner_id, dup_id in pairs:
        if dup_id in processed_dups:
            continue
        processed_dups.add(dup_id)
        await merge_duplicate_publication(db_session, winner_id=winner_id, dup_id=dup_id)

    await db_session.flush()
    return len(processed_dups)

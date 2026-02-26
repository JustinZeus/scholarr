"""Unit tests for the identifier-based publication dedup sweep.

DB operations are mocked via AsyncMock so no database is required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import ScholarPublication
from app.services.domains.publications.dedup import (
    find_identifier_duplicate_pairs,
    merge_duplicate_publication,
    sweep_identifier_duplicates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(rows: list) -> MagicMock:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_result.__iter__ = lambda self: iter(rows)
    return mock_result


def _session_with_execute_sequence(results: list) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_make_result(r) for r in results])
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# find_identifier_duplicate_pairs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_identifier_duplicate_pairs_returns_pairs() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_result([(1, 2)]))

    pairs = await find_identifier_duplicate_pairs(session)

    assert pairs == [(1, 2)]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_identifier_duplicate_pairs_returns_empty_when_no_duplicates() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_result([]))

    pairs = await find_identifier_duplicate_pairs(session)

    assert pairs == []


# ---------------------------------------------------------------------------
# merge_duplicate_publication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merge_duplicate_migrates_orphaned_scholar_links() -> None:
    """Scholar link that only the dup has should be migrated to winner."""
    dup_link = MagicMock(spec=ScholarPublication)
    dup_link.scholar_profile_id = 99
    dup_link.publication_id = 2

    session = _session_with_execute_sequence(
        results=[
            [dup_link],  # dup links
            [],          # winner profile ids (no conflict)
            [],          # execute(delete(Publication)) result
        ]
    )

    await merge_duplicate_publication(session, winner_id=1, dup_id=2)

    assert dup_link.publication_id == 1
    session.delete.assert_not_awaited()  # not deleted; migrated instead


@pytest.mark.asyncio
async def test_merge_duplicate_drops_conflicting_scholar_link() -> None:
    """When winner already has a link for the same scholar, dup's link is deleted."""
    dup_link = MagicMock(spec=ScholarPublication)
    dup_link.scholar_profile_id = 88
    dup_link.publication_id = 2

    session = _session_with_execute_sequence(
        results=[
            [dup_link],    # dup links
            [(88,)],       # winner profiles (conflict: profile 88 already linked)
            [],            # execute(delete(Publication)) result
        ]
    )

    await merge_duplicate_publication(session, winner_id=1, dup_id=2)

    session.delete.assert_awaited_once_with(dup_link)
    assert dup_link.publication_id == 2  # unchanged — link was deleted, not migrated


# ---------------------------------------------------------------------------
# sweep_identifier_duplicates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sweep_returns_zero_when_no_pairs() -> None:
    with patch(
        "app.services.domains.publications.dedup.find_identifier_duplicate_pairs",
        new=AsyncMock(return_value=[]),
    ):
        session = AsyncMock()
        count = await sweep_identifier_duplicates(session)

    assert count == 0
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_returns_merge_count() -> None:
    with (
        patch(
            "app.services.domains.publications.dedup.find_identifier_duplicate_pairs",
            new=AsyncMock(return_value=[(1, 2), (3, 4)]),
        ),
        patch(
            "app.services.domains.publications.dedup.merge_duplicate_publication",
            new=AsyncMock(),
        ) as mock_merge,
    ):
        session = AsyncMock()
        count = await sweep_identifier_duplicates(session)

    assert count == 2
    assert mock_merge.await_count == 2
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_merges_each_dup_only_once() -> None:
    """A dup sharing two identifiers with the winner appears twice in pairs but merged once."""
    with (
        patch(
            "app.services.domains.publications.dedup.find_identifier_duplicate_pairs",
            new=AsyncMock(return_value=[(1, 2), (1, 2)]),
        ),
        patch(
            "app.services.domains.publications.dedup.merge_duplicate_publication",
            new=AsyncMock(),
        ) as mock_merge,
    ):
        session = AsyncMock()
        count = await sweep_identifier_duplicates(session)

    assert count == 1
    assert mock_merge.await_count == 1

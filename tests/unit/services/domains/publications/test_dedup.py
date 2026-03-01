"""Unit tests for publication dedup operations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import ScholarPublication
from app.services.publications import dedup as dedup_service
from app.services.publications.dedup import (
    NearDuplicateCluster,
    NearDuplicateMember,
    find_identifier_duplicate_pairs,
    find_near_duplicate_clusters,
    merge_duplicate_publication,
    merge_near_duplicate_cluster,
    sweep_identifier_duplicates,
)


def _make_result(rows: list) -> MagicMock:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_result.__iter__ = lambda self: iter(rows)
    mock_result.all.return_value = rows
    return mock_result


def _session_with_execute_sequence(results: list) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_make_result(r) for r in results])
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


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


@pytest.mark.asyncio
async def test_merge_duplicate_publication_migrates_links_and_identifiers() -> None:
    session = AsyncMock()
    winner = SimpleNamespace(
        year=2014,
        citation_count=10,
        author_text=None,
        venue_text=None,
        pub_url=None,
        pdf_url=None,
        cluster_id=None,
        canonical_title_hash=None,
        title_raw="winner",
        title_normalized="winner",
    )
    dup = SimpleNamespace(
        year=2015,
        citation_count=11,
        author_text="a",
        venue_text="v",
        pub_url="https://example.org",
        pdf_url="https://example.org/a.pdf",
        cluster_id="x",
        canonical_title_hash="hash",
        title_raw="dup",
        title_normalized="dup",
    )

    with (
        patch(
            "app.services.publications.dedup._load_publication",
            new=AsyncMock(side_effect=[winner, dup]),
        ),
        patch(
            "app.services.publications.dedup._migrate_scholar_links",
            new=AsyncMock(),
        ) as mock_links,
        patch(
            "app.services.publications.dedup._migrate_identifiers",
            new=AsyncMock(),
        ) as mock_identifiers,
    ):
        await merge_duplicate_publication(session, winner_id=1, dup_id=2)

    assert session.execute.await_count == 1
    mock_links.assert_awaited_once_with(session, winner_id=1, dup_id=2)
    mock_identifiers.assert_awaited_once_with(session, winner_id=1, dup_id=2)


@pytest.mark.asyncio
async def test_merge_duplicate_publication_rejects_missing_publications() -> None:
    session = AsyncMock()

    with (
        patch(
            "app.services.publications.dedup._load_publication",
            new=AsyncMock(side_effect=[None, None]),
        ),
        pytest.raises(ValueError),
    ):
        await merge_duplicate_publication(session, winner_id=1, dup_id=2)


@pytest.mark.asyncio
async def test_migrate_scholar_links_moves_orphans() -> None:
    dup_link = MagicMock(spec=ScholarPublication)
    dup_link.scholar_profile_id = 99
    dup_link.publication_id = 2

    session = _session_with_execute_sequence(
        results=[
            [dup_link],
            [],
        ]
    )

    await dedup_service._migrate_scholar_links(session, winner_id=1, dup_id=2)

    assert dup_link.publication_id == 1
    session.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_migrate_scholar_links_drops_conflicts() -> None:
    dup_link = MagicMock(spec=ScholarPublication)
    dup_link.scholar_profile_id = 88
    dup_link.publication_id = 2

    session = _session_with_execute_sequence(
        results=[
            [dup_link],
            [(88,)],
        ]
    )

    await dedup_service._migrate_scholar_links(session, winner_id=1, dup_id=2)

    session.delete.assert_awaited_once_with(dup_link)


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_no_pairs() -> None:
    with patch(
        "app.services.publications.dedup.find_identifier_duplicate_pairs",
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
            "app.services.publications.dedup.find_identifier_duplicate_pairs",
            new=AsyncMock(return_value=[(1, 2), (3, 4)]),
        ),
        patch(
            "app.services.publications.dedup.merge_duplicate_publication",
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
    with (
        patch(
            "app.services.publications.dedup.find_identifier_duplicate_pairs",
            new=AsyncMock(return_value=[(1, 2), (1, 2)]),
        ),
        patch(
            "app.services.publications.dedup.merge_duplicate_publication",
            new=AsyncMock(),
        ) as mock_merge,
    ):
        session = AsyncMock()
        count = await sweep_identifier_duplicates(session)

    assert count == 1
    assert mock_merge.await_count == 1


@pytest.mark.asyncio
async def test_find_near_duplicate_clusters_groups_similar_titles() -> None:
    first = dedup_service._candidate_from_row(
        publication_id=10,
        title="Adam: A method for stochastic optimization",
        year=2014,
        citation_count=100,
    )
    second = dedup_service._candidate_from_row(
        publication_id=11,
        title="â€ œAdam: A method for stochastic optimization, â€ 3rd Int. Conf. Learn. Represent.",
        year=2015,
        citation_count=50,
    )
    assert first is not None
    assert second is not None

    with patch(
        "app.services.publications.dedup._load_near_duplicate_candidates",
        new=AsyncMock(return_value=[first, second]),
    ):
        clusters = await find_near_duplicate_clusters(AsyncMock())

    assert len(clusters) == 1
    assert len(clusters[0].members) == 2
    assert clusters[0].winner_publication_id == 10


@pytest.mark.asyncio
async def test_find_near_duplicate_clusters_skips_unrelated_titles() -> None:
    first = dedup_service._candidate_from_row(
        publication_id=21,
        title="Adam optimizer",
        year=2014,
        citation_count=10,
    )
    second = dedup_service._candidate_from_row(
        publication_id=22,
        title="Diffusion models in vision",
        year=2022,
        citation_count=10,
    )
    assert first is not None
    assert second is not None

    with patch(
        "app.services.publications.dedup._load_near_duplicate_candidates",
        new=AsyncMock(return_value=[first, second]),
    ):
        clusters = await find_near_duplicate_clusters(AsyncMock())

    assert clusters == []


@pytest.mark.asyncio
async def test_merge_near_duplicate_cluster_merges_non_winner_members() -> None:
    cluster = NearDuplicateCluster(
        cluster_key="abc",
        winner_publication_id=5,
        similarity_score=1.0,
        members=(
            NearDuplicateMember(publication_id=5, title="Winner", year=2014, citation_count=10),
            NearDuplicateMember(publication_id=6, title="Dup", year=2014, citation_count=3),
            NearDuplicateMember(publication_id=7, title="Dup2", year=2014, citation_count=1),
        ),
    )

    with patch(
        "app.services.publications.dedup.merge_duplicate_publication",
        new=AsyncMock(),
    ) as mock_merge:
        merged = await merge_near_duplicate_cluster(AsyncMock(), cluster=cluster)

    assert merged == 2
    assert mock_merge.await_count == 2

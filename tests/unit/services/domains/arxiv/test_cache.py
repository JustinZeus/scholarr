from __future__ import annotations

import asyncio
import gc
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArxivQueryCacheEntry
from app.services.domains.arxiv.cache import (
    build_query_fingerprint,
    get_cached_feed,
    run_with_inflight_dedupe,
    set_cached_feed,
)
from app.services.domains.arxiv.types import ArxivEntry, ArxivFeed, ArxivOpenSearchMeta


def _sample_feed(arxiv_id: str = "1234.5678") -> ArxivFeed:
    return ArxivFeed(
        entries=[
            ArxivEntry(
                entry_id_url=f"https://arxiv.org/abs/{arxiv_id}",
                arxiv_id=arxiv_id,
                title="Sample",
                summary="Summary",
                published=None,
                updated=None,
            )
        ],
        opensearch=ArxivOpenSearchMeta(total_results=1, start_index=0, items_per_page=1),
    )


def test_build_query_fingerprint_normalizes_search_and_id_params() -> None:
    first = build_query_fingerprint(
        params={
            "search_query": '  TI:"Quantum   Fields"   AND AU:"Doe" ',
            "start": 0,
            "max_results": 3,
        }
    )
    second = build_query_fingerprint(
        params={
            "search_query": 'ti:"quantum fields" and au:"doe"',
            "start": 0,
            "max_results": 3,
        }
    )
    third = build_query_fingerprint(params={"id_list": " 2222.0002,1111.0001 "})
    fourth = build_query_fingerprint(params={"id_list": "1111.0001, 2222.0002"})

    assert first == second
    assert third == fourth


@pytest.mark.asyncio
async def test_cache_entry_expires_and_is_deleted(db_session: AsyncSession) -> None:
    query_fingerprint = build_query_fingerprint(params={"search_query": "ti:test", "start": 0})
    now_utc = datetime(2026, 2, 26, 12, 0, tzinfo=UTC)

    await set_cached_feed(
        query_fingerprint=query_fingerprint,
        feed=_sample_feed(),
        ttl_seconds=5.0,
        max_entries=16,
        now_utc=now_utc,
    )

    hit = await get_cached_feed(
        query_fingerprint=query_fingerprint,
        now_utc=now_utc + timedelta(seconds=2),
    )
    miss = await get_cached_feed(
        query_fingerprint=query_fingerprint,
        now_utc=now_utc + timedelta(seconds=8),
    )

    result = await db_session.execute(
        select(ArxivQueryCacheEntry).where(ArxivQueryCacheEntry.query_fingerprint == query_fingerprint)
    )
    assert hit is not None
    assert miss is None
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_inflight_dedupe_coalesces_identical_requests() -> None:
    calls = {"count": 0}

    async def _fetch_feed() -> ArxivFeed:
        calls["count"] += 1
        await asyncio.sleep(0.05)
        return _sample_feed("9999.0001")

    first, second = await asyncio.gather(
        run_with_inflight_dedupe(query_fingerprint="same-key", fetch_feed=_fetch_feed),
        run_with_inflight_dedupe(query_fingerprint="same-key", fetch_feed=_fetch_feed),
    )

    assert calls["count"] == 1
    assert first.entries[0].arxiv_id == "9999.0001"
    assert second.entries[0].arxiv_id == "9999.0001"


@pytest.mark.asyncio
async def test_inflight_owner_failure_without_joiner_has_no_unretrieved_exception() -> None:
    loop = asyncio.get_running_loop()
    messages: list[str] = []
    previous_handler = loop.get_exception_handler()

    def _capture_exception(_loop, context) -> None:
        messages.append(str(context.get("message", "")))

    loop.set_exception_handler(_capture_exception)
    try:

        async def _failing_fetch() -> ArxivFeed:
            raise RuntimeError("owner_failed")

        with pytest.raises(RuntimeError, match="owner_failed"):
            await run_with_inflight_dedupe(
                query_fingerprint="owner-failure-no-joiner",
                fetch_feed=_failing_fetch,
            )
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert "Future exception was never retrieved" not in " | ".join(messages)

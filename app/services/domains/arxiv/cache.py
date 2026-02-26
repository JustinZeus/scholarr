from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from app.db.models import ArxivQueryCacheEntry
from app.db.session import get_session_factory
from app.services.domains.arxiv.constants import ARXIV_CACHE_FINGERPRINT_VERSION
from app.services.domains.arxiv.types import ArxivEntry, ArxivFeed, ArxivOpenSearchMeta

_INFLIGHT_LOCK = asyncio.Lock()
_INFLIGHT_FEEDS: dict[str, asyncio.Future[ArxivFeed]] = {}


def build_query_fingerprint(*, params: Mapping[str, object]) -> str:
    canonical = _canonical_cache_payload(params=params)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload = f"{ARXIV_CACHE_FINGERPRINT_VERSION}:{encoded}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def get_cached_feed(
    *,
    query_fingerprint: str,
    now_utc: datetime | None = None,
) -> ArxivFeed | None:
    timestamp = _as_utc(now_utc)
    session_factory = get_session_factory()
    async with session_factory() as db_session, db_session.begin():
        result = await db_session.execute(
            select(ArxivQueryCacheEntry).where(ArxivQueryCacheEntry.query_fingerprint == query_fingerprint)
        )
        entry = result.scalar_one_or_none()
        return await _validate_cached_entry(db_session, entry=entry, now_utc=timestamp)


async def set_cached_feed(
    *,
    query_fingerprint: str,
    feed: ArxivFeed,
    ttl_seconds: float,
    max_entries: int,
    now_utc: datetime | None = None,
) -> None:
    timestamp = _as_utc(now_utc)
    session_factory = get_session_factory()
    async with session_factory() as db_session, db_session.begin():
        await _write_cached_entry(
            db_session,
            query_fingerprint=query_fingerprint,
            feed=feed,
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
            now_utc=timestamp,
        )


async def run_with_inflight_dedupe(
    *,
    query_fingerprint: str,
    fetch_feed: Callable[[], Awaitable[ArxivFeed]],
) -> ArxivFeed:
    future, is_owner = await _reserve_inflight_future(query_fingerprint=query_fingerprint)
    if not is_owner:
        return await asyncio.shield(future)
    try:
        result = await fetch_feed()
    except Exception as exc:
        _complete_future(future, error=exc)
        raise
    finally:
        await _release_inflight_future(query_fingerprint=query_fingerprint, future=future)
    _complete_future(future, result=result)
    return result


def _canonical_cache_payload(*, params: Mapping[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in sorted(params.keys()):
        payload[str(key)] = _normalize_param_value(str(key), params[key])
    return payload


def _normalize_param_value(key: str, value: object) -> object:
    if key == "search_query":
        return _normalize_search_query(str(value or ""))
    if key == "id_list":
        return _normalize_id_list(str(value or ""))
    if isinstance(value, str):
        return " ".join(value.strip().split())
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value).strip()


def _normalize_search_query(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_id_list(value: str) -> str:
    normalized = [item.strip().lower() for item in value.split(",") if item.strip()]
    return ",".join(sorted(normalized))


async def _validate_cached_entry(
    db_session,
    *,
    entry: ArxivQueryCacheEntry | None,
    now_utc: datetime,
) -> ArxivFeed | None:
    if entry is None:
        return None
    if _as_utc(entry.expires_at) <= now_utc:
        await db_session.delete(entry)
        return None
    parsed = _deserialize_feed(entry.payload)
    if parsed is None:
        await db_session.delete(entry)
        return None
    return parsed


async def _write_cached_entry(
    db_session,
    *,
    query_fingerprint: str,
    feed: ArxivFeed,
    ttl_seconds: float,
    max_entries: int,
    now_utc: datetime,
) -> None:
    ttl = max(float(ttl_seconds), 0.0)
    result = await db_session.execute(
        select(ArxivQueryCacheEntry).where(ArxivQueryCacheEntry.query_fingerprint == query_fingerprint)
    )
    existing = result.scalar_one_or_none()
    if ttl <= 0.0:
        if existing is not None:
            await db_session.delete(existing)
        return
    expires_at = now_utc + timedelta(seconds=ttl)
    payload = _serialize_feed(feed)
    if existing is None:
        db_session.add(
            ArxivQueryCacheEntry(
                query_fingerprint=query_fingerprint,
                payload=payload,
                expires_at=expires_at,
                cached_at=now_utc,
                updated_at=now_utc,
            )
        )
    else:
        existing.payload = payload
        existing.expires_at = expires_at
        existing.cached_at = now_utc
        existing.updated_at = now_utc
    await _prune_cache_entries(db_session, now_utc=now_utc, max_entries=max_entries)


async def _prune_cache_entries(
    db_session,
    *,
    now_utc: datetime,
    max_entries: int,
) -> None:
    await db_session.execute(delete(ArxivQueryCacheEntry).where(ArxivQueryCacheEntry.expires_at <= now_utc))
    bounded_max_entries = int(max_entries)
    if bounded_max_entries <= 0:
        return
    count_result = await db_session.execute(select(func.count()).select_from(ArxivQueryCacheEntry))
    entry_count = int(count_result.scalar_one() or 0)
    overflow = max(0, entry_count - bounded_max_entries)
    if overflow <= 0:
        return
    stale_result = await db_session.execute(
        select(ArxivQueryCacheEntry.query_fingerprint).order_by(ArxivQueryCacheEntry.cached_at.asc()).limit(overflow)
    )
    stale_keys = [str(row[0]) for row in stale_result.all()]
    if stale_keys:
        await db_session.execute(
            delete(ArxivQueryCacheEntry).where(ArxivQueryCacheEntry.query_fingerprint.in_(stale_keys))
        )


def _serialize_feed(feed: ArxivFeed) -> dict[str, Any]:
    return asdict(feed)


def _deserialize_feed(payload: object) -> ArxivFeed | None:
    if not isinstance(payload, dict):
        return None
    entries_payload = payload.get("entries")
    opensearch_payload = payload.get("opensearch")
    if not isinstance(entries_payload, list):
        return None
    entries: list[ArxivEntry] = []
    for value in entries_payload:
        entry = _deserialize_entry(value)
        if entry is None:
            return None
        entries.append(entry)
    opensearch = _deserialize_opensearch(opensearch_payload)
    if opensearch is None:
        return None
    return ArxivFeed(entries=entries, opensearch=opensearch)


def _deserialize_entry(value: object) -> ArxivEntry | None:
    if not isinstance(value, dict):
        return None
    try:
        return ArxivEntry(
            entry_id_url=str(value["entry_id_url"]),
            arxiv_id=_as_optional_string(value.get("arxiv_id")),
            title=str(value["title"]),
            summary=str(value["summary"]),
            published=_as_optional_string(value.get("published")),
            updated=_as_optional_string(value.get("updated")),
            authors=_as_string_list(value.get("authors")),
            links=_as_string_list(value.get("links")),
            categories=_as_string_list(value.get("categories")),
            primary_category=_as_optional_string(value.get("primary_category")),
        )
    except KeyError:
        return None


def _deserialize_opensearch(value: object) -> ArxivOpenSearchMeta | None:
    if not isinstance(value, dict):
        return None
    try:
        return ArxivOpenSearchMeta(
            total_results=int(value.get("total_results", 0)),
            start_index=int(value.get("start_index", 0)),
            items_per_page=int(value.get("items_per_page", 0)),
        )
    except (TypeError, ValueError):
        return None


def _as_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def _reserve_inflight_future(
    *,
    query_fingerprint: str,
) -> tuple[asyncio.Future[ArxivFeed], bool]:
    async with _INFLIGHT_LOCK:
        existing = _INFLIGHT_FEEDS.get(query_fingerprint)
        if existing is not None:
            return existing, False
        loop = asyncio.get_running_loop()
        created = loop.create_future()
        created.add_done_callback(_consume_unretrieved_future_exception)
        _INFLIGHT_FEEDS[query_fingerprint] = created
        return created, True


async def _release_inflight_future(
    *,
    query_fingerprint: str,
    future: asyncio.Future[ArxivFeed],
) -> None:
    async with _INFLIGHT_LOCK:
        current = _INFLIGHT_FEEDS.get(query_fingerprint)
        if current is future:
            _INFLIGHT_FEEDS.pop(query_fingerprint, None)


def _complete_future(
    future: asyncio.Future[ArxivFeed],
    *,
    result: ArxivFeed | None = None,
    error: Exception | None = None,
) -> None:
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
        return
    if result is None:
        raise RuntimeError("in-flight future completion requires result or error")
    future.set_result(result)


def _consume_unretrieved_future_exception(future: asyncio.Future[ArxivFeed]) -> None:
    if future.cancelled():
        return
    try:
        _ = future.exception()
    except Exception:
        return

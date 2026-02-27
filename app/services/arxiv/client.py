from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx

from app.logging_utils import structured_log
from app.services.arxiv.cache import (
    build_query_fingerprint,
    get_cached_feed,
    run_with_inflight_dedupe,
    set_cached_feed,
)
from app.services.arxiv.constants import (
    ARXIV_SOURCE_PATH_LOOKUP_IDS,
    ARXIV_SOURCE_PATH_SEARCH,
    ARXIV_SOURCE_PATH_UNKNOWN,
)
from app.services.arxiv.errors import ArxivClientValidationError, ArxivRateLimitError
from app.services.arxiv.parser import parse_arxiv_feed
from app.services.arxiv.rate_limit import get_arxiv_cooldown_status, run_with_global_arxiv_limit
from app.services.arxiv.types import ArxivFeed
from app.settings import settings

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ARXIV_QUERY_START = 0
_ARXIV_MAX_RESULTS_LIMIT = 30_000
_ARXIV_SORT_BY_ALLOWED = {"relevance", "lastUpdatedDate", "submittedDate"}
_ARXIV_SORT_ORDER_ALLOWED = {"ascending", "descending"}
_FALLBACK_CONTACT_EMAIL = "unknown@example.com"

ArxivRequestFn = Callable[..., Awaitable[httpx.Response]]
logger = logging.getLogger(__name__)


class ArxivClient:
    def __init__(
        self,
        *,
        request_fn: ArxivRequestFn | None = None,
        cache_enabled: bool | None = None,
    ) -> None:
        self._request_fn = request_fn or _request_arxiv_feed
        self._cache_enabled = _resolve_cache_enabled(
            cache_enabled=cache_enabled,
            request_fn=request_fn,
        )
        self._cache_ttl_seconds = _cache_ttl_seconds()
        self._cache_max_entries = _cache_max_entries()

    async def search(
        self,
        *,
        query: str,
        start: int = _ARXIV_QUERY_START,
        max_results: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        request_email: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ArxivFeed:
        params = _search_params(
            query=query,
            start=start,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return await self._fetch_feed(
            params=params,
            request_email=request_email,
            timeout_seconds=timeout_seconds,
            source_path=ARXIV_SOURCE_PATH_SEARCH,
        )

    async def lookup_ids(
        self,
        *,
        id_list: list[str],
        start: int = _ARXIV_QUERY_START,
        max_results: int | None = None,
        request_email: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ArxivFeed:
        params = _lookup_params(id_list=id_list, start=start, max_results=max_results)
        return await self._fetch_feed(
            params=params,
            request_email=request_email,
            timeout_seconds=timeout_seconds,
            source_path=ARXIV_SOURCE_PATH_LOOKUP_IDS,
        )

    async def _fetch_feed(
        self,
        *,
        params: dict[str, object],
        request_email: str | None,
        timeout_seconds: float | None,
        source_path: str,
    ) -> ArxivFeed:
        query_fingerprint = build_query_fingerprint(params=params)
        if self._cache_enabled:
            cached = await get_cached_feed(query_fingerprint=query_fingerprint)
            if cached is not None:
                structured_log(
                    logger, "info", "arxiv.cache_hit", query_fingerprint=query_fingerprint, source_path=source_path
                )
                return cached
            structured_log(
                logger, "info", "arxiv.cache_miss", query_fingerprint=query_fingerprint, source_path=source_path
            )
        return await run_with_inflight_dedupe(
            query_fingerprint=query_fingerprint,
            fetch_feed=lambda: self._fetch_live_feed(
                params=params,
                request_email=request_email,
                timeout_seconds=timeout_seconds,
                query_fingerprint=query_fingerprint,
            ),
        )

    async def _fetch_live_feed(
        self,
        *,
        params: dict[str, object],
        request_email: str | None,
        timeout_seconds: float | None,
        query_fingerprint: str,
    ) -> ArxivFeed:
        response = await self._request_fn(
            params=params,
            request_email=request_email,
            timeout_seconds=timeout_seconds,
        )
        response.raise_for_status()
        feed = parse_arxiv_feed(response.text)
        if self._cache_enabled:
            await set_cached_feed(
                query_fingerprint=query_fingerprint,
                feed=feed,
                ttl_seconds=self._cache_ttl_seconds,
                max_entries=self._cache_max_entries,
            )
        return feed


def _search_params(
    *,
    query: str,
    start: int,
    max_results: int | None,
    sort_by: str | None,
    sort_order: str | None,
) -> dict[str, object]:
    clean_query = query.strip()
    if not clean_query:
        raise ArxivClientValidationError("search query must not be empty")
    params: dict[str, object] = {
        "search_query": clean_query,
        "start": _validate_start(start),
        "max_results": _validate_max_results(max_results),
    }
    if sort_by is not None:
        params["sortBy"] = _validate_sort_by(sort_by)
    if sort_order is not None:
        params["sortOrder"] = _validate_sort_order(sort_order)
    return params


def _lookup_params(*, id_list: list[str], start: int, max_results: int | None) -> dict[str, object]:
    normalized_ids = [value.strip() for value in id_list if value and value.strip()]
    if not normalized_ids:
        raise ArxivClientValidationError("id_list must include at least one id")
    return {
        "id_list": ",".join(normalized_ids),
        "start": _validate_start(start),
        "max_results": _validate_max_results(max_results),
    }


def _validate_start(value: int) -> int:
    start = int(value)
    if start < 0:
        raise ArxivClientValidationError("start must be >= 0")
    return start


def _validate_max_results(value: int | None) -> int:
    if value is None:
        default_value = int(settings.arxiv_default_max_results)
        return max(default_value, 1)
    parsed = int(value)
    if parsed < 1:
        raise ArxivClientValidationError("max_results must be >= 1")
    if parsed > _ARXIV_MAX_RESULTS_LIMIT:
        raise ArxivClientValidationError(f"max_results must be <= {_ARXIV_MAX_RESULTS_LIMIT}")
    return parsed


def _validate_sort_by(value: str) -> str:
    if value not in _ARXIV_SORT_BY_ALLOWED:
        raise ArxivClientValidationError(f"sort_by must be one of: {sorted(_ARXIV_SORT_BY_ALLOWED)!r}")
    return value


def _validate_sort_order(value: str) -> str:
    if value not in _ARXIV_SORT_ORDER_ALLOWED:
        raise ArxivClientValidationError(f"sort_order must be one of: {sorted(_ARXIV_SORT_ORDER_ALLOWED)!r}")
    return value


async def _request_arxiv_feed(
    *,
    params: dict[str, object],
    request_email: str | None,
    timeout_seconds: float | None,
) -> httpx.Response:
    source_path = _source_path_from_params(params)
    cooldown_status = await get_arxiv_cooldown_status()
    if cooldown_status.is_active:
        structured_log(
            logger,
            "warning",
            "arxiv.request_skipped_cooldown",
            source_path=source_path,
            cooldown_remaining_seconds=float(cooldown_status.remaining_seconds),
        )
        raise ArxivRateLimitError(f"arXiv global cooldown active ({cooldown_status.remaining_seconds:.0f}s remaining)")

    async def _fetch() -> httpx.Response:
        timeout_value = _timeout_seconds(timeout_seconds)
        headers = {"User-Agent": f"scholar-scraper/1.0 (mailto:{_contact_email(request_email)})"}
        async with httpx.AsyncClient(timeout=timeout_value, follow_redirects=True, headers=headers) as client:
            return await client.get(_ARXIV_API_URL, params=params)

    return await run_with_global_arxiv_limit(
        fetch=_fetch,
        source_path=source_path,
    )


def _timeout_seconds(timeout_seconds: float | None) -> float:
    if timeout_seconds is not None:
        return max(float(timeout_seconds), 0.5)
    return max(float(settings.arxiv_timeout_seconds), 0.5)


def _contact_email(request_email: str | None) -> str:
    return request_email or settings.arxiv_mailto or settings.crossref_api_mailto or _FALLBACK_CONTACT_EMAIL


def _resolve_cache_enabled(
    *,
    cache_enabled: bool | None,
    request_fn: ArxivRequestFn | None,
) -> bool:
    if cache_enabled is not None:
        return bool(cache_enabled)
    if request_fn is not None:
        return False
    return _cache_ttl_seconds() > 0.0


def _cache_ttl_seconds() -> float:
    return max(float(settings.arxiv_cache_ttl_seconds), 0.0)


def _cache_max_entries() -> int:
    return max(int(settings.arxiv_cache_max_entries), 0)


def _source_path_from_params(params: dict[str, object]) -> str:
    if "search_query" in params:
        return ARXIV_SOURCE_PATH_SEARCH
    if "id_list" in params:
        return ARXIV_SOURCE_PATH_LOOKUP_IDS
    return ARXIV_SOURCE_PATH_UNKNOWN

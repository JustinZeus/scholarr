from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.logging_utils import structured_log
from app.services.scholar import rate_limit as scholar_rate_limit
from app.settings import settings

SCHOLAR_PROFILE_URL = "https://scholar.google.com/citations"
DEFAULT_PAGE_SIZE = 100

DEFAULT_USER_AGENTS = [
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.1 Safari/605.1.15"
    ),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"),
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    status_code: int | None
    final_url: str | None
    body: str
    error: str | None


class ScholarSource(Protocol):
    async def fetch_profile_html(self, scholar_id: str) -> FetchResult: ...

    async def fetch_profile_page_html(
        self,
        scholar_id: str,
        *,
        cstart: int,
        pagesize: int,
    ) -> FetchResult: ...

    async def fetch_author_search_html(
        self,
        query: str,
        *,
        start: int,
    ) -> FetchResult: ...


class LiveScholarSource:
    def __init__(
        self,
        *,
        timeout_seconds: float = 25.0,
        min_interval_seconds: float | None = None,
        user_agents: list[str] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        configured_interval = (
            float(settings.ingestion_min_request_delay_seconds)
            if min_interval_seconds is None
            else float(min_interval_seconds)
        )
        self._min_interval_seconds = max(configured_interval, 0.0)
        self._user_agents = user_agents or DEFAULT_USER_AGENTS

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        return await self.fetch_profile_page_html(
            scholar_id,
            cstart=0,
            pagesize=DEFAULT_PAGE_SIZE,
        )

    async def fetch_profile_page_html(
        self,
        scholar_id: str,
        *,
        cstart: int,
        pagesize: int = DEFAULT_PAGE_SIZE,
    ) -> FetchResult:
        requested_url = _build_profile_url(
            scholar_id=scholar_id,
            cstart=cstart,
            pagesize=pagesize,
        )
        return await self._fetch_with_global_throttle(requested_url)

    async def fetch_author_search_html(
        self,
        query: str,
        *,
        start: int = 0,
    ) -> FetchResult:
        requested_url = _build_author_search_url(
            query=query,
            start=start,
        )
        return await self._fetch_with_global_throttle(requested_url)

    async def fetch_publication_html(self, publication_url: str) -> FetchResult:
        return await self._fetch_with_global_throttle(publication_url)

    async def _fetch_with_global_throttle(self, requested_url: str) -> FetchResult:
        await scholar_rate_limit.wait_for_scholar_slot(
            min_interval_seconds=self._min_interval_seconds,
        )
        return await asyncio.to_thread(self._fetch_sync, requested_url)

    def _build_request(self, requested_url: str) -> Request:
        return Request(
            requested_url,
            headers={
                "User-Agent": random.choice(self._user_agents),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "close",
            },
        )

    @staticmethod
    def _http_error_body(exc: HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _network_error_result(requested_url: str, exc: URLError) -> FetchResult:
        structured_log(
            logger,
            "warning",
            "scholar_source.fetch_network_error",
            requested_url=requested_url,
        )
        return FetchResult(
            requested_url=requested_url,
            status_code=None,
            final_url=None,
            body="",
            error=str(exc),
        )

    @staticmethod
    def _http_error_result(requested_url: str, exc: HTTPError) -> FetchResult:
        structured_log(
            logger,
            "warning",
            "scholar_source.fetch_http_error",
            requested_url=requested_url,
            status_code=exc.code,
        )
        return FetchResult(
            requested_url=requested_url,
            status_code=exc.code,
            final_url=exc.geturl(),
            body=LiveScholarSource._http_error_body(exc),
            error=str(exc),
        )

    @staticmethod
    def _success_result(requested_url: str, response) -> FetchResult:
        body = response.read().decode("utf-8", errors="replace")
        status_code = getattr(response, "status", 200)
        structured_log(
            logger,
            "debug",
            "scholar_source.fetch_succeeded",
            requested_url=requested_url,
            status_code=status_code,
        )
        return FetchResult(
            requested_url=requested_url,
            status_code=status_code,
            final_url=response.geturl(),
            body=body,
            error=None,
        )

    def _fetch_sync(self, requested_url: str) -> FetchResult:
        request = self._build_request(requested_url)

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return self._success_result(requested_url, response)
        except HTTPError as exc:
            return self._http_error_result(requested_url, exc)
        except URLError as exc:
            return self._network_error_result(requested_url, exc)


def _build_profile_url(*, scholar_id: str, cstart: int, pagesize: int) -> str:
    query: dict[str, int | str] = {"hl": "en", "user": scholar_id}
    if cstart > 0:
        query["cstart"] = int(cstart)
    if pagesize > 0:
        query["pagesize"] = int(pagesize)
    return f"{SCHOLAR_PROFILE_URL}?{urlencode(query)}"


def _build_author_search_url(*, query: str, start: int) -> str:
    params: dict[str, int | str] = {
        "hl": "en",
        "view_op": "search_authors",
        "mauthors": query,
    }
    if start > 0:
        params["astart"] = int(start)
    return f"{SCHOLAR_PROFILE_URL}?{urlencode(params)}"

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
        rotate_user_agents: bool | None = None,
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
        self._rotate_user_agents = (
            bool(settings.scholar_http_rotate_user_agent) if rotate_user_agents is None else bool(rotate_user_agents)
        )
        configured_user_agent = settings.scholar_http_user_agent.strip()
        self._configured_user_agent = configured_user_agent or None
        self._accept_language = settings.scholar_http_accept_language.strip() or "en-US,en;q=0.9"
        self._cookie_header = settings.scholar_http_cookie.strip() or None
        self._stable_user_agent = self._resolve_initial_user_agent()

    def _resolve_initial_user_agent(self) -> str:
        if self._configured_user_agent is not None:
            return self._configured_user_agent
        return random.choice(self._user_agents)

    def _resolve_user_agent_for_request(self) -> str:
        if self._configured_user_agent is not None:
            return self._configured_user_agent
        if self._rotate_user_agents:
            return random.choice(self._user_agents)
        return self._stable_user_agent

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self._resolve_user_agent_for_request(),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": self._accept_language,
        }
        if self._cookie_header is not None:
            headers["Cookie"] = self._cookie_header
        return headers

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
        return Request(requested_url, headers=self._request_headers())

    @staticmethod
    def _http_error_reason(*, status_code: int, final_url: str, body: str) -> str:
        lowered_url = final_url.lower()
        lowered_body = body.lower()
        if "sorry/index" in lowered_url or "sorry/index" in lowered_body:
            return "blocked_google_sorry_challenge"
        if "our systems have detected" in lowered_body or "unusual traffic" in lowered_body:
            return "blocked_unusual_traffic_detected"
        if "automated queries" in lowered_body:
            return "blocked_automated_queries_detected"
        if status_code == 429:
            return "blocked_http_429_rate_limited"
        return f"http_error_status_{status_code}"

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
        final_url = exc.geturl()
        body = LiveScholarSource._http_error_body(exc)
        block_reason = LiveScholarSource._http_error_reason(
            status_code=exc.code,
            final_url=final_url,
            body=body,
        )
        structured_log(
            logger,
            "warning",
            "scholar_source.fetch_http_error",
            requested_url=requested_url,
            status_code=exc.code,
            final_url=final_url,
            block_reason=block_reason,
        )
        return FetchResult(
            requested_url=requested_url,
            status_code=exc.code,
            final_url=final_url,
            body=body,
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

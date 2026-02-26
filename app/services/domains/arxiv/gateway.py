from __future__ import annotations

import logging
import re
import unicodedata
from typing import TYPE_CHECKING, Protocol

from app.logging_utils import structured_log
from app.services.domains.arxiv.client import ArxivClient
from app.services.domains.arxiv.errors import ArxivRateLimitError
from app.services.domains.arxiv.types import ArxivFeed
from app.settings import settings

if TYPE_CHECKING:
    from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem

logger = logging.getLogger(__name__)

_default_gateway: ArxivGateway | None = None
_MOJIBAKE_HINT_RE = re.compile(r"[ÃÂâ]")
_NON_ALNUM_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


class ArxivGateway(Protocol):
    async def discover_arxiv_id_for_publication(
        self,
        *,
        item: PublicationListItem | UnreadPublicationItem,
        request_email: str | None = None,
        timeout_seconds: float | None = None,
        max_results: int | None = None,
    ) -> str | None: ...


def build_arxiv_query(title: str, author_surname: str | None) -> str | None:
    parts: list[str] = []
    if title:
        clean_title = _normalize_query_title(title)
        if clean_title:
            parts.append(f'ti:"{clean_title}"')
    if author_surname:
        clean_author = _normalize_query_title(author_surname)
        if clean_author:
            parts.append(f'au:"{clean_author}"')
    if not parts:
        return None
    return " AND ".join(parts)


def _normalize_query_title(value: str) -> str:
    repaired = _repair_mojibake(value.strip())
    normalized = unicodedata.normalize("NFKC", repaired)
    stripped = _NON_ALNUM_RE.sub(" ", _MOJIBAKE_HINT_RE.sub(" ", normalized))
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _repair_mojibake(value: str) -> str:
    if not value or not _MOJIBAKE_HINT_RE.search(value):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if _mojibake_score(repaired) < _mojibake_score(value) else value


def _mojibake_score(value: str) -> int:
    return len(_MOJIBAKE_HINT_RE.findall(value))


def get_arxiv_gateway() -> ArxivGateway:
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = HttpArxivGateway()
    return _default_gateway


def set_arxiv_gateway(gateway: ArxivGateway | None) -> ArxivGateway | None:
    global _default_gateway
    previous = _default_gateway
    _default_gateway = gateway
    return previous


class HttpArxivGateway:
    def __init__(self, *, client: ArxivClient | None = None) -> None:
        self._client = client or ArxivClient()

    async def discover_arxiv_id_for_publication(
        self,
        *,
        item: PublicationListItem | UnreadPublicationItem,
        request_email: str | None = None,
        timeout_seconds: float | None = None,
        max_results: int | None = None,
    ) -> str | None:
        if not settings.arxiv_enabled:
            return None
        query = _query_for_item(item)
        if query is None:
            return None

        try:
            result = await self._client.search(
                query=query,
                start=0,
                request_email=request_email,
                timeout_seconds=timeout_seconds,
                max_results=max_results,
            )
            return _first_discovered_id(result)
        except ArxivRateLimitError:
            raise
        except Exception as exc:
            structured_log(logger, "debug", "arxiv.query_failed", error=str(exc))
            return None


def _query_for_item(item: PublicationListItem | UnreadPublicationItem) -> str | None:
    title = (item.title or "").strip()
    if not title:
        return None
    author_surname = _author_surname(item.scholar_label)
    return build_arxiv_query(title, author_surname)


def _author_surname(scholar_label: str | None) -> str | None:
    if not scholar_label:
        return None
    tokens = [token for token in scholar_label.strip().split() if token]
    if not tokens:
        return None
    return tokens[-1].lower()


def _first_discovered_id(result: ArxivFeed) -> str | None:
    for entry in result.entries:
        if entry.arxiv_id:
            structured_log(logger, "debug", "arxiv.id_discovered", arxiv_id=entry.arxiv_id)
            return entry.arxiv_id
    return None

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

import httpx

from app.services.domains.publication_identifiers.normalize import normalize_arxiv_id
from app.settings import settings

if TYPE_CHECKING:
    from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem

logger = logging.getLogger(__name__)

# arXiv API terms: max 1 request per 3 seconds, single connection at a time.
_ARXIV_LOCK = asyncio.Lock()
_ARXIV_MIN_INTERVAL_SECONDS = 4.0
# Global cooldown: when arXiv returns 429, all batches back off for this long.
_ARXIV_RATE_LIMIT_COOLDOWN_SECONDS = 60.0
_arxiv_rate_limited_until: float = 0.0  # asyncio monotonic time


class ArxivRateLimitError(Exception):
    """arXiv returned 429 — stop the batch to avoid hammering."""
    pass


def _build_arxiv_query(title: str, author_surname: str | None) -> str | None:
    parts = []
    if title:
        clean_title = title.replace('"', '').replace("'", "")
        parts.append(f'ti:"{clean_title}"')
    if author_surname:
        parts.append(f'au:"{author_surname}"')
    if not parts:
        return None
    return " AND ".join(parts)


async def discover_arxiv_id_for_publication(
    *,
    item: PublicationListItem | UnreadPublicationItem,
    request_email: str | None = None,
    timeout_seconds: float = 3.0,
) -> str | None:
    title = (item.title or "").strip()
    if not title:
        return None

    author_surname = None
    if item.scholar_label:
        tokens = [t for t in item.scholar_label.strip().split() if t]
        if tokens:
            author_surname = tokens[-1].lower()

    query = _build_arxiv_query(title, author_surname)
    if not query:
        return None

    url = "https://export.arxiv.org/api/query"
    params = {"search_query": query, "start": 0, "max_results": 3}
    headers = {
        "User-Agent": (
            f"scholar-scraper/1.0 "
            f"(mailto:{request_email or settings.crossref_api_mailto or 'unknown@example.com'})"
        )
    }

    try:
        async with _ARXIV_LOCK:
            global _arxiv_rate_limited_until
            now = asyncio.get_running_loop().time()
            if now < _arxiv_rate_limited_until:
                remaining = _arxiv_rate_limited_until - now
                raise ArxivRateLimitError(f"arXiv global cooldown active ({remaining:.0f}s remaining)")

            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
                response = await client.get(url, params=params)

            if response.status_code == 429:
                _arxiv_rate_limited_until = asyncio.get_running_loop().time() + _ARXIV_RATE_LIMIT_COOLDOWN_SECONDS
                raise ArxivRateLimitError("arXiv rate limit hit (429) — stopping batch")

            await asyncio.sleep(_ARXIV_MIN_INTERVAL_SECONDS)

        response.raise_for_status()

        root = ET.fromstring(response.text)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", namespace):
            id_elem = entry.find("atom:id", namespace)
            if id_elem is not None and id_elem.text:
                candidate = str(id_elem.text)
                if "/abs/" in candidate:
                    candidate = candidate.split("/abs/")[-1]
                normalized = normalize_arxiv_id(candidate)
                if normalized:
                    logger.debug("arxiv.id_discovered", extra={"event": "arxiv.id_discovered", "arxiv_id": normalized})
                    return normalized

    except ArxivRateLimitError:
        raise  # propagate so the batch loop can stop
    except Exception as exc:
        logger.debug(f"Failed to query arXiv API: {exc}")

    return None

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


def _build_arxiv_query(title: str, author_surname: str | None) -> str | None:
    parts = []
    if title:
        # arXiv api allows strict title searching using ti:
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
    params = {
        "search_query": query,
        "start": 0,
        "max_results": 3,
    }

    headers = {"User-Agent": f"scholar-scraper/1.0 (mailto:{request_email or settings.crossref_api_mailto or 'unknown@example.com'})"}
    
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            
        root = ET.fromstring(response.text)
        namespace = {'atom': 'http://www.w3.org/2005/Atom'}
        
        for entry in root.findall('atom:entry', namespace):
            id_elem = entry.find('atom:id', namespace)
            if id_elem is not None and id_elem.text:
                candidate = str(id_elem.text)
                if '/abs/' in candidate:
                    candidate = candidate.split('/abs/')[-1]
                normalized = normalize_arxiv_id(candidate)
                if normalized:
                    logger.debug("arxiv.id_discovered", extra={"event": "arxiv.id_discovered", "arxiv_id": normalized})
                    return normalized
                    
    except Exception as exc:
        logger.debug(f"Failed to query arXiv API: {exc}")
        
    return None

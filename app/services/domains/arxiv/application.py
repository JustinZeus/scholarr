from __future__ import annotations

from typing import TYPE_CHECKING
from app.services.domains.arxiv.gateway import (
    build_arxiv_query,
    get_arxiv_gateway,
)
from app.services.domains.arxiv.errors import ArxivRateLimitError

if TYPE_CHECKING:
    from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem


def _build_arxiv_query(title: str, author_surname: str | None) -> str | None:
    return build_arxiv_query(title, author_surname)


async def discover_arxiv_id_for_publication(
    *,
    item: PublicationListItem | UnreadPublicationItem,
    request_email: str | None = None,
    timeout_seconds: float | None = None,
) -> str | None:
    gateway = get_arxiv_gateway()
    return await gateway.discover_arxiv_id_for_publication(
        item=item,
        request_email=request_email,
        timeout_seconds=timeout_seconds,
    )

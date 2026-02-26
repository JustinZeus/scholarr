from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ArxivSortBy = Literal["relevance", "lastUpdatedDate", "submittedDate"]
ArxivSortOrder = Literal["ascending", "descending"]


@dataclass(frozen=True)
class ArxivOpenSearchMeta:
    total_results: int = 0
    start_index: int = 0
    items_per_page: int = 0


@dataclass(frozen=True)
class ArxivEntry:
    entry_id_url: str
    arxiv_id: str | None
    title: str
    summary: str
    published: str | None
    updated: str | None
    authors: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    primary_category: str | None = None


@dataclass(frozen=True)
class ArxivFeed:
    entries: list[ArxivEntry] = field(default_factory=list)
    opensearch: ArxivOpenSearchMeta = field(default_factory=ArxivOpenSearchMeta)

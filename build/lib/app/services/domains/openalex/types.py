from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class OpenAlexAuthor:
    openalex_id: str | None
    display_name: str | None


@dataclass(frozen=True)
class OpenAlexWork:
    openalex_id: str
    doi: str | None
    pmid: str | None
    pmcid: str | None
    title: str | None
    publication_year: int | None
    cited_by_count: int
    is_oa: bool
    oa_url: str | None
    authors: list[OpenAlexAuthor] = field(default_factory=list)
    raw_data: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api_dict(cls, data: Mapping[str, Any]) -> OpenAlexWork:
        ids = data.get("ids") or {}
        
        # Extract DOI without the https://doi.org/ prefix
        doi = ids.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[16:]
            
        # Extract PMID without the url prefix
        pmid = ids.get("pmid")
        if pmid and pmid.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
            pmid = pmid[32:]
            
        # Extract PMCID without the url prefix
        pmcid = ids.get("pmcid")
        if pmcid and pmcid.startswith("https://www.ncbi.nlm.nih.gov/pmc/articles/"):
            pmcid = pmcid[42:]

        open_access = data.get("open_access") or {}
        
        authors = []
        for authorship in data.get("authorships") or []:
            author_data = authorship.get("author") or {}
            authors.append(
                OpenAlexAuthor(
                    openalex_id=author_data.get("id"),
                    display_name=author_data.get("display_name"),
                )
            )

        return cls(
            openalex_id=data.get("id", ""),
            doi=doi,
            pmid=pmid,
            pmcid=pmcid,
            title=data.get("title"),
            publication_year=data.get("publication_year"),
            cited_by_count=data.get("cited_by_count", 0),
            is_oa=bool(open_access.get("is_oa")),
            oa_url=open_access.get("oa_url"),
            authors=authors,
            raw_data=dict(data),
        )

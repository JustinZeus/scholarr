from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from app.services.domains.arxiv.application import ArxivRateLimitError
from app.services.domains.arxiv.guards import arxiv_skip_reason_for_item
from app.services.domains.openalex.client import OpenAlexBudgetExhaustedError
from app.services.domains.publications.types import PublicationListItem
from app.services.domains.unpaywall.application import OaResolutionOutcome, resolve_publication_oa_outcomes
from app.logging_utils import structured_log
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineOutcome:
    outcome: OaResolutionOutcome | None
    scholar_candidates: Any | None  # Kept for backward compatibility with calling signatures
    arxiv_rate_limited: bool = False


async def resolve_publication_pdf_outcome_for_row(
    *,
    row: PublicationListItem,
    request_email: str | None,
    openalex_api_key: str | None = None,
    allow_arxiv_lookup: bool = True,
) -> PipelineOutcome:
    # 1. OpenAlex OA — raises OpenAlexBudgetExhaustedError if budget is gone
    openalex_outcome = await _openalex_outcome(row, request_email=request_email, openalex_api_key=openalex_api_key)
    if openalex_outcome and openalex_outcome.pdf_url:
        return PipelineOutcome(openalex_outcome, None)

    # 2. arXiv
    arxiv_rate_limited = False
    try:
        arxiv_outcome = await _arxiv_outcome(
            row,
            request_email=request_email,
            allow_lookup=allow_arxiv_lookup,
        )
    except ArxivRateLimitError:
        arxiv_rate_limited = True
        arxiv_outcome = None
        structured_log(logger, "warning", "publications.pdf_resolution.arxiv_rate_limited", publication_id=int(row.publication_id))
    if arxiv_outcome and arxiv_outcome.pdf_url:
        return PipelineOutcome(arxiv_outcome, None, arxiv_rate_limited=arxiv_rate_limited)

    # 3. Unpaywall (which falls back to Crossref)
    oa_outcome = await _oa_outcome(row=row, request_email=request_email)
    return PipelineOutcome(oa_outcome, None, arxiv_rate_limited=arxiv_rate_limited)


async def _openalex_outcome(
    row: PublicationListItem,
    request_email: str | None,
    openalex_api_key: str | None = None,
) -> OaResolutionOutcome | None:
    from app.services.domains.openalex.client import OpenAlexClient
    from app.services.domains.openalex.matching import find_best_match

    if not row.title:
        return None

    import re
    safe_title = re.sub(r"[^\w\s]", " ", row.title)
    safe_title = " ".join(safe_title.split())
    if not safe_title:
        return None

    api_key = openalex_api_key or settings.openalex_api_key
    client = OpenAlexClient(api_key=api_key, mailto=request_email or settings.crossref_api_mailto)
    try:
        openalex_works = await client.get_works_by_filter({"title.search": safe_title}, limit=5)
        match = find_best_match(
            target_title=row.title,
            target_year=row.year,
            target_authors=row.scholar_label,
            candidates=openalex_works,
        )
        if match and match.oa_url:
            return OaResolutionOutcome(
                publication_id=row.publication_id,
                doi=match.doi,
                pdf_url=match.oa_url,
                failure_reason=None,
                source="openalex",
                used_crossref=False,
            )
    except OpenAlexBudgetExhaustedError:
        # Re-raise so the caller's batch loop can stop hitting the API.
        raise
    except Exception as exc:
        structured_log(logger, "warning", "publications.pdf_resolution.openalex_failed", error=str(exc))
    return None


async def _arxiv_outcome(
    row: PublicationListItem,
    *,
    request_email: str | None,
    allow_lookup: bool = True,
) -> OaResolutionOutcome | None:
    from app.services.domains.arxiv.application import discover_arxiv_id_for_publication

    if not allow_lookup:
        structured_log(logger, "info", "publications.pdf_resolution.arxiv_skipped", publication_id=int(row.publication_id), skip_reason="batch_arxiv_cooldown_active")
        return None

    skip_reason = arxiv_skip_reason_for_item(item=row)
    if skip_reason is not None:
        structured_log(logger, "info", "publications.pdf_resolution.arxiv_skipped", publication_id=int(row.publication_id), skip_reason=skip_reason)
        return None

    try:
        arxiv_id = await discover_arxiv_id_for_publication(item=row, request_email=request_email)
        if arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            return OaResolutionOutcome(
                publication_id=row.publication_id,
                doi=None,
                pdf_url=pdf_url,
                failure_reason=None,
                source="arxiv",
                used_crossref=False,
            )
    except ArxivRateLimitError:
        raise  # propagate so orchestration can switch to non-arXiv fallback
    except Exception as exc:
        structured_log(logger, "warning", "publications.pdf_resolution.arxiv_failed", error=str(exc))
    return None



async def _oa_outcome(
    *,
    row: PublicationListItem,
    request_email: str | None,
) -> OaResolutionOutcome | None:
    outcomes = await resolve_publication_oa_outcomes([row], request_email=request_email)
    return outcomes.get(row.publication_id)

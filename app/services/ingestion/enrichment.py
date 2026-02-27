from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    Publication,
    RunStatus,
    ScholarProfile,
    ScholarPublication,
)
from app.logging_utils import structured_log
from app.services.arxiv.errors import ArxivRateLimitError
from app.services.publication_identifiers import application as identifier_service
from app.services.runs.events import run_events
from app.services.scholar.parser import PublicationCandidate
from app.settings import settings

logger = logging.getLogger(__name__)


class EnrichmentRunner:
    """Post-run OpenAlex enrichment logic.

    Receives service dependencies at construction so it can be tested
    independently of ``ScholarIngestionService``.
    """

    async def run_is_canceled(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
    ) -> bool:
        check_result = await db_session.execute(select(CrawlRun.status).where(CrawlRun.id == run_id))
        status = check_result.scalar_one_or_none()
        if status is None:
            raise RuntimeError(f"Missing crawl_run for run_id={run_id}.")
        return status == RunStatus.CANCELED

    async def enrich_pending_publications(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
        openalex_api_key: str | None = None,
    ) -> None:
        """Enrich unenriched publications with OpenAlex data.

        Stops immediately on budget exhaustion (429 with $0 remaining).
        Sleeps 60s and continues on transient rate limits.
        """
        from app.services.openalex.client import (
            OpenAlexBudgetExhaustedError,
            OpenAlexClient,
            OpenAlexRateLimitError,
        )
        from app.services.openalex.matching import find_best_match

        run_result = await db_session.execute(select(CrawlRun.user_id).where(CrawlRun.id == run_id))
        user_id = run_result.scalar_one()

        now = datetime.now(UTC)
        cooldown_threshold = now - timedelta(days=7)

        stmt = (
            select(Publication)
            .join(ScholarPublication)
            .join(ScholarProfile, ScholarPublication.scholar_profile_id == ScholarProfile.id)
            .where(
                ScholarProfile.user_id == user_id,
                Publication.openalex_enriched.is_(False),
                or_(
                    Publication.openalex_last_attempt_at.is_(None),
                    Publication.openalex_last_attempt_at < cooldown_threshold,
                ),
            )
            .distinct()
        )
        result = await db_session.execute(stmt)
        publications = list(result.scalars().all())

        if not publications:
            return

        resolved_key = openalex_api_key or settings.openalex_api_key
        client = OpenAlexClient(api_key=resolved_key, mailto=settings.crossref_api_mailto)
        batch_size = 25
        arxiv_lookup_allowed = True

        for i in range(0, len(publications), batch_size):
            if await self.run_is_canceled(db_session, run_id=run_id):
                logger.info("ingestion.enrichment_aborted", extra={"run_id": run_id})
                return
            batch = publications[i : i + batch_size]
            titles = [
                " ".join(re.sub(r"[^\w\s]", " ", p.title_raw).split())
                for p in batch
                if p.title_raw and p.title_raw.strip()
            ]

            if not titles:
                continue

            try:
                openalex_works = await client.get_works_by_filter(
                    {"title.search": "|".join(titles)}, limit=batch_size * 3
                )
            except OpenAlexBudgetExhaustedError:
                structured_log(
                    logger,
                    "warning",
                    "ingestion.openalex_budget_exhausted",
                    run_id=run_id,
                )
                break
            except OpenAlexRateLimitError:
                structured_log(
                    logger,
                    "warning",
                    "ingestion.openalex_rate_limited",
                    run_id=run_id,
                )
                await asyncio.sleep(60)
                continue
            except Exception as e:
                structured_log(
                    logger,
                    "warning",
                    "ingestion.openalex_enrichment_failed",
                    error=str(e),
                    run_id=run_id,
                )
                continue

            for p in batch:
                if await self.run_is_canceled(db_session, run_id=run_id):
                    logger.info("ingestion.enrichment_aborted", extra={"run_id": run_id})
                    return

                p.openalex_last_attempt_at = now
                arxiv_lookup_allowed = await self._discover_identifiers_for_enrichment(
                    db_session,
                    publication=p,
                    run_id=run_id,
                    allow_arxiv_lookup=arxiv_lookup_allowed,
                )

                match = find_best_match(
                    target_title=p.title_raw,
                    target_year=p.year,
                    target_authors=p.author_text or "",
                    candidates=openalex_works,
                )
                if match:
                    p.year = match.publication_year or p.year
                    p.citation_count = match.cited_by_count or p.citation_count
                    p.pdf_url = match.oa_url or p.pdf_url
                    p.openalex_enriched = True

        await db_session.flush()

        from app.services.publications.dedup import sweep_identifier_duplicates

        merge_count = await sweep_identifier_duplicates(db_session)
        if merge_count:
            structured_log(
                logger,
                "info",
                "ingestion.identifier_dedup_sweep",
                merged_count=merge_count,
                run_id=run_id,
            )

    async def _discover_identifiers_for_enrichment(
        self,
        db_session: AsyncSession,
        *,
        publication: Publication,
        run_id: int,
        allow_arxiv_lookup: bool,
    ) -> bool:
        if not allow_arxiv_lookup:
            await identifier_service.sync_identifiers_for_publication_fields(
                db_session,
                publication=publication,
            )
            await self._publish_identifier_update_event(
                db_session,
                run_id=run_id,
                publication_id=int(publication.id),
            )
            return False
        try:
            await identifier_service.discover_and_sync_identifiers_for_publication(
                db_session,
                publication=publication,
                scholar_label=publication.author_text or "",
            )
            await self._publish_identifier_update_event(
                db_session,
                run_id=run_id,
                publication_id=int(publication.id),
            )
            return True
        except ArxivRateLimitError:
            structured_log(
                logger,
                "warning",
                "ingestion.arxiv_rate_limited",
                run_id=run_id,
                publication_id=int(publication.id),
                detail="arXiv temporarily disabled for remaining enrichment pass",
            )
            await identifier_service.sync_identifiers_for_publication_fields(
                db_session,
                publication=publication,
            )
            await self._publish_identifier_update_event(
                db_session,
                run_id=run_id,
                publication_id=int(publication.id),
            )
            return False

    async def _publish_identifier_update_event(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
        publication_id: int,
    ) -> None:
        display = await identifier_service.display_identifier_for_publication_id(
            db_session,
            publication_id=publication_id,
        )
        if display is None:
            return
        await run_events.publish(
            run_id=run_id,
            event_type="identifier_updated",
            data={
                "publication_id": int(publication_id),
                "display_identifier": {
                    "kind": display.kind,
                    "value": display.value,
                    "label": display.label,
                    "url": display.url,
                    "confidence_score": float(display.confidence_score),
                },
            },
        )

    async def enrich_publications_with_openalex(
        self,
        scholar: ScholarProfile,
        publications: list[PublicationCandidate],
    ) -> list[PublicationCandidate]:
        if not publications:
            return publications

        from app.services.openalex.client import OpenAlexClient
        from app.services.openalex.matching import find_best_match

        client = OpenAlexClient(api_key=settings.openalex_api_key, mailto=settings.crossref_api_mailto)

        batch_size = 25
        enriched: list[PublicationCandidate] = []

        for i in range(0, len(publications), batch_size):
            batch = publications[i : i + batch_size]

            titles = []
            for p in batch:
                if not p.title:
                    continue
                safe_title = re.sub(r"[^\w\s]", " ", p.title)
                safe_title = " ".join(safe_title.split())
                if safe_title:
                    titles.append(safe_title)

            if not titles:
                enriched.extend(batch)
                continue

            query = "|".join(t for t in titles)
            try:
                openalex_works = await client.get_works_by_filter({"title.search": query}, limit=batch_size * 3)
            except Exception as e:
                logger.warning(
                    "ingestion.openalex_enrichment_failed",
                    extra={"error": str(e), "batch_size": len(batch), "scholar_id": scholar.id},
                )
                openalex_works = []

            for p in batch:
                match = find_best_match(
                    target_title=p.title,
                    target_year=p.year,
                    target_authors=p.authors_text or (scholar.display_name or scholar.scholar_id),
                    candidates=openalex_works,
                )
                if match:
                    new_p = PublicationCandidate(
                        title=p.title,
                        title_url=p.title_url,
                        cluster_id=p.cluster_id,
                        year=match.publication_year or p.year,
                        citation_count=match.cited_by_count,
                        authors_text=p.authors_text,
                        venue_text=p.venue_text,
                        pdf_url=match.oa_url or p.pdf_url,
                    )
                    enriched.append(new_p)
                else:
                    enriched.append(p)
        return enriched

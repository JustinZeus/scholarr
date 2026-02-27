from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    Publication,
    RunStatus,
    RunTriggerType,
    ScholarProfile,
    ScholarPublication,
)
from app.logging_utils import structured_log
from app.services.arxiv.errors import ArxivRateLimitError
from app.services.ingestion import queue as queue_service
from app.services.ingestion import safety as run_safety_service
from app.services.ingestion.constants import (
    FAILED_STATES,
    FAILURE_BUCKET_BLOCKED,
    FAILURE_BUCKET_INGESTION,
    FAILURE_BUCKET_LAYOUT,
    FAILURE_BUCKET_NETWORK,
    FAILURE_BUCKET_OTHER,
    RESUMABLE_PARTIAL_REASON_PREFIXES,
    RESUMABLE_PARTIAL_REASONS,
    RUN_LOCK_NAMESPACE,
)
from app.services.ingestion.fingerprints import (
    _build_body_excerpt,
)
from app.services.ingestion.pagination import PaginationEngine
from app.services.ingestion.publication_upsert import upsert_profile_publications
from app.services.ingestion.types import (
    PagedParseResult,
    RunAlertSummary,
    RunAlreadyInProgressError,
    RunBlockedBySafetyPolicyError,
    RunExecutionSummary,
    RunFailureSummary,
    RunProgress,
    ScholarProcessingOutcome,
)
from app.services.publication_identifiers import application as identifier_service
from app.services.runs.events import run_events
from app.services.scholar.parser import (
    ParsedProfilePage,
    ParseState,
    PublicationCandidate,
)
from app.services.scholar.source import FetchResult, ScholarSource
from app.services.settings import application as user_settings_service
from app.settings import settings

logger = logging.getLogger(__name__)
ACTIVE_RUN_INDEX_NAME = "uq_crawl_runs_user_active"


def _is_active_run_integrity_error(exc: IntegrityError) -> bool:
    original_error = getattr(exc, "orig", None)
    if ACTIVE_RUN_INDEX_NAME in str(exc):
        return True
    if original_error is None:
        return False
    if ACTIVE_RUN_INDEX_NAME in str(original_error):
        return True
    diagnostics = getattr(original_error, "diag", None)
    if diagnostics is None:
        return False
    return getattr(diagnostics, "constraint_name", None) == ACTIVE_RUN_INDEX_NAME


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _classify_failure_bucket(*, state: str, state_reason: str) -> str:
    reason = state_reason.strip().lower()
    normalized_state = state.strip().lower()

    if normalized_state == ParseState.BLOCKED_OR_CAPTCHA.value or reason.startswith("blocked_"):
        return FAILURE_BUCKET_BLOCKED
    if normalized_state == ParseState.NETWORK_ERROR.value or reason.startswith("network_"):
        return FAILURE_BUCKET_NETWORK
    if normalized_state == ParseState.LAYOUT_CHANGED.value:
        return FAILURE_BUCKET_LAYOUT
    if normalized_state == "ingestion_error":
        return FAILURE_BUCKET_INGESTION
    return FAILURE_BUCKET_OTHER


_background_tasks: set[asyncio.Task[Any]] = set()


class ScholarIngestionService:
    def __init__(self, *, source: ScholarSource) -> None:
        self._source = source
        self._pagination = PaginationEngine(source=source)

    @staticmethod
    def _effective_request_delay_seconds(value: int) -> int:
        policy_minimum = user_settings_service.resolve_request_delay_minimum(
            settings.ingestion_min_request_delay_seconds
        )
        return max(policy_minimum, _int_or_default(value, policy_minimum))

    async def _load_user_settings_for_run(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
    ):
        user_settings = await user_settings_service.get_or_create_settings(
            db_session,
            user_id=user_id,
        )
        await self._enforce_safety_gate(
            db_session,
            user_settings=user_settings,
            user_id=user_id,
            trigger_type=trigger_type,
        )
        return user_settings

    async def _enforce_safety_gate(
        self,
        db_session: AsyncSession,
        *,
        user_settings,
        user_id: int,
        trigger_type: RunTriggerType,
    ) -> None:
        now_utc = datetime.now(UTC)
        previous = run_safety_service.get_safety_event_context(user_settings, now_utc=now_utc)
        if run_safety_service.clear_expired_cooldown(user_settings, now_utc=now_utc):
            await db_session.commit()
            await db_session.refresh(user_settings)
            structured_log(
                logger,
                "info",
                "ingestion.cooldown_cleared",
                user_id=user_id,
                reason=previous.get("cooldown_reason"),
                cooldown_until=previous.get("cooldown_until"),
            )
            now_utc = datetime.now(UTC)
        if run_safety_service.is_cooldown_active(user_settings, now_utc=now_utc):
            await self._raise_safety_blocked_start(
                db_session,
                user_settings=user_settings,
                user_id=user_id,
                trigger_type=trigger_type,
                now_utc=now_utc,
            )

    async def _raise_safety_blocked_start(
        self,
        db_session: AsyncSession,
        *,
        user_settings,
        user_id: int,
        trigger_type: RunTriggerType,
        now_utc: datetime,
    ) -> None:
        safety_state = run_safety_service.register_cooldown_blocked_start(
            user_settings,
            now_utc=now_utc,
        )
        await db_session.commit()
        structured_log(
            logger,
            "warning",
            "ingestion.safety_policy_blocked_run_start",
            user_id=user_id,
            trigger_type=trigger_type.value,
            reason=safety_state.get("cooldown_reason"),
            cooldown_until=safety_state.get("cooldown_until"),
            cooldown_remaining_seconds=safety_state.get("cooldown_remaining_seconds"),
            blocked_start_count=((safety_state.get("counters") or {}).get("blocked_start_count")),
        )
        raise RunBlockedBySafetyPolicyError(
            code="scrape_cooldown_active",
            message="Scrape safety cooldown is active; run start is temporarily blocked.",
            safety_state=safety_state,
        )

    @staticmethod
    def _normalize_run_targets(
        *,
        scholar_profile_ids: set[int] | None,
        start_cstart_by_scholar_id: dict[int, int] | None,
    ) -> tuple[set[int] | None, dict[int, int]]:
        filtered_scholar_ids = (
            {int(value) for value in scholar_profile_ids} if scholar_profile_ids is not None else None
        )
        start_cstart_map = {int(key): max(0, int(value)) for key, value in (start_cstart_by_scholar_id or {}).items()}
        return filtered_scholar_ids, start_cstart_map

    async def _load_target_scholars(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        filtered_scholar_ids: set[int] | None,
    ) -> list[ScholarProfile]:
        scholars_stmt = (
            select(ScholarProfile)
            .where(ScholarProfile.user_id == user_id, ScholarProfile.is_enabled.is_(True))
            .order_by(ScholarProfile.created_at.asc(), ScholarProfile.id.asc())
        )
        if filtered_scholar_ids is not None:
            scholars_stmt = scholars_stmt.where(ScholarProfile.id.in_(filtered_scholar_ids))
        scholars_result = await db_session.execute(scholars_stmt)
        scholars = list(scholars_result.scalars().all())
        await self._clear_missing_filtered_jobs(
            db_session,
            user_id=user_id,
            filtered_scholar_ids=filtered_scholar_ids,
            scholars=scholars,
        )
        return scholars

    async def _clear_missing_filtered_jobs(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        filtered_scholar_ids: set[int] | None,
        scholars: list[ScholarProfile],
    ) -> None:
        if filtered_scholar_ids is None:
            return
        found_ids = {int(scholar.id) for scholar in scholars}
        missing_ids = filtered_scholar_ids - found_ids
        for scholar_profile_id in missing_ids:
            await queue_service.clear_job_for_scholar(
                db_session,
                user_id=user_id,
                scholar_profile_id=scholar_profile_id,
            )

    @staticmethod
    def _create_running_run(
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholar_count: int,
        idempotency_key: str | None,
    ) -> CrawlRun:
        return CrawlRun(
            user_id=user_id,
            trigger_type=trigger_type,
            status=RunStatus.RUNNING,
            scholar_count=scholar_count,
            new_pub_count=0,
            idempotency_key=idempotency_key,
            error_log={},
        )

    @staticmethod
    async def _wait_between_scholars(*, index: int, request_delay_seconds: int) -> None:
        if index <= 0 or request_delay_seconds <= 0:
            return
        await asyncio.sleep(float(request_delay_seconds))

    @staticmethod
    def _assert_valid_paged_parse_result(
        *,
        scholar_id: str,
        paged_parse_result: PagedParseResult,
    ) -> None:
        parsed_page = paged_parse_result.parsed_page
        if parsed_page.state in {ParseState.OK, ParseState.NO_RESULTS} and any(
            code.startswith("layout_") for code in parsed_page.warnings
        ):
            raise RuntimeError(f"Layout warning marked as terminal for scholar_id={scholar_id}.")
        for publication in paged_parse_result.publications:
            if not publication.title.strip():
                raise RuntimeError(f"Malformed publication title for scholar_id={scholar_id}.")
            if publication.citation_count is not None and int(publication.citation_count) < 0:
                raise RuntimeError(f"Negative citation count for scholar_id={scholar_id}.")

    @staticmethod
    def _apply_first_page_profile_metadata(
        *,
        scholar: ScholarProfile,
        paged_parse_result: PagedParseResult,
        run_dt: datetime,
    ) -> None:
        first_page = paged_parse_result.first_page_parsed_page
        if first_page.profile_name and not (scholar.display_name or "").strip():
            scholar.display_name = first_page.profile_name
        if first_page.profile_image_url:
            scholar.profile_image_url = first_page.profile_image_url
        scholar.last_initial_page_checked_at = run_dt

    @staticmethod
    def _build_result_entry(
        *,
        scholar: ScholarProfile,
        start_cstart: int,
        paged_parse_result: PagedParseResult,
    ) -> dict[str, Any]:
        parsed_page = paged_parse_result.parsed_page
        return {
            "scholar_profile_id": scholar.id,
            "scholar_id": scholar.scholar_id,
            "state": parsed_page.state.value,
            "state_reason": parsed_page.state_reason,
            "outcome": "failed",
            "attempt_count": len(paged_parse_result.attempt_log),
            "publication_count": len(paged_parse_result.publications),
            "start_cstart": start_cstart,
            "articles_range": parsed_page.articles_range,
            "warnings": parsed_page.warnings,
            "has_show_more_button": parsed_page.has_show_more_button,
            "pages_fetched": paged_parse_result.pages_fetched,
            "pages_attempted": paged_parse_result.pages_attempted,
            "has_more_remaining": paged_parse_result.has_more_remaining,
            "pagination_truncated_reason": paged_parse_result.pagination_truncated_reason,
            "continuation_cstart": paged_parse_result.continuation_cstart,
            "skipped_no_change": paged_parse_result.skipped_no_change,
            "initial_page_fingerprint_sha256": paged_parse_result.first_page_fingerprint_sha256,
        }

    def _skipped_no_change_outcome(
        self,
        *,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        first_page = paged_parse_result.first_page_parsed_page
        scholar.last_run_status = RunStatus.SUCCESS
        scholar.last_run_dt = run_dt
        result_entry["state"] = first_page.state.value
        result_entry["state_reason"] = "no_change_initial_page_signature"
        result_entry["outcome"] = "success"
        result_entry["publication_count"] = 0
        result_entry["warnings"] = first_page.warnings
        result_entry["debug"] = {
            "state_reason": "no_change_initial_page_signature",
            "first_page_fingerprint_sha256": paged_parse_result.first_page_fingerprint_sha256,
            "attempt_log": paged_parse_result.attempt_log,
            "page_logs": paged_parse_result.page_logs,
        }
        return ScholarProcessingOutcome(
            result_entry=result_entry,
            succeeded_count_delta=1,
            failed_count_delta=0,
            partial_count_delta=0,
            discovered_publication_count=0,
        )

    async def _upsert_publications_outcome(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        parsed_page = paged_parse_result.parsed_page
        publications = paged_parse_result.publications
        had_page_failure = parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}
        has_partial_set = len(publications) > 0 and had_page_failure
        if (not had_page_failure) or has_partial_set:
            return await self._upsert_success_or_exception(
                db_session,
                run=run,
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
                has_partial_publication_set=has_partial_set,
            )
        return self._parse_failure_outcome(
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )

    async def _upsert_success_or_exception(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
        has_partial_publication_set: bool,
    ) -> ScholarProcessingOutcome:
        try:
            return await self._upsert_success(
                db_session,
                run=run,
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
                has_partial_publication_set=has_partial_publication_set,
            )
        except Exception as exc:
            return self._upsert_exception_outcome(
                run=run,
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
                exc=exc,
            )

    async def _upsert_success(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
        has_partial_publication_set: bool,
    ) -> ScholarProcessingOutcome:
        # We no longer aggregate and upsert the publications here.
        # Eager DB insertions have already saved and committed them inside `fetch_and_parse_all_pages` and `_paginate_loop`.
        discovered_count = paged_parse_result.discovered_publication_count
        is_partial = (
            paged_parse_result.has_more_remaining
            or paged_parse_result.pagination_truncated_reason is not None
            or has_partial_publication_set
        )
        scholar.last_run_status = RunStatus.PARTIAL_FAILURE if is_partial else RunStatus.SUCCESS
        scholar.last_run_dt = run_dt
        if not is_partial and paged_parse_result.first_page_fingerprint_sha256:
            scholar.last_initial_page_fingerprint_sha256 = paged_parse_result.first_page_fingerprint_sha256
        result_entry["outcome"] = "partial" if is_partial else "success"
        if is_partial:
            result_entry["debug"] = self._build_failure_debug_context(
                fetch_result=paged_parse_result.fetch_result,
                parsed_page=paged_parse_result.parsed_page,
                attempt_log=paged_parse_result.attempt_log,
                page_logs=paged_parse_result.page_logs,
            )
        return ScholarProcessingOutcome(
            result_entry=result_entry,
            succeeded_count_delta=1,
            failed_count_delta=0,
            partial_count_delta=1 if is_partial else 0,
            discovered_publication_count=discovered_count,
        )

    def _upsert_exception_outcome(
        self,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
        exc: Exception,
    ) -> ScholarProcessingOutcome:
        scholar.last_run_status = RunStatus.FAILED
        scholar.last_run_dt = run_dt
        result_entry["state"] = "ingestion_error"
        result_entry["state_reason"] = "publication_upsert_exception"
        result_entry["outcome"] = "failed"
        result_entry["error"] = str(exc)
        result_entry["debug"] = self._build_failure_debug_context(
            fetch_result=paged_parse_result.fetch_result,
            parsed_page=paged_parse_result.parsed_page,
            attempt_log=paged_parse_result.attempt_log,
            page_logs=paged_parse_result.page_logs,
            exception=exc,
        )
        logger.exception(
            "ingestion.scholar_failed",
            extra={
                "crawl_run_id": run.id,
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
            },
        )
        return ScholarProcessingOutcome(result_entry, 0, 1, 0, 0)

    def _parse_failure_outcome(
        self,
        *,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        scholar.last_run_status = RunStatus.FAILED
        scholar.last_run_dt = run_dt
        result_entry["debug"] = self._build_failure_debug_context(
            fetch_result=paged_parse_result.fetch_result,
            parsed_page=paged_parse_result.parsed_page,
            attempt_log=paged_parse_result.attempt_log,
            page_logs=paged_parse_result.page_logs,
        )
        structured_log(
            logger,
            "warning",
            "ingestion.scholar_parse_failed",
            scholar_profile_id=scholar.id,
            scholar_id=scholar.scholar_id,
            state=paged_parse_result.parsed_page.state.value,
            state_reason=paged_parse_result.parsed_page.state_reason,
            status_code=paged_parse_result.fetch_result.status_code,
        )
        return ScholarProcessingOutcome(result_entry, 0, 1, 0, 0)

    async def _sync_continuation_queue(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        scholar: ScholarProfile,
        run: CrawlRun,
        start_cstart: int,
        result_entry: dict[str, Any],
        paged_parse_result: PagedParseResult,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> None:
        queue_reason, queue_cstart = self._resolve_continuation_queue_target(
            outcome=str(result_entry.get("outcome", "")),
            state=str(result_entry.get("state", "")),
            pagination_truncated_reason=paged_parse_result.pagination_truncated_reason,
            continuation_cstart=paged_parse_result.continuation_cstart,
            fallback_cstart=start_cstart,
        )
        if auto_queue_continuations and queue_reason is not None:
            await queue_service.upsert_job(
                db_session,
                user_id=user_id,
                scholar_profile_id=scholar.id,
                resume_cstart=queue_cstart,
                reason=queue_reason,
                run_id=run.id,
                delay_seconds=queue_delay_seconds,
            )
            result_entry["continuation_enqueued"] = True
            result_entry["continuation_reason"] = queue_reason
            result_entry["continuation_cstart"] = queue_cstart
            return
        if await queue_service.clear_job_for_scholar(db_session, user_id=user_id, scholar_profile_id=scholar.id):
            result_entry["continuation_cleared"] = True

    async def _process_scholar(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        user_id: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        start_cstart: int,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> ScholarProcessingOutcome:
        try:
            return await self._process_scholar_inner(
                db_session,
                run=run,
                scholar=scholar,
                user_id=user_id,
                request_delay_seconds=request_delay_seconds,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                rate_limit_retries=rate_limit_retries,
                rate_limit_backoff_seconds=rate_limit_backoff_seconds,
                max_pages_per_scholar=max_pages_per_scholar,
                page_size=page_size,
                start_cstart=start_cstart,
                auto_queue_continuations=auto_queue_continuations,
                queue_delay_seconds=queue_delay_seconds,
            )
        except Exception as exc:
            return self._unexpected_scholar_exception_outcome(
                run=run,
                scholar=scholar,
                start_cstart=start_cstart,
                exc=exc,
            )

    async def _process_scholar_inner(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        user_id: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        start_cstart: int,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> ScholarProcessingOutcome:
        run_dt, paged_parse_result, result_entry = await self._fetch_and_prepare_scholar_result(
            db_session,
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=start_cstart,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        outcome = await self._resolve_scholar_outcome(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )
        await self._sync_continuation_queue(
            db_session,
            user_id=user_id,
            scholar=scholar,
            run=run,
            start_cstart=start_cstart,
            result_entry=outcome.result_entry,
            paged_parse_result=paged_parse_result,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
        )
        return outcome

    async def _fetch_and_prepare_scholar_result(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        user_id: int,
        start_cstart: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
    ) -> tuple[datetime, PagedParseResult, dict[str, Any]]:
        run_dt = datetime.now(UTC)
        paged_parse_result = await self._pagination.fetch_and_parse_all_pages(
            scholar=scholar,
            run=run,
            db_session=db_session,
            start_cstart=start_cstart,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages=max_pages_per_scholar,
            page_size=page_size,
            previous_initial_page_fingerprint_sha256=scholar.last_initial_page_fingerprint_sha256,
            upsert_publications_fn=upsert_profile_publications,
        )
        self._assert_valid_paged_parse_result(scholar_id=scholar.scholar_id, paged_parse_result=paged_parse_result)
        self._apply_first_page_profile_metadata(scholar=scholar, paged_parse_result=paged_parse_result, run_dt=run_dt)
        parsed_page = paged_parse_result.parsed_page
        structured_log(
            logger,
            "info",
            "ingestion.scholar_parsed",
            user_id=user_id,
            crawl_run_id=run.id,
            scholar_profile_id=scholar.id,
            scholar_id=scholar.scholar_id,
            state=parsed_page.state.value,
            publication_count=len(paged_parse_result.publications),
            has_show_more_button=parsed_page.has_show_more_button,
            pages_fetched=paged_parse_result.pages_fetched,
            pages_attempted=paged_parse_result.pages_attempted,
            has_more_remaining=paged_parse_result.has_more_remaining,
            pagination_truncated_reason=paged_parse_result.pagination_truncated_reason,
            warning_count=len(parsed_page.warnings),
            skipped_no_change=paged_parse_result.skipped_no_change,
        )
        result_entry = self._build_result_entry(
            scholar=scholar,
            start_cstart=start_cstart,
            paged_parse_result=paged_parse_result,
        )
        return run_dt, paged_parse_result, result_entry

    async def _resolve_scholar_outcome(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        if paged_parse_result.skipped_no_change:
            return self._skipped_no_change_outcome(
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
            )
        return await self._upsert_publications_outcome(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )

    @staticmethod
    def _result_counters(result_entry: dict[str, Any]) -> tuple[int, int, int]:
        outcome = str(result_entry.get("outcome", "")).strip().lower()
        if outcome == "success":
            return 1, 0, 0
        if outcome == "partial":
            return 1, 0, 1
        if outcome == "failed":
            return 0, 1, 0
        raise RuntimeError(f"Unexpected scholar outcome label: {outcome!r}")

    @staticmethod
    def _find_scholar_result_index(
        *,
        scholar_results: list[dict[str, Any]],
        scholar_profile_id: int,
    ) -> int | None:
        for index, result_entry in enumerate(scholar_results):
            current_scholar_id = _int_or_default(result_entry.get("scholar_profile_id"), 0)
            if current_scholar_id == scholar_profile_id:
                return index
        return None

    @staticmethod
    def _adjust_progress_counts(
        *,
        progress: RunProgress,
        succeeded_delta: int,
        failed_delta: int,
        partial_delta: int,
    ) -> None:
        progress.succeeded_count += succeeded_delta
        progress.failed_count += failed_delta
        progress.partial_count += partial_delta
        if progress.succeeded_count < 0 or progress.failed_count < 0 or progress.partial_count < 0:
            raise RuntimeError("RunProgress counters entered invalid negative state.")

    @staticmethod
    def _apply_outcome_to_progress(
        *,
        progress: RunProgress,
        outcome: ScholarProcessingOutcome,
    ) -> None:
        scholar_profile_id = _int_or_default(outcome.result_entry.get("scholar_profile_id"), 0)
        if scholar_profile_id <= 0:
            raise RuntimeError("Scholar outcome missing valid scholar_profile_id.")
        prior_index = ScholarIngestionService._find_scholar_result_index(
            scholar_results=progress.scholar_results,
            scholar_profile_id=scholar_profile_id,
        )
        next_succeeded, next_failed, next_partial = ScholarIngestionService._result_counters(outcome.result_entry)
        if prior_index is None:
            progress.scholar_results.append(outcome.result_entry)
            ScholarIngestionService._adjust_progress_counts(
                progress=progress,
                succeeded_delta=next_succeeded,
                failed_delta=next_failed,
                partial_delta=next_partial,
            )
            return
        previous_entry = progress.scholar_results[prior_index]
        prev_succeeded, prev_failed, prev_partial = ScholarIngestionService._result_counters(previous_entry)
        progress.scholar_results[prior_index] = outcome.result_entry
        ScholarIngestionService._adjust_progress_counts(
            progress=progress,
            succeeded_delta=next_succeeded - prev_succeeded,
            failed_delta=next_failed - prev_failed,
            partial_delta=next_partial - prev_partial,
        )

    def _unexpected_scholar_exception_outcome(
        self,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        start_cstart: int,
        exc: Exception,
    ) -> ScholarProcessingOutcome:
        scholar.last_run_status = RunStatus.FAILED
        scholar.last_run_dt = datetime.now(UTC)
        logger.exception(
            "ingestion.scholar_unexpected_failure",
            extra={
                "crawl_run_id": run.id,
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
            },
        )
        return ScholarProcessingOutcome(
            result_entry={
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
                "state": "ingestion_error",
                "state_reason": "scholar_processing_exception",
                "outcome": "failed",
                "attempt_count": 0,
                "publication_count": 0,
                "start_cstart": start_cstart,
                "warnings": [],
                "error": str(exc),
                "debug": {"exception_type": type(exc).__name__, "exception_message": str(exc)},
            },
            succeeded_count_delta=0,
            failed_count_delta=1,
            partial_count_delta=0,
            discovered_publication_count=0,
        )

    @staticmethod
    def _summarize_failures(
        *,
        scholar_results: list[dict[str, Any]],
    ) -> RunFailureSummary:
        failed_state_counts: dict[str, int] = {}
        failed_reason_counts: dict[str, int] = {}
        scrape_failure_counts: dict[str, int] = {}
        retries_scheduled_count = 0
        scholars_with_retries_count = 0
        retry_exhausted_count = 0
        for entry in scholar_results:
            retries_for_entry = max(0, _int_or_default(entry.get("attempt_count"), 0) - 1)
            if retries_for_entry > 0:
                retries_scheduled_count += retries_for_entry
                scholars_with_retries_count += 1
            if str(entry.get("outcome", "")) != "failed":
                continue
            state = str(entry.get("state", "")).strip()
            if state not in FAILED_STATES:
                continue
            failed_state_counts[state] = failed_state_counts.get(state, 0) + 1
            reason = str(entry.get("state_reason", "")).strip()
            if reason:
                failed_reason_counts[reason] = failed_reason_counts.get(reason, 0) + 1
            bucket = _classify_failure_bucket(state=state, state_reason=reason)
            scrape_failure_counts[bucket] = scrape_failure_counts.get(bucket, 0) + 1
            if state == ParseState.NETWORK_ERROR.value and retries_for_entry > 0:
                retry_exhausted_count += 1
        return RunFailureSummary(
            failed_state_counts=failed_state_counts,
            failed_reason_counts=failed_reason_counts,
            scrape_failure_counts=scrape_failure_counts,
            retries_scheduled_count=retries_scheduled_count,
            scholars_with_retries_count=scholars_with_retries_count,
            retry_exhausted_count=retry_exhausted_count,
        )

    @staticmethod
    def _build_alert_summary(
        *,
        failure_summary: RunFailureSummary,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> RunAlertSummary:
        blocked_failure_count = int(failure_summary.scrape_failure_counts.get(FAILURE_BUCKET_BLOCKED, 0))
        network_failure_count = int(failure_summary.scrape_failure_counts.get(FAILURE_BUCKET_NETWORK, 0))
        blocked_threshold = max(1, int(alert_blocked_failure_threshold))
        network_threshold = max(1, int(alert_network_failure_threshold))
        retry_threshold = max(1, int(alert_retry_scheduled_threshold))
        alert_flags = {
            "blocked_failure_threshold_exceeded": blocked_failure_count >= blocked_threshold,
            "network_failure_threshold_exceeded": network_failure_count >= network_threshold,
            "retry_scheduled_threshold_exceeded": failure_summary.retries_scheduled_count >= retry_threshold,
        }
        return RunAlertSummary(
            blocked_failure_count=blocked_failure_count,
            network_failure_count=network_failure_count,
            blocked_failure_threshold=blocked_threshold,
            network_failure_threshold=network_threshold,
            retry_scheduled_threshold=retry_threshold,
            alert_flags=alert_flags,
        )

    @staticmethod
    def _apply_safety_outcome(
        *,
        user_settings,
        run: CrawlRun,
        user_id: int,
        alert_summary: RunAlertSummary,
    ) -> None:
        pre_apply_state = run_safety_service.get_safety_event_context(
            user_settings,
            now_utc=datetime.now(UTC),
        )
        safety_state, cooldown_trigger_reason = run_safety_service.apply_run_safety_outcome(
            user_settings,
            run_id=int(run.id),
            blocked_failure_count=alert_summary.blocked_failure_count,
            network_failure_count=alert_summary.network_failure_count,
            blocked_failure_threshold=alert_summary.blocked_failure_threshold,
            network_failure_threshold=alert_summary.network_failure_threshold,
            blocked_cooldown_seconds=settings.ingestion_safety_cooldown_blocked_seconds,
            network_cooldown_seconds=settings.ingestion_safety_cooldown_network_seconds,
            now_utc=datetime.now(UTC),
        )
        if cooldown_trigger_reason is not None:
            structured_log(
                logger,
                "warning",
                "ingestion.safety_cooldown_entered",
                user_id=user_id,
                crawl_run_id=int(run.id),
                reason=cooldown_trigger_reason,
                blocked_failure_count=alert_summary.blocked_failure_count,
                network_failure_count=alert_summary.network_failure_count,
                blocked_failure_threshold=alert_summary.blocked_failure_threshold,
                network_failure_threshold=alert_summary.network_failure_threshold,
                cooldown_until=safety_state.get("cooldown_until"),
                cooldown_remaining_seconds=safety_state.get("cooldown_remaining_seconds"),
                safety_counters=safety_state.get("counters", {}),
            )
        elif pre_apply_state.get("cooldown_active") and not safety_state.get("cooldown_active"):
            structured_log(
                logger,
                "info",
                "ingestion.cooldown_cleared",
                user_id=user_id,
                crawl_run_id=int(run.id),
                reason=pre_apply_state.get("cooldown_reason"),
                cooldown_until=pre_apply_state.get("cooldown_until"),
            )

    def _finalize_run_record(
        self,
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        progress: RunProgress,
        failure_summary: RunFailureSummary,
        alert_summary: RunAlertSummary,
        idempotency_key: str | None,
    ) -> None:
        run.end_dt = datetime.now(UTC)
        if run.status != RunStatus.CANCELED:
            run.status = self._resolve_run_status(
                scholar_count=len(scholars),
                succeeded_count=progress.succeeded_count,
                failed_count=progress.failed_count,
                partial_count=progress.partial_count,
            )
        run.error_log = {
            "scholar_results": progress.scholar_results,
            "summary": {
                "succeeded_count": progress.succeeded_count,
                "failed_count": progress.failed_count,
                "partial_count": progress.partial_count,
                "failed_state_counts": failure_summary.failed_state_counts,
                "failed_reason_counts": failure_summary.failed_reason_counts,
                "scrape_failure_counts": failure_summary.scrape_failure_counts,
                "retry_counts": {
                    "retries_scheduled_count": failure_summary.retries_scheduled_count,
                    "scholars_with_retries_count": failure_summary.scholars_with_retries_count,
                    "retry_exhausted_count": failure_summary.retry_exhausted_count,
                },
                "alert_thresholds": {
                    "blocked_failure_threshold": alert_summary.blocked_failure_threshold,
                    "network_failure_threshold": alert_summary.network_failure_threshold,
                    "retry_scheduled_threshold": alert_summary.retry_scheduled_threshold,
                },
                "alert_flags": alert_summary.alert_flags,
            },
            "meta": {"idempotency_key": idempotency_key} if idempotency_key else {},
        }

    @staticmethod
    def _paging_kwargs(
        *,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
    ) -> dict[str, Any]:
        return {
            "request_delay_seconds": request_delay_seconds,
            "network_error_retries": network_error_retries,
            "retry_backoff_seconds": retry_backoff_seconds,
            "rate_limit_retries": rate_limit_retries,
            "rate_limit_backoff_seconds": rate_limit_backoff_seconds,
            "max_pages_per_scholar": max_pages_per_scholar,
            "page_size": page_size,
        }

    @staticmethod
    def _threshold_kwargs(
        *,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> dict[str, Any]:
        return {
            "alert_blocked_failure_threshold": alert_blocked_failure_threshold,
            "alert_network_failure_threshold": alert_network_failure_threshold,
            "alert_retry_scheduled_threshold": alert_retry_scheduled_threshold,
        }

    @staticmethod
    def _run_execution_summary(
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        progress: RunProgress,
    ) -> RunExecutionSummary:
        return RunExecutionSummary(
            crawl_run_id=run.id,
            status=run.status,
            scholar_count=len(scholars),
            succeeded_count=progress.succeeded_count,
            failed_count=progress.failed_count,
            partial_count=progress.partial_count,
            new_publication_count=run.new_pub_count,
        )

    async def _initialize_run_for_user(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholar_profile_ids: set[int] | None,
        start_cstart_by_scholar_id: dict[int, int] | None,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        idempotency_key: str | None,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> tuple[Any, CrawlRun, list[ScholarProfile], dict[int, int]]:
        user_settings = await self._load_user_settings_for_run(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
        )
        if not await self._try_acquire_user_lock(db_session, user_id=user_id):
            raise RunAlreadyInProgressError(f"Run already in progress for user_id={user_id}.")
        filtered_scholar_ids, start_cstart_map = self._normalize_run_targets(
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
        )
        scholars = await self._load_target_scholars(
            db_session,
            user_id=user_id,
            filtered_scholar_ids=filtered_scholar_ids,
        )
        run = await self._start_run_record_for_targets(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            scholars=scholars,
            filtered=filtered_scholar_ids is not None,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
            idempotency_key=idempotency_key,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        return user_settings, run, scholars, start_cstart_map

    async def _start_run_record_for_targets(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholars: list[ScholarProfile],
        filtered: bool,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        idempotency_key: str | None,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> CrawlRun:
        structured_log(
            logger,
            "info",
            "ingestion.run_started",
            user_id=user_id,
            trigger_type=trigger_type.value,
            scholar_count=len(scholars),
            is_filtered_run=filtered,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
            idempotency_key=idempotency_key,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        run = self._create_running_run(
            user_id=user_id,
            trigger_type=trigger_type,
            scholar_count=len(scholars),
            idempotency_key=idempotency_key,
        )
        db_session.add(run)
        try:
            await db_session.flush()
        except IntegrityError as exc:
            if _is_active_run_integrity_error(exc):
                await db_session.rollback()
                raise RunAlreadyInProgressError(f"Run already in progress for user_id={user_id}.") from exc
            raise
        return run

    async def _run_scholar_iteration(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        user_id: int,
        start_cstart_map: dict[int, int],
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> RunProgress:
        progress = RunProgress()

        # ── Pass 1: first page of every scholar (breadth-first) ──────────
        # This ensures all scholars have visible publications as quickly as
        # possible, rather than fully paginating one scholar before the next.
        first_pass_cstarts: dict[int, int] = {}
        for index, scholar in enumerate(scholars):
            await db_session.refresh(run)
            if run.status == RunStatus.CANCELED:
                structured_log(
                    logger,
                    "info",
                    "ingestion.run_canceled",
                    run_id=run.id,
                    user_id=user_id,
                )
                return progress
            await self._wait_between_scholars(index=index, request_delay_seconds=request_delay_seconds)
            start_cstart = int(start_cstart_map.get(int(scholar.id), 0))
            outcome = await self._process_scholar(
                db_session,
                run=run,
                scholar=scholar,
                user_id=user_id,
                request_delay_seconds=request_delay_seconds,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                rate_limit_retries=rate_limit_retries,
                rate_limit_backoff_seconds=rate_limit_backoff_seconds,
                max_pages_per_scholar=1,
                page_size=page_size,
                start_cstart=start_cstart,
                auto_queue_continuations=False,
                queue_delay_seconds=queue_delay_seconds,
            )
            self._apply_outcome_to_progress(progress=progress, outcome=outcome)
            # Track where to resume from for the deep pass
            resume_cstart = outcome.result_entry.get("continuation_cstart")
            if resume_cstart is not None and int(resume_cstart) > start_cstart:
                first_pass_cstarts[int(scholar.id)] = int(resume_cstart)

        # ── Pass 2: remaining pages for each scholar (depth) ─────────────
        remaining_max = max(max_pages_per_scholar - 1, 0)
        if remaining_max <= 0:
            return progress

        for index, scholar in enumerate(scholars):
            resume_cstart = first_pass_cstarts.get(int(scholar.id))
            if resume_cstart is None:
                continue  # first page failed, had no continuation, or was skipped
            await db_session.refresh(run)
            if run.status == RunStatus.CANCELED:
                structured_log(
                    logger,
                    "info",
                    "ingestion.run_canceled",
                    run_id=run.id,
                    user_id=user_id,
                )
                break
            await self._wait_between_scholars(index=index, request_delay_seconds=request_delay_seconds)
            outcome = await self._process_scholar(
                db_session,
                run=run,
                scholar=scholar,
                user_id=user_id,
                request_delay_seconds=request_delay_seconds,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                rate_limit_retries=rate_limit_retries,
                rate_limit_backoff_seconds=rate_limit_backoff_seconds,
                max_pages_per_scholar=remaining_max,
                page_size=page_size,
                start_cstart=resume_cstart,
                auto_queue_continuations=auto_queue_continuations,
                queue_delay_seconds=queue_delay_seconds,
            )
            self._apply_outcome_to_progress(progress=progress, outcome=outcome)
        return progress

    def _complete_run_for_user(
        self,
        *,
        user_settings: Any,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        user_id: int,
        progress: RunProgress,
        idempotency_key: str | None,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> tuple[RunFailureSummary, RunAlertSummary]:
        failure_summary = self._summarize_failures(scholar_results=progress.scholar_results)
        alert_summary = self._build_alert_summary(
            failure_summary=failure_summary,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        if alert_summary.alert_flags["blocked_failure_threshold_exceeded"]:
            structured_log(
                logger,
                "warning",
                "ingestion.alert_blocked_failure_threshold_exceeded",
                user_id=user_id,
                crawl_run_id=int(run.id),
                blocked_failure_count=alert_summary.blocked_failure_count,
                threshold=alert_summary.blocked_failure_threshold,
            )
        if alert_summary.alert_flags["network_failure_threshold_exceeded"]:
            structured_log(
                logger,
                "warning",
                "ingestion.alert_network_failure_threshold_exceeded",
                user_id=user_id,
                crawl_run_id=int(run.id),
                network_failure_count=alert_summary.network_failure_count,
                threshold=alert_summary.network_failure_threshold,
            )
        if alert_summary.alert_flags["retry_scheduled_threshold_exceeded"]:
            structured_log(
                logger,
                "warning",
                "ingestion.alert_retry_scheduled_threshold_exceeded",
                user_id=user_id,
                crawl_run_id=int(run.id),
                retries_scheduled_count=failure_summary.retries_scheduled_count,
                threshold=alert_summary.retry_scheduled_threshold,
            )
        self._apply_safety_outcome(user_settings=user_settings, run=run, user_id=user_id, alert_summary=alert_summary)
        self._finalize_run_record(
            run=run,
            scholars=scholars,
            progress=progress,
            failure_summary=failure_summary,
            alert_summary=alert_summary,
            idempotency_key=idempotency_key,
        )
        return failure_summary, alert_summary

    async def initialize_run(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        rate_limit_retries: int | None = None,
        rate_limit_backoff_seconds: float | None = None,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        scholar_profile_ids: set[int] | None = None,
        start_cstart_by_scholar_id: dict[int, int] | None = None,
        idempotency_key: str | None = None,
        alert_blocked_failure_threshold: int = 1,
        alert_network_failure_threshold: int = 2,
        alert_retry_scheduled_threshold: int = 3,
    ) -> tuple[CrawlRun, list[ScholarProfile], dict[int, int]]:
        effective_delay = self._effective_request_delay_seconds(request_delay_seconds)
        if effective_delay != _int_or_default(request_delay_seconds, effective_delay):
            structured_log(
                logger,
                "warning",
                "ingestion.delay_coerced",
                user_id=user_id,
                requested_request_delay_seconds=_int_or_default(request_delay_seconds, 0),
                effective_request_delay_seconds=effective_delay,
                policy_minimum_request_delay_seconds=user_settings_service.resolve_request_delay_minimum(
                    settings.ingestion_min_request_delay_seconds
                ),
            )

        paging_kwargs = self._paging_kwargs(
            request_delay_seconds=effective_delay,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries
            if rate_limit_retries is not None
            else settings.ingestion_rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds
            if rate_limit_backoff_seconds is not None
            else settings.ingestion_rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        threshold_kwargs = self._threshold_kwargs(
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )

        _, run, scholars, start_cstart_map = await self._initialize_run_for_user(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
            idempotency_key=idempotency_key,
            **paging_kwargs,
            **threshold_kwargs,
        )
        return run, scholars, start_cstart_map

    async def execute_run(
        self,
        session_factory: Any,
        *,
        run_id: int,
        user_id: int,
        scholars: list[ScholarProfile],
        start_cstart_map: dict[int, int],
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        rate_limit_retries: int | None = None,
        rate_limit_backoff_seconds: float | None = None,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        auto_queue_continuations: bool = True,
        queue_delay_seconds: int = 60,
        alert_blocked_failure_threshold: int = 1,
        alert_network_failure_threshold: int = 2,
        alert_retry_scheduled_threshold: int = 3,
        idempotency_key: str | None = None,
    ) -> None:
        async with session_factory() as db_session:
            try:
                # Re-fetch everything to ensure attachment to the new session
                run, user_settings, attached_scholars = await self._prepare_execute_run(
                    db_session, run_id=run_id, user_id=user_id, scholars=scholars
                )

                paging_kwargs = self._paging_kwargs(
                    request_delay_seconds=request_delay_seconds,
                    network_error_retries=network_error_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                    rate_limit_retries=rate_limit_retries
                    if rate_limit_retries is not None
                    else settings.ingestion_rate_limit_retries,
                    rate_limit_backoff_seconds=rate_limit_backoff_seconds
                    if rate_limit_backoff_seconds is not None
                    else settings.ingestion_rate_limit_backoff_seconds,
                    max_pages_per_scholar=max_pages_per_scholar,
                    page_size=page_size,
                )
                threshold_kwargs = self._threshold_kwargs(
                    alert_blocked_failure_threshold=alert_blocked_failure_threshold,
                    alert_network_failure_threshold=alert_network_failure_threshold,
                    alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
                )

                progress = await self._run_scholar_iteration(
                    db_session,
                    run=run,
                    scholars=attached_scholars,
                    user_id=user_id,
                    start_cstart_map=start_cstart_map,
                    auto_queue_continuations=auto_queue_continuations,
                    queue_delay_seconds=queue_delay_seconds,
                    **paging_kwargs,
                )

                failure_summary, alert_summary = self._complete_run_for_user(
                    user_settings=user_settings,
                    run=run,
                    scholars=attached_scholars,
                    user_id=user_id,
                    progress=progress,
                    idempotency_key=idempotency_key,
                    **threshold_kwargs,
                )

                # Capture the final status that _finalize_run_record computed,
                # then set RESOLVING so the UI shows enrichment is in progress.
                intended_final_status = run.status
                if intended_final_status not in (RunStatus.CANCELED,):
                    run.status = RunStatus.RESOLVING
                await db_session.commit()
                structured_log(
                    logger,
                    "info",
                    "ingestion.run_completed",
                    user_id=user_id,
                    crawl_run_id=run.id,
                    status=run.status.value,
                    scholar_count=len(attached_scholars),
                    succeeded_count=progress.succeeded_count,
                    failed_count=progress.failed_count,
                    partial_count=progress.partial_count,
                    new_publication_count=run.new_pub_count,
                    blocked_failure_count=alert_summary.blocked_failure_count,
                    network_failure_count=alert_summary.network_failure_count,
                    retries_scheduled_count=failure_summary.retries_scheduled_count,
                    alert_flags=alert_summary.alert_flags,
                )

                # Fire-and-forget enrichment in a separate background task
                if intended_final_status not in (RunStatus.CANCELED,):
                    task = asyncio.create_task(
                        self._background_enrich(
                            session_factory,
                            run_id=run.id,
                            intended_final_status=intended_final_status,
                            openalex_api_key=getattr(user_settings, "openalex_api_key", None),
                        )
                    )
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
            except Exception as exc:
                await db_session.rollback()
                logger.exception("ingestion.background_run_failed", extra={"run_id": run_id, "user_id": user_id})
                await self._fail_run_in_background(session_factory, run_id, exc)

    async def _prepare_execute_run(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
        user_id: int,
        scholars: list[ScholarProfile],
    ) -> tuple[CrawlRun, Any, list[ScholarProfile]]:
        run_result = await db_session.execute(select(CrawlRun).where(CrawlRun.id == run_id))
        run = run_result.scalar_one()
        user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=user_id)

        scholar_ids = [s.id for s in scholars]
        scholars_result = await db_session.execute(
            select(ScholarProfile)
            .where(ScholarProfile.id.in_(scholar_ids))
            .order_by(ScholarProfile.created_at.asc(), ScholarProfile.id.asc())
        )
        return run, user_settings, list(scholars_result.scalars().all())

    async def _fail_run_in_background(self, session_factory: Any, run_id: int, exc: Exception) -> None:
        async with session_factory() as cleanup_session:
            run_to_fail = await cleanup_session.get(CrawlRun, run_id)
            if run_to_fail:
                run_to_fail.status = RunStatus.FAILED
                run_to_fail.end_dt = datetime.now(UTC)
                run_to_fail.error_log["terminal_exception"] = str(exc)
                await cleanup_session.commit()

    async def _background_enrich(
        self,
        session_factory: Any,
        *,
        run_id: int,
        intended_final_status: RunStatus,
        openalex_api_key: str | None = None,
    ) -> None:
        """Run enrichment independently — failures don't affect run status."""
        try:
            async with session_factory() as session:
                await self._enrich_pending_publications(
                    session,
                    run_id=run_id,
                    openalex_api_key=openalex_api_key,
                )
                run = await session.get(CrawlRun, run_id)
                if run is not None and run.status == RunStatus.RESOLVING:
                    run.status = intended_final_status
                await session.commit()
                logger.info(
                    "ingestion.background_enrichment_complete",
                    extra={"run_id": run_id, "final_status": str(intended_final_status)},
                )
        except Exception:
            logger.exception(
                "ingestion.background_enrichment_failed",
                extra={"run_id": run_id},
            )
            # Still transition out of RESOLVING so the run doesn't stay stuck.
            try:
                async with session_factory() as fallback_session:
                    run = await fallback_session.get(CrawlRun, run_id)
                    if run is not None and run.status == RunStatus.RESOLVING:
                        run.status = intended_final_status
                    await fallback_session.commit()
            except Exception:
                logger.exception(
                    "ingestion.background_enrichment_fallback_failed",
                    extra={"run_id": run_id},
                )

    async def run_for_user(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        rate_limit_retries: int | None = None,
        rate_limit_backoff_seconds: float | None = None,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        scholar_profile_ids: set[int] | None = None,
        start_cstart_by_scholar_id: dict[int, int] | None = None,
        auto_queue_continuations: bool = True,
        queue_delay_seconds: int = 60,
        idempotency_key: str | None = None,
        alert_blocked_failure_threshold: int = 1,
        alert_network_failure_threshold: int = 2,
        alert_retry_scheduled_threshold: int = 3,
    ) -> RunExecutionSummary:
        # Legacy/Synchronous trigger (used by tests or older flows)
        run, scholars, start_cstart_map = await self.initialize_run(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
            idempotency_key=idempotency_key,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )

        paging_kwargs = self._paging_kwargs(
            request_delay_seconds=self._effective_request_delay_seconds(request_delay_seconds),
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries
            if rate_limit_retries is not None
            else settings.ingestion_rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds
            if rate_limit_backoff_seconds is not None
            else settings.ingestion_rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )

        threshold_kwargs = self._threshold_kwargs(
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )

        progress = await self._run_scholar_iteration(
            db_session,
            run=run,
            scholars=scholars,
            user_id=user_id,
            start_cstart_map=start_cstart_map,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
            **paging_kwargs,
        )

        user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=user_id)
        failure_summary, alert_summary = self._complete_run_for_user(
            user_settings=user_settings,
            run=run,
            scholars=scholars,
            user_id=user_id,
            progress=progress,
            idempotency_key=idempotency_key,
            **threshold_kwargs,
        )

        # Set RESOLVING during enrichment (synchronous path).
        intended_final_status = run.status
        if intended_final_status not in (RunStatus.CANCELED,):
            run.status = RunStatus.RESOLVING
        await db_session.commit()

        try:
            await self._enrich_pending_publications(
                db_session,
                run_id=run.id,
                openalex_api_key=getattr(user_settings, "openalex_api_key", None),
            )
        except Exception:
            logger.exception("ingestion.enrichment_failed", extra={"run_id": run.id})

        # Finalize to the intended status unless the run was canceled during resolving.
        if run.status == RunStatus.RESOLVING:
            run.status = intended_final_status
        await db_session.commit()

        structured_log(
            logger,
            "info",
            "ingestion.run_completed",
            user_id=user_id,
            crawl_run_id=run.id,
            status=run.status.value,
            scholar_count=len(scholars),
            succeeded_count=progress.succeeded_count,
            failed_count=progress.failed_count,
            partial_count=progress.partial_count,
            new_publication_count=run.new_pub_count,
            blocked_failure_count=alert_summary.blocked_failure_count,
            network_failure_count=alert_summary.network_failure_count,
            retries_scheduled_count=failure_summary.retries_scheduled_count,
            alert_flags=alert_summary.alert_flags,
        )
        return self._run_execution_summary(run=run, scholars=scholars, progress=progress)

    async def _run_is_canceled(
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

    async def _enrich_pending_publications(
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
            if await self._run_is_canceled(db_session, run_id=run_id):
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
                break  # Stop all enrichment — budget won't reset until midnight UTC
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
                # Check for cancellation periodically within the batch
                if await self._run_is_canceled(db_session, run_id=run_id):
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

    async def _enrich_publications_with_openalex(
        self,
        scholar: ScholarProfile,
        publications: list[PublicationCandidate],
    ) -> list[PublicationCandidate]:
        if not publications:
            return publications

        from app.services.openalex.client import OpenAlexClient
        from app.services.openalex.matching import find_best_match

        client = OpenAlexClient(api_key=settings.openalex_api_key, mailto=settings.crossref_api_mailto)

        # Batch requests by 25 to stay within URL length limits
        batch_size = 25
        enriched: list[PublicationCandidate] = []

        import re

        for i in range(0, len(publications), batch_size):
            batch = publications[i : i + batch_size]

            titles = []
            for p in batch:
                if not p.title:
                    continue
                # Strip all non-alphanumeric words to prevent OpenAlex API injection crashes
                # and minimize punctuation-based duplicate misses.
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

    def _resolve_run_status(
        self,
        *,
        scholar_count: int,
        succeeded_count: int,
        failed_count: int,
        partial_count: int,
    ) -> RunStatus:
        if scholar_count == 0:
            return RunStatus.SUCCESS
        if failed_count == scholar_count:
            return RunStatus.FAILED
        if failed_count > 0 or partial_count > 0:
            return RunStatus.PARTIAL_FAILURE
        if succeeded_count > 0:
            return RunStatus.SUCCESS
        return RunStatus.FAILED

    def _resolve_continuation_queue_target(
        self,
        *,
        outcome: str,
        state: str,
        pagination_truncated_reason: str | None,
        continuation_cstart: int | None,
        fallback_cstart: int,
    ) -> tuple[str | None, int]:
        if outcome == "partial":
            reason = (pagination_truncated_reason or "").strip()
            if reason in RESUMABLE_PARTIAL_REASONS or reason.startswith(RESUMABLE_PARTIAL_REASON_PREFIXES):
                return reason, queue_service.normalize_cstart(
                    continuation_cstart if continuation_cstart is not None else fallback_cstart
                )
            return None, queue_service.normalize_cstart(fallback_cstart)

        if outcome == "failed" and state == ParseState.NETWORK_ERROR.value:
            return "network_error_retry", queue_service.normalize_cstart(
                continuation_cstart if continuation_cstart is not None else fallback_cstart
            )

        return None, queue_service.normalize_cstart(fallback_cstart)

    def _build_failure_debug_context(
        self,
        *,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        attempt_log: list[dict[str, Any]],
        page_logs: list[dict[str, Any]] | None = None,
        exception: Exception | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "requested_url": fetch_result.requested_url,
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "fetch_error": fetch_result.error,
            "state_reason": parsed_page.state_reason,
            "profile_name": parsed_page.profile_name,
            "profile_image_url": parsed_page.profile_image_url,
            "articles_range": parsed_page.articles_range,
            "has_show_more_button": parsed_page.has_show_more_button,
            "has_operation_error_banner": parsed_page.has_operation_error_banner,
            "warning_codes": parsed_page.warnings,
            "marker_counts_nonzero": {key: value for key, value in parsed_page.marker_counts.items() if value > 0},
            "body_length": len(fetch_result.body),
            "body_sha256": hashlib.sha256(fetch_result.body.encode("utf-8")).hexdigest() if fetch_result.body else None,
            "body_excerpt": _build_body_excerpt(fetch_result.body),
            "attempt_log": attempt_log,
        }
        if page_logs:
            context["page_logs"] = page_logs
        if exception is not None:
            context["exception_type"] = type(exception).__name__
            context["exception_message"] = str(exception)
        return context

    async def _try_acquire_user_lock(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
    ) -> bool:
        result = await db_session.execute(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :user_key)"),
            {
                "namespace": RUN_LOCK_NAMESPACE,
                "user_key": int(user_id),
            },
        )
        return bool(result.scalar_one())

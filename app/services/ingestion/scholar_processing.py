from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    RunStatus,
    ScholarProfile,
)
from app.logging_utils import structured_log
from app.services.ingestion import queue as queue_service
from app.services.ingestion.constants import (
    RESUMABLE_PARTIAL_REASON_PREFIXES,
    RESUMABLE_PARTIAL_REASONS,
)
from app.services.ingestion.pagination import PaginationEngine
from app.services.ingestion.publication_upsert import upsert_profile_publications
from app.services.ingestion.run_completion import apply_outcome_to_progress, build_failure_debug_context
from app.services.ingestion.types import (
    PagedParseResult,
    RunProgress,
    ScholarProcessingOutcome,
)
from app.services.scholar.parser import ParseState

logger = logging.getLogger(__name__)


def assert_valid_paged_parse_result(
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


def apply_first_page_profile_metadata(
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


def build_result_entry(
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


def skipped_no_change_outcome(
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


async def upsert_publications_outcome(
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
        return await _upsert_success_or_exception(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
            has_partial_publication_set=has_partial_set,
        )
    return _parse_failure_outcome(
        scholar=scholar,
        run_dt=run_dt,
        paged_parse_result=paged_parse_result,
        result_entry=result_entry,
    )


async def _upsert_success_or_exception(
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
        return _upsert_success(
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
            has_partial_publication_set=has_partial_publication_set,
        )
    except Exception as exc:
        return _upsert_exception_outcome(
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
            exc=exc,
        )


def _upsert_success(
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    run_dt: datetime,
    paged_parse_result: PagedParseResult,
    result_entry: dict[str, Any],
    has_partial_publication_set: bool,
) -> ScholarProcessingOutcome:
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
        result_entry["debug"] = build_failure_debug_context(
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
    result_entry["debug"] = build_failure_debug_context(
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
    *,
    scholar: ScholarProfile,
    run_dt: datetime,
    paged_parse_result: PagedParseResult,
    result_entry: dict[str, Any],
) -> ScholarProcessingOutcome:
    scholar.last_run_status = RunStatus.FAILED
    scholar.last_run_dt = run_dt
    result_entry["debug"] = build_failure_debug_context(
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


async def sync_continuation_queue(
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
    queue_reason, queue_cstart = resolve_continuation_queue_target(
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


def resolve_continuation_queue_target(
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


async def process_scholar(
    db_session: AsyncSession,
    *,
    pagination: PaginationEngine,
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
        run_dt, paged_parse_result, result_entry = await _fetch_and_prepare_scholar_result(
            db_session,
            pagination=pagination,
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
        outcome = await _resolve_scholar_outcome(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )
        await sync_continuation_queue(
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
    except Exception as exc:
        return unexpected_scholar_exception_outcome(
            run=run,
            scholar=scholar,
            start_cstart=start_cstart,
            exc=exc,
        )


async def _fetch_and_prepare_scholar_result(
    db_session: AsyncSession,
    *,
    pagination: PaginationEngine,
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
    paged_parse_result = await pagination.fetch_and_parse_all_pages(
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
    assert_valid_paged_parse_result(scholar_id=scholar.scholar_id, paged_parse_result=paged_parse_result)
    apply_first_page_profile_metadata(scholar=scholar, paged_parse_result=paged_parse_result, run_dt=run_dt)
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
    result_entry = build_result_entry(
        scholar=scholar,
        start_cstart=start_cstart,
        paged_parse_result=paged_parse_result,
    )
    return run_dt, paged_parse_result, result_entry


async def _resolve_scholar_outcome(
    db_session: AsyncSession,
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    run_dt: datetime,
    paged_parse_result: PagedParseResult,
    result_entry: dict[str, Any],
) -> ScholarProcessingOutcome:
    if paged_parse_result.skipped_no_change:
        return skipped_no_change_outcome(
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )
    return await upsert_publications_outcome(
        db_session,
        run=run,
        scholar=scholar,
        run_dt=run_dt,
        paged_parse_result=paged_parse_result,
        result_entry=result_entry,
    )


def unexpected_scholar_exception_outcome(
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


async def _run_first_pass(
    db_session: AsyncSession,
    *,
    scholars: list[ScholarProfile],
    pagination: PaginationEngine,
    run: CrawlRun,
    user_id: int,
    start_cstart_map: dict[int, int],
    scholar_kwargs: dict[str, Any],
    request_delay_seconds: int,
    queue_delay_seconds: int,
    progress: RunProgress,
) -> dict[int, int]:
    first_pass_cstarts: dict[int, int] = {}
    for index, scholar in enumerate(scholars):
        await db_session.refresh(run)
        if run.status == RunStatus.CANCELED:
            structured_log(logger, "info", "ingestion.run_canceled", run_id=run.id, user_id=user_id)
            return first_pass_cstarts
        if index > 0 and request_delay_seconds > 0:
            await asyncio.sleep(float(request_delay_seconds))
        start_cstart = int(start_cstart_map.get(int(scholar.id), 0))
        outcome = await process_scholar(
            db_session,
            pagination=pagination,
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=start_cstart,
            max_pages_per_scholar=1,
            auto_queue_continuations=False,
            queue_delay_seconds=queue_delay_seconds,
            **scholar_kwargs,
        )
        apply_outcome_to_progress(progress=progress, outcome=outcome)
        resume_cstart = outcome.result_entry.get("continuation_cstart")
        if resume_cstart is not None and int(resume_cstart) > start_cstart:
            first_pass_cstarts[int(scholar.id)] = int(resume_cstart)
    return first_pass_cstarts


async def _run_depth_pass(
    db_session: AsyncSession,
    *,
    scholars: list[ScholarProfile],
    first_pass_cstarts: dict[int, int],
    pagination: PaginationEngine,
    run: CrawlRun,
    user_id: int,
    scholar_kwargs: dict[str, Any],
    request_delay_seconds: int,
    remaining_max: int,
    auto_queue_continuations: bool,
    queue_delay_seconds: int,
    progress: RunProgress,
) -> None:
    for index, scholar in enumerate(scholars):
        resume_cstart = first_pass_cstarts.get(int(scholar.id))
        if resume_cstart is None:
            continue
        await db_session.refresh(run)
        if run.status == RunStatus.CANCELED:
            structured_log(logger, "info", "ingestion.run_canceled", run_id=run.id, user_id=user_id)
            break
        if index > 0 and request_delay_seconds > 0:
            await asyncio.sleep(float(request_delay_seconds))
        outcome = await process_scholar(
            db_session,
            pagination=pagination,
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=resume_cstart,
            max_pages_per_scholar=remaining_max,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
            **scholar_kwargs,
        )
        apply_outcome_to_progress(progress=progress, outcome=outcome)


async def run_scholar_iteration(
    db_session: AsyncSession,
    *,
    pagination: PaginationEngine,
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
    scholar_kwargs: dict[str, Any] = {
        "request_delay_seconds": request_delay_seconds,
        "network_error_retries": network_error_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
        "rate_limit_retries": rate_limit_retries,
        "rate_limit_backoff_seconds": rate_limit_backoff_seconds,
        "page_size": page_size,
    }
    first_pass_cstarts = await _run_first_pass(
        db_session,
        scholars=scholars,
        pagination=pagination,
        run=run,
        user_id=user_id,
        start_cstart_map=start_cstart_map,
        scholar_kwargs=scholar_kwargs,
        request_delay_seconds=request_delay_seconds,
        queue_delay_seconds=queue_delay_seconds,
        progress=progress,
    )
    remaining_max = max(max_pages_per_scholar - 1, 0)
    if remaining_max <= 0:
        return progress
    await _run_depth_pass(
        db_session,
        scholars=scholars,
        first_pass_cstarts=first_pass_cstarts,
        pagination=pagination,
        run=run,
        user_id=user_id,
        scholar_kwargs=scholar_kwargs,
        request_delay_seconds=request_delay_seconds,
        remaining_max=remaining_max,
        auto_queue_continuations=auto_queue_continuations,
        queue_delay_seconds=queue_delay_seconds,
        progress=progress,
    )
    return progress

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    PublicationPdfJob,
    PublicationPdfJobEvent,
    User,
)
from app.services.publications.pdf_queue_queries import (
    missing_pdf_candidates,
    retry_item_for_publication_id,
)
from app.services.publications.pdf_queue_resolution import schedule_rows
from app.services.publications.types import PublicationListItem
from app.settings import settings

PDF_STATUS_UNTRACKED = "untracked"
PDF_STATUS_QUEUED = "queued"
PDF_STATUS_RUNNING = "running"
PDF_STATUS_RESOLVED = "resolved"
PDF_STATUS_FAILED = "failed"

PDF_EVENT_QUEUED = "queued"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfRequeueResult:
    publication_exists: bool
    queued: bool


@dataclass(frozen=True)
class PdfBulkQueueResult:
    requested_count: int
    queued_count: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _publication_ids(rows: list[PublicationListItem]) -> list[int]:
    return sorted({row.publication_id for row in rows})


def _status_from_job(row: PublicationListItem, job: PublicationPdfJob | None) -> str:
    if row.pdf_url:
        return PDF_STATUS_RESOLVED
    if job is None:
        return PDF_STATUS_UNTRACKED
    return job.status


def _item_from_row_and_job(
    row: PublicationListItem,
    job: PublicationPdfJob | None,
) -> PublicationListItem:
    return PublicationListItem(
        publication_id=row.publication_id,
        scholar_profile_id=row.scholar_profile_id,
        scholar_label=row.scholar_label,
        title=row.title,
        year=row.year,
        citation_count=row.citation_count,
        venue_text=row.venue_text,
        pub_url=row.pub_url,
        pdf_url=row.pdf_url,
        is_read=row.is_read,
        is_favorite=row.is_favorite,
        first_seen_at=row.first_seen_at,
        is_new_in_latest_run=row.is_new_in_latest_run,
        pdf_status=_status_from_job(row, job),
        pdf_attempt_count=int(job.attempt_count) if job is not None else 0,
        pdf_failure_reason=job.last_failure_reason if job is not None else None,
        pdf_failure_detail=job.last_failure_detail if job is not None else None,
        display_identifier=row.display_identifier,
    )


def _queueable_rows(
    rows: list[PublicationListItem],
    *,
    max_items: int,
) -> list[PublicationListItem]:
    bounded = max(0, int(max_items))
    if bounded == 0:
        return []
    candidates = [row for row in rows if not row.pdf_url]
    return candidates[:bounded]


def _auto_retry_interval_seconds() -> int:
    return max(int(settings.pdf_auto_retry_interval_seconds), 1)


def _auto_retry_first_interval_seconds() -> int:
    return max(int(settings.pdf_auto_retry_first_interval_seconds), 1)


def _auto_retry_max_attempts() -> int:
    return max(int(settings.pdf_auto_retry_max_attempts), 1)


def _retry_interval_seconds_for_attempt_count(attempt_count: int) -> int:
    if int(attempt_count) <= 1:
        return _auto_retry_first_interval_seconds()
    return _auto_retry_interval_seconds()


def _cooldown_active(
    *,
    last_attempt_at: datetime | None,
    attempt_count: int,
) -> bool:
    if last_attempt_at is None:
        return False
    elapsed = (_utcnow() - last_attempt_at).total_seconds()
    return elapsed < _retry_interval_seconds_for_attempt_count(int(attempt_count))


def _can_enqueue_job(
    job: PublicationPdfJob | None,
    *,
    force_retry: bool,
) -> bool:
    if job is None:
        return True
    if job.status in {PDF_STATUS_QUEUED, PDF_STATUS_RUNNING}:
        return False
    if force_retry:
        return job.status in {PDF_STATUS_FAILED, PDF_STATUS_RESOLVED, PDF_STATUS_UNTRACKED}
    if job.status == PDF_STATUS_RESOLVED:
        return False
    if int(job.attempt_count) >= _auto_retry_max_attempts():
        return False
    return not _cooldown_active(
        last_attempt_at=job.last_attempt_at,
        attempt_count=int(job.attempt_count),
    )


def _event_row(
    *,
    publication_id: int,
    user_id: int | None,
    event_type: str,
    status: str | None,
) -> PublicationPdfJobEvent:
    return PublicationPdfJobEvent(
        publication_id=publication_id,
        user_id=user_id,
        event_type=event_type,
        status=status,
    )


def _queued_job(
    *,
    publication_id: int,
    user_id: int,
) -> PublicationPdfJob:
    now = _utcnow()
    return PublicationPdfJob(
        publication_id=publication_id,
        status=PDF_STATUS_QUEUED,
        queued_at=now,
        last_requested_by_user_id=user_id,
    )


def _mark_job_queued(job: PublicationPdfJob, *, user_id: int) -> None:
    now = _utcnow()
    job.status = PDF_STATUS_QUEUED
    job.queued_at = now
    job.last_requested_by_user_id = user_id
    job.last_failure_reason = None
    job.last_failure_detail = None
    job.last_source = None


def _state_map(jobs: list[PublicationPdfJob]) -> dict[int, PublicationPdfJob]:
    return {int(job.publication_id): job for job in jobs}


async def _jobs_for_publication_ids(
    db_session: AsyncSession,
    *,
    publication_ids: list[int],
) -> dict[int, PublicationPdfJob]:
    if not publication_ids:
        return {}
    result = await db_session.execute(
        select(PublicationPdfJob).where(PublicationPdfJob.publication_id.in_(publication_ids))
    )
    return _state_map(list(result.scalars()))


async def overlay_pdf_job_state(
    db_session: AsyncSession,
    *,
    rows: list[PublicationListItem],
) -> list[PublicationListItem]:
    if not rows:
        return []
    jobs = await _jobs_for_publication_ids(
        db_session,
        publication_ids=_publication_ids(rows),
    )
    return [_item_from_row_and_job(row, jobs.get(row.publication_id)) for row in rows]


async def _enqueue_rows(
    db_session: AsyncSession,
    *,
    user_id: int,
    rows: list[PublicationListItem],
    force_retry: bool,
) -> list[PublicationListItem]:
    if not rows:
        return []
    queued: list[PublicationListItem] = []
    jobs = await _jobs_for_publication_ids(
        db_session,
        publication_ids=_publication_ids(rows),
    )
    for row in rows:
        job = jobs.get(row.publication_id)
        if not _can_enqueue_job(job, force_retry=force_retry):
            continue
        if job is None:
            job = _queued_job(publication_id=row.publication_id, user_id=user_id)
            jobs[row.publication_id] = job
            db_session.add(job)
        else:
            _mark_job_queued(job, user_id=user_id)
        db_session.add(
            _event_row(
                publication_id=row.publication_id,
                user_id=user_id,
                event_type=PDF_EVENT_QUEUED,
                status=PDF_STATUS_QUEUED,
            )
        )
        queued.append(row)
    if queued:
        await db_session.commit()
    return queued


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def enqueue_missing_pdf_jobs(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    rows: list[PublicationListItem],
    max_items: int,
) -> list[int]:
    queueable = _queueable_rows(rows, max_items=max_items)
    queued_rows = await _enqueue_rows(
        db_session,
        user_id=user_id,
        rows=queueable,
        force_retry=False,
    )
    schedule_rows(user_id=user_id, request_email=request_email, rows=queued_rows)
    return [row.publication_id for row in queued_rows]


async def enqueue_retry_pdf_job(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    row: PublicationListItem,
) -> bool:
    queued_rows = await _enqueue_rows(
        db_session,
        user_id=user_id,
        rows=[row],
        force_retry=True,
    )
    schedule_rows(user_id=user_id, request_email=request_email, rows=queued_rows)
    return bool(queued_rows)


async def enqueue_retry_pdf_job_for_publication_id(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    publication_id: int,
) -> PdfRequeueResult:
    row = await retry_item_for_publication_id(
        db_session,
        publication_id=publication_id,
    )
    if row is None:
        return PdfRequeueResult(publication_exists=False, queued=False)
    queued = await enqueue_retry_pdf_job(
        db_session,
        user_id=user_id,
        request_email=request_email,
        row=row,
    )
    return PdfRequeueResult(publication_exists=True, queued=queued)


async def enqueue_all_missing_pdf_jobs(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    limit: int = 1000,
) -> PdfBulkQueueResult:
    candidates = await missing_pdf_candidates(db_session, limit=limit)
    queued_rows = await _enqueue_rows(
        db_session,
        user_id=user_id,
        rows=candidates,
        force_retry=True,
    )
    schedule_rows(user_id=user_id, request_email=request_email, rows=queued_rows)
    return PdfBulkQueueResult(
        requested_count=len(candidates),
        queued_count=len(queued_rows),
    )


async def drain_ready_jobs(
    db_session: AsyncSession,
    *,
    limit: int,
    max_attempts: int,
) -> int:
    result = await db_session.execute(select(User.id).where(User.is_active.is_(True)).order_by(User.id.asc()).limit(1))
    system_user_id = result.scalar_one_or_none()
    if system_user_id is None:
        return 0

    bulk_result = await enqueue_all_missing_pdf_jobs(
        db_session,
        user_id=system_user_id,
        request_email=settings.unpaywall_email,
        limit=limit,
    )
    return bulk_result.queued_count

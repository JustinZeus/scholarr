from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiException
from app.logging_utils import structured_log
from app.services.ingestion import queue as ingestion_queue_service
from app.services.scholar import rate_limit as scholar_rate_limit
from app.services.scholar.source import ScholarSource
from app.services.scholars import application as scholar_service
from app.services.scholars import search_hints as scholar_search_hints
from app.settings import settings

logger = logging.getLogger(__name__)

CREATE_METADATA_HYDRATION_TIMEOUT_SECONDS = 5.0
INITIAL_SCHOLAR_SCRAPE_QUEUE_DELAY_SECONDS = 0
INITIAL_SCHOLAR_SCRAPE_QUEUE_REASON = "scholar_added_initial_scrape"


def needs_metadata_hydration(profile) -> bool:
    if not profile.profile_image_url:
        return True
    return not (profile.display_name or "").strip()


def is_create_hydration_rate_limited() -> tuple[bool, float]:
    remaining_seconds = scholar_rate_limit.remaining_scholar_slot_seconds(
        min_interval_seconds=float(settings.ingestion_min_request_delay_seconds),
    )
    return remaining_seconds > 0, remaining_seconds


def auto_enqueue_new_scholar_enabled() -> bool:
    if not settings.scheduler_enabled:
        return False
    if not settings.ingestion_automation_allowed:
        return False
    return bool(settings.ingestion_continuation_queue_enabled)


async def enqueue_initial_scrape_job_for_scholar(
    db_session: AsyncSession,
    *,
    profile,
    user_id: int,
) -> bool:
    if not auto_enqueue_new_scholar_enabled():
        return False
    try:
        await ingestion_queue_service.upsert_job(
            db_session,
            user_id=user_id,
            scholar_profile_id=int(profile.id),
            resume_cstart=0,
            reason=INITIAL_SCHOLAR_SCRAPE_QUEUE_REASON,
            run_id=None,
            delay_seconds=INITIAL_SCHOLAR_SCRAPE_QUEUE_DELAY_SECONDS,
        )
        await db_session.commit()
    except Exception:
        await db_session.rollback()
        structured_log(
            logger,
            "warning",
            "api.scholars.initial_scrape_enqueue_failed",
            user_id=user_id,
            scholar_profile_id=profile.id,
        )
        return False

    structured_log(
        logger,
        "info",
        "api.scholars.initial_scrape_enqueued",
        user_id=user_id,
        scholar_profile_id=profile.id,
        reason=INITIAL_SCHOLAR_SCRAPE_QUEUE_REASON,
    )
    return True


def uploaded_image_media_path(scholar_profile_id: int) -> str:
    return f"/scholar-images/{scholar_profile_id}/upload"


def serialize_scholar(profile) -> dict[str, object]:
    uploaded_image_url = None
    if profile.profile_image_upload_path:
        uploaded_image_url = uploaded_image_media_path(int(profile.id))

    profile_image_url, profile_image_source = scholar_search_hints.resolve_profile_image(
        profile,
        uploaded_image_url=uploaded_image_url,
    )

    return {
        "id": int(profile.id),
        "scholar_id": profile.scholar_id,
        "display_name": profile.display_name,
        "profile_image_url": profile_image_url,
        "profile_image_source": profile_image_source,
        "is_enabled": bool(profile.is_enabled),
        "baseline_completed": bool(profile.baseline_completed),
        "last_run_dt": profile.last_run_dt,
        "last_run_status": (profile.last_run_status.value if profile.last_run_status is not None else None),
    }


async def hydrate_scholar_metadata_if_needed(
    db_session: AsyncSession,
    *,
    profile,
    source: ScholarSource,
    user_id: int,
):
    if not needs_metadata_hydration(profile):
        return profile

    should_skip, remaining_seconds = is_create_hydration_rate_limited()
    if should_skip:
        structured_log(
            logger,
            "info",
            "api.scholars.create_metadata_hydration_skipped",
            reason="scholar_request_throttle_active",
            user_id=user_id,
            scholar_profile_id=profile.id,
            retry_after_seconds=round(remaining_seconds, 3),
        )
        return profile

    try:
        return await asyncio.wait_for(
            scholar_service.hydrate_profile_metadata(
                db_session,
                profile=profile,
                source=source,
            ),
            timeout=CREATE_METADATA_HYDRATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        structured_log(
            logger,
            "info",
            "api.scholars.create_metadata_hydration_skipped",
            reason="create_timeout",
            user_id=user_id,
            scholar_profile_id=profile.id,
        )
    except Exception:
        structured_log(
            logger,
            "warning",
            "api.scholars.create_metadata_hydration_failed",
            user_id=user_id,
            scholar_profile_id=profile.id,
        )
    return profile


def search_kwargs() -> dict[str, Any]:
    return {
        "network_error_retries": settings.ingestion_network_error_retries,
        "retry_backoff_seconds": settings.ingestion_retry_backoff_seconds,
        "search_enabled": settings.scholar_name_search_enabled,
        "cache_ttl_seconds": settings.scholar_name_search_cache_ttl_seconds,
        "blocked_cache_ttl_seconds": settings.scholar_name_search_blocked_cache_ttl_seconds,
        "cache_max_entries": settings.scholar_name_search_cache_max_entries,
        "min_interval_seconds": settings.scholar_name_search_min_interval_seconds,
        "interval_jitter_seconds": settings.scholar_name_search_interval_jitter_seconds,
        "cooldown_block_threshold": settings.scholar_name_search_cooldown_block_threshold,
        "cooldown_seconds": settings.scholar_name_search_cooldown_seconds,
        "retry_alert_threshold": settings.scholar_name_search_alert_retry_count_threshold,
        "cooldown_rejection_alert_threshold": (settings.scholar_name_search_alert_cooldown_rejections_threshold),
    }


def search_response_data(query: str, parsed) -> dict[str, object]:
    return {
        "query": query.strip(),
        "state": parsed.state.value,
        "state_reason": parsed.state_reason,
        "action_hint": scholar_search_hints.scrape_state_hint(
            state=parsed.state,
            state_reason=parsed.state_reason,
        ),
        "candidates": [
            {
                "scholar_id": item.scholar_id,
                "display_name": item.display_name,
                "affiliation": item.affiliation,
                "email_domain": item.email_domain,
                "cited_by_count": item.cited_by_count,
                "interests": item.interests,
                "profile_url": item.profile_url,
                "profile_image_url": item.profile_image_url,
            }
            for item in parsed.candidates
        ],
        "warnings": parsed.warnings,
    }


async def read_uploaded_image(image: UploadFile) -> bytes:
    try:
        return await image.read()
    finally:
        await image.close()


async def require_user_profile(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=user_id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )
    return profile

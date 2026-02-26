from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.runtime_deps import get_scholar_source
from app.api.schemas import (
    DataExportEnvelope,
    DataImportEnvelope,
    DataImportRequest,
    MessageEnvelope,
    ScholarCreateRequest,
    ScholarEnvelope,
    ScholarImageUrlUpdateRequest,
    ScholarSearchEnvelope,
    ScholarsListEnvelope,
)
from app.db.models import User
from app.db.session import get_db_session
from app.logging_utils import structured_log
from app.services.domains.ingestion import queue as ingestion_queue_service
from app.services.domains.portability import application as import_export_service
from app.services.domains.scholar import rate_limit as scholar_rate_limit
from app.services.domains.scholars import application as scholar_service
from app.services.domains.scholar.source import ScholarSource
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scholars", tags=["api-scholars"])
CREATE_METADATA_HYDRATION_TIMEOUT_SECONDS = 5.0
INITIAL_SCHOLAR_SCRAPE_QUEUE_DELAY_SECONDS = 0
INITIAL_SCHOLAR_SCRAPE_QUEUE_REASON = "scholar_added_initial_scrape"


def _needs_metadata_hydration(profile) -> bool:
    if not profile.profile_image_url:
        return True
    return not (profile.display_name or "").strip()


def _is_create_hydration_rate_limited() -> tuple[bool, float]:
    remaining_seconds = scholar_rate_limit.remaining_scholar_slot_seconds(
        min_interval_seconds=float(settings.ingestion_min_request_delay_seconds),
    )
    return remaining_seconds > 0, remaining_seconds


def _auto_enqueue_new_scholar_enabled() -> bool:
    if not settings.scheduler_enabled:
        return False
    if not settings.ingestion_automation_allowed:
        return False
    return bool(settings.ingestion_continuation_queue_enabled)


async def _enqueue_initial_scrape_job_for_scholar(
    db_session: AsyncSession,
    *,
    profile,
    user_id: int,
) -> bool:
    if not _auto_enqueue_new_scholar_enabled():
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
            logger, "warning", "api.scholars.initial_scrape_enqueue_failed",
            user_id=user_id,
            scholar_profile_id=profile.id,
        )
        return False

    structured_log(
        logger, "info", "api.scholars.initial_scrape_enqueued",
        user_id=user_id,
        scholar_profile_id=profile.id,
        reason=INITIAL_SCHOLAR_SCRAPE_QUEUE_REASON,
    )
    return True


def _uploaded_image_media_path(scholar_profile_id: int) -> str:
    return f"/scholar-images/{scholar_profile_id}/upload"


def _serialize_scholar(profile) -> dict[str, object]:
    uploaded_image_url = None
    if profile.profile_image_upload_path:
        uploaded_image_url = _uploaded_image_media_path(int(profile.id))

    profile_image_url, profile_image_source = scholar_service.resolve_profile_image(
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
        "last_run_status": (
            profile.last_run_status.value if profile.last_run_status is not None else None
        ),
    }


async def _hydrate_scholar_metadata_if_needed(
    db_session: AsyncSession,
    *,
    profile,
    source: ScholarSource,
    user_id: int,
):
    if not _needs_metadata_hydration(profile):
        return profile

    should_skip, remaining_seconds = _is_create_hydration_rate_limited()
    if should_skip:
        structured_log(
            logger, "info", "api.scholars.create_metadata_hydration_skipped",
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
            logger, "info", "api.scholars.create_metadata_hydration_skipped",
            reason="create_timeout",
            user_id=user_id,
            scholar_profile_id=profile.id,
        )
    except Exception:
        structured_log(
            logger, "warning", "api.scholars.create_metadata_hydration_failed",
            user_id=user_id,
            scholar_profile_id=profile.id,
        )
    return profile


def _search_kwargs() -> dict[str, object]:
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
        "cooldown_rejection_alert_threshold": (
            settings.scholar_name_search_alert_cooldown_rejections_threshold
        ),
    }


def _search_response_data(query: str, parsed) -> dict[str, object]:
    return {
        "query": query.strip(),
        "state": parsed.state.value,
        "state_reason": parsed.state_reason,
        "action_hint": scholar_service.scrape_state_hint(
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


async def _read_uploaded_image(image: UploadFile) -> bytes:
    try:
        return await image.read()
    finally:
        await image.close()


async def _require_user_profile(
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


@router.get(
    "",
    response_model=ScholarsListEnvelope,
)
async def list_scholars(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    scholars = await scholar_service.list_scholars_for_user(
        db_session,
        user_id=current_user.id,
    )
    return success_payload(
        request,
        data={
            "scholars": [_serialize_scholar(profile) for profile in scholars],
        },
    )


@router.get(
    "/export",
    response_model=DataExportEnvelope,
)
async def export_scholars_and_publications(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    data = await import_export_service.export_user_data(
        db_session,
        user_id=current_user.id,
    )
    return success_payload(request, data=data)


@router.post(
    "/import",
    response_model=DataImportEnvelope,
)
async def import_scholars_and_publications(
    payload: DataImportRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    if (
        payload.schema_version is not None
        and int(payload.schema_version) != import_export_service.EXPORT_SCHEMA_VERSION
    ):
        raise ApiException(
            status_code=400,
            code="invalid_import_schema_version",
            message=(
                "Import schema version is not supported. "
                f"Expected {import_export_service.EXPORT_SCHEMA_VERSION}."
            ),
        )
    try:
        result = await import_export_service.import_user_data(
            db_session,
            user_id=current_user.id,
            scholars=[item.model_dump() for item in payload.scholars],
            publications=[item.model_dump() for item in payload.publications],
        )
    except import_export_service.ImportExportError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_import_payload",
            message=str(exc),
        ) from exc
    structured_log(logger, "info", "api.scholars.imported", user_id=current_user.id, **result)
    return success_payload(request, data=result)


@router.post(
    "",
    response_model=ScholarEnvelope,
    status_code=201,
)
async def create_scholar(
    payload: ScholarCreateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    source: ScholarSource = Depends(get_scholar_source),
    current_user: User = Depends(get_api_current_user),
):
    try:
        created = await scholar_service.create_scholar_for_user(
            db_session,
            user_id=current_user.id,
            scholar_id=payload.scholar_id,
            display_name="",
            profile_image_url=payload.profile_image_url,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar",
            message=str(exc),
        ) from exc
    structured_log(logger, "info", "api.scholars.created", user_id=current_user.id, scholar_profile_id=created.id)
    did_queue_initial_scrape = await _enqueue_initial_scrape_job_for_scholar(
        db_session,
        profile=created,
        user_id=current_user.id,
    )
    if not did_queue_initial_scrape:
        created = await _hydrate_scholar_metadata_if_needed(
            db_session,
            profile=created,
            source=source,
            user_id=current_user.id,
        )

    return success_payload(
        request,
        data=_serialize_scholar(created),
    )


@router.get(
    "/search",
    response_model=ScholarSearchEnvelope,
)
async def search_scholars(
    request: Request,
    query: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(10, ge=1, le=25),
    db_session: AsyncSession = Depends(get_db_session),
    source: ScholarSource = Depends(get_scholar_source),
    current_user: User = Depends(get_api_current_user),
):
    try:
        parsed = await scholar_service.search_author_candidates(
            source=source,
            db_session=db_session,
            query=query,
            limit=limit,
            **_search_kwargs(),
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar_search",
            message=str(exc),
        ) from exc

    structured_log(logger, "info", "api.scholars.search.completed", user_id=current_user.id, query=query.strip(), candidate_count=len(parsed.candidates), state=parsed.state.value)
    return success_payload(
        request,
        data=_search_response_data(query, parsed),
    )


@router.patch(
    "/{scholar_profile_id}/toggle",
    response_model=ScholarEnvelope,
)
async def toggle_scholar(
    scholar_profile_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )
    updated = await scholar_service.toggle_scholar_enabled(db_session, profile=profile)
    structured_log(logger, "info", "api.scholars.toggled", user_id=current_user.id, scholar_profile_id=updated.id, is_enabled=updated.is_enabled)
    return success_payload(
        request,
        data=_serialize_scholar(updated),
    )


@router.delete(
    "/{scholar_profile_id}",
    response_model=MessageEnvelope,
)
async def delete_scholar(
    scholar_profile_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )
    await scholar_service.delete_scholar(
        db_session,
        profile=profile,
        upload_dir=settings.scholar_image_upload_dir,
    )
    structured_log(logger, "info", "api.scholars.deleted", user_id=current_user.id, scholar_profile_id=scholar_profile_id)
    return success_payload(
        request,
        data={"message": "Scholar deleted."},
    )


@router.put(
    "/{scholar_profile_id}/image/url",
    response_model=ScholarEnvelope,
)
async def update_scholar_image_url(
    scholar_profile_id: int,
    payload: ScholarImageUrlUpdateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )

    try:
        updated = await scholar_service.set_profile_image_override_url(
            db_session,
            profile=profile,
            image_url=payload.image_url,
            upload_dir=settings.scholar_image_upload_dir,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar_image",
            message=str(exc),
        ) from exc

    structured_log(logger, "info", "api.scholars.image_url_updated", user_id=current_user.id, scholar_profile_id=updated.id)
    return success_payload(
        request,
        data=_serialize_scholar(updated),
    )


@router.post(
    "/{scholar_profile_id}/image/upload",
    response_model=ScholarEnvelope,
)
async def upload_scholar_image(
    scholar_profile_id: int,
    request: Request,
    image: UploadFile = File(...),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await _require_user_profile(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )

    image_bytes = await _read_uploaded_image(image)
    try:
        updated = await scholar_service.set_profile_image_upload(
            db_session,
            profile=profile,
            content_type=image.content_type,
            image_bytes=image_bytes,
            upload_dir=settings.scholar_image_upload_dir,
            max_upload_bytes=settings.scholar_image_upload_max_bytes,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar_image",
            message=str(exc),
        ) from exc

    image_size = len(image_bytes)
    structured_log(logger, "info", "api.scholars.image_uploaded", user_id=current_user.id, scholar_profile_id=updated.id, content_type=image.content_type, size_bytes=image_size)
    return success_payload(
        request,
        data=_serialize_scholar(updated),
    )


@router.delete(
    "/{scholar_profile_id}/image",
    response_model=ScholarEnvelope,
)
async def clear_scholar_image_customization(
    scholar_profile_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )

    updated = await scholar_service.clear_profile_image_customization(
        db_session,
        profile=profile,
        upload_dir=settings.scholar_image_upload_dir,
    )
    structured_log(logger, "info", "api.scholars.image_customization_cleared", user_id=current_user.id, scholar_profile_id=updated.id)
    return success_payload(
        request,
        data=_serialize_scholar(updated),
    )

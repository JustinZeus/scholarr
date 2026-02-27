from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_api_admin_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    AdminScholarHttpSettingsEnvelope,
    AdminScholarHttpSettingsUpdateRequest,
)
from app.db.models import User
from app.logging_utils import structured_log
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/settings", tags=["api-admin-settings"])
_MAX_USER_AGENT_LENGTH = 512
_MAX_ACCEPT_LANGUAGE_LENGTH = 128
_MAX_COOKIE_LENGTH = 8192


def _normalize_header_value(value: str, *, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ApiException(
            status_code=400,
            code="invalid_admin_setting",
            message=f"{field_name} must be {max_length} characters or fewer.",
        )
    return normalized


def _serialize_scholar_http_settings() -> dict[str, object]:
    return {
        "user_agent": settings.scholar_http_user_agent,
        "rotate_user_agent": bool(settings.scholar_http_rotate_user_agent),
        "accept_language": settings.scholar_http_accept_language,
        "cookie": settings.scholar_http_cookie,
    }


def _apply_scholar_http_settings(payload: AdminScholarHttpSettingsUpdateRequest) -> None:
    user_agent = _normalize_header_value(
        payload.user_agent,
        field_name="user_agent",
        max_length=_MAX_USER_AGENT_LENGTH,
    )
    accept_language = _normalize_header_value(
        payload.accept_language,
        field_name="accept_language",
        max_length=_MAX_ACCEPT_LANGUAGE_LENGTH,
    )
    cookie = _normalize_header_value(
        payload.cookie,
        field_name="cookie",
        max_length=_MAX_COOKIE_LENGTH,
    )
    object.__setattr__(settings, "scholar_http_user_agent", user_agent)
    object.__setattr__(settings, "scholar_http_rotate_user_agent", bool(payload.rotate_user_agent))
    object.__setattr__(settings, "scholar_http_accept_language", accept_language)
    object.__setattr__(settings, "scholar_http_cookie", cookie)


@router.get(
    "/scholar-http",
    response_model=AdminScholarHttpSettingsEnvelope,
)
async def get_scholar_http_settings(
    request: Request,
    admin_user: User = Depends(get_api_admin_user),
):
    structured_log(
        logger,
        "info",
        "api.admin.settings.scholar_http_read",
        admin_user_id=int(admin_user.id),
    )
    return success_payload(request, data=_serialize_scholar_http_settings())


@router.put(
    "/scholar-http",
    response_model=AdminScholarHttpSettingsEnvelope,
)
async def update_scholar_http_settings(
    payload: AdminScholarHttpSettingsUpdateRequest,
    request: Request,
    admin_user: User = Depends(get_api_admin_user),
):
    _apply_scholar_http_settings(payload)
    structured_log(
        logger,
        "info",
        "api.admin.settings.scholar_http_updated",
        admin_user_id=int(admin_user.id),
        rotate_user_agent=bool(settings.scholar_http_rotate_user_agent),
        user_agent_set=bool(settings.scholar_http_user_agent.strip()),
        cookie_set=bool(settings.scholar_http_cookie.strip()),
    )
    return success_payload(request, data=_serialize_scholar_http_settings())

from __future__ import annotations

import re
from typing import Any

from app.api.errors import ApiException
from app.services.runs import application as run_service

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_MAX_LENGTH = 128
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_idempotency_key(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    candidate = raw_value.strip()
    if not candidate:
        return None
    if len(candidate) > IDEMPOTENCY_MAX_LENGTH or not IDEMPOTENCY_PATTERN.match(candidate):
        raise ApiException(
            status_code=400,
            code="invalid_idempotency_key",
            message=("Invalid Idempotency-Key. Use 8-128 characters from: A-Z a-z 0-9 . _ : -"),
        )
    return candidate


def serialize_run(run) -> dict[str, Any]:
    summary = run_service.extract_run_summary(run.error_log)
    return {
        "id": int(run.id),
        "trigger_type": run.trigger_type.value,
        "status": run.status.value,
        "start_dt": run.start_dt,
        "end_dt": run.end_dt,
        "scholar_count": int(run.scholar_count or 0),
        "new_publication_count": int(run.new_pub_count or 0),
        "failed_count": int(summary["failed_count"]),
        "partial_count": int(summary["partial_count"]),
    }


def serialize_queue_item(item) -> dict[str, Any]:
    return {
        "id": int(item.id),
        "scholar_profile_id": int(item.scholar_profile_id),
        "scholar_label": item.scholar_label,
        "status": item.status,
        "reason": item.reason,
        "dropped_reason": item.dropped_reason,
        "attempt_count": int(item.attempt_count),
        "resume_cstart": int(item.resume_cstart),
        "next_attempt_dt": item.next_attempt_dt,
        "updated_at": item.updated_at,
        "last_error": item.last_error,
        "last_run_id": item.last_run_id,
    }


def _normalize_attempt_log(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "attempt": _int_value(item.get("attempt"), 0),
                "cstart": _int_value(item.get("cstart"), 0),
                "state": _str_value(item.get("state")),
                "state_reason": _str_value(item.get("state_reason")),
                "status_code": (_int_value(item.get("status_code")) if item.get("status_code") is not None else None),
                "fetch_error": _str_value(item.get("fetch_error")),
            }
        )
    return normalized


def _normalize_page_logs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        warning_codes = item.get("warning_codes")
        normalized.append(
            {
                "page": _int_value(item.get("page"), 0),
                "cstart": _int_value(item.get("cstart"), 0),
                "state": _str_value(item.get("state")) or "unknown",
                "state_reason": _str_value(item.get("state_reason")),
                "status_code": (_int_value(item.get("status_code")) if item.get("status_code") is not None else None),
                "publication_count": _int_value(item.get("publication_count"), 0),
                "attempt_count": _int_value(item.get("attempt_count"), 0),
                "has_show_more_button": _bool_value(item.get("has_show_more_button"), False),
                "articles_range": _str_value(item.get("articles_range")),
                "warning_codes": [str(code) for code in (warning_codes if isinstance(warning_codes, list) else [])],
            }
        )
    return normalized


def _normalize_debug(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    marker_counts = value.get("marker_counts_nonzero")
    warning_codes = value.get("warning_codes")
    return {
        "status_code": (_int_value(value.get("status_code")) if value.get("status_code") is not None else None),
        "final_url": _str_value(value.get("final_url")),
        "fetch_error": _str_value(value.get("fetch_error")),
        "body_sha256": _str_value(value.get("body_sha256")),
        "body_length": (_int_value(value.get("body_length")) if value.get("body_length") is not None else None),
        "has_show_more_button": (
            _bool_value(value.get("has_show_more_button"), False)
            if value.get("has_show_more_button") is not None
            else None
        ),
        "articles_range": _str_value(value.get("articles_range")),
        "state_reason": _str_value(value.get("state_reason")),
        "warning_codes": [str(code) for code in (warning_codes if isinstance(warning_codes, list) else [])],
        "marker_counts_nonzero": {
            str(key): _int_value(count, 0)
            for key, count in (marker_counts.items() if isinstance(marker_counts, dict) else [])
        },
        "page_logs": _normalize_page_logs(value.get("page_logs")),
        "attempt_log": _normalize_attempt_log(value.get("attempt_log")),
    }


def normalize_scholar_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "scholar_profile_id": 0,
            "scholar_id": "unknown",
            "state": "unknown",
            "state_reason": None,
            "outcome": "failed",
            "attempt_count": 0,
            "publication_count": 0,
            "start_cstart": 0,
            "continuation_cstart": None,
            "continuation_enqueued": False,
            "continuation_cleared": False,
            "warnings": [],
            "error": None,
            "debug": None,
        }
    warnings = value.get("warnings")
    return {
        "scholar_profile_id": _int_value(value.get("scholar_profile_id"), 0),
        "scholar_id": _str_value(value.get("scholar_id")) or "unknown",
        "state": _str_value(value.get("state")) or "unknown",
        "state_reason": _str_value(value.get("state_reason")),
        "outcome": _str_value(value.get("outcome")) or "failed",
        "attempt_count": _int_value(value.get("attempt_count"), 0),
        "publication_count": _int_value(value.get("publication_count"), 0),
        "start_cstart": _int_value(value.get("start_cstart"), 0),
        "continuation_cstart": (
            _int_value(value.get("continuation_cstart")) if value.get("continuation_cstart") is not None else None
        ),
        "continuation_enqueued": _bool_value(value.get("continuation_enqueued"), False),
        "continuation_cleared": _bool_value(value.get("continuation_cleared"), False),
        "warnings": [str(item) for item in (warnings if isinstance(warnings, list) else [])],
        "error": _str_value(value.get("error")),
        "debug": _normalize_debug(value.get("debug")),
    }


def manual_run_payload_from_run(
    run,
    *,
    idempotency_key: str | None,
    reused_existing_run: bool,
    safety_state: dict[str, Any],
) -> dict[str, Any]:
    summary = run_service.extract_run_summary(run.error_log)
    return {
        "run_id": int(run.id),
        "status": run.status.value,
        "scholar_count": int(run.scholar_count or 0),
        "succeeded_count": int(summary["succeeded_count"]),
        "failed_count": int(summary["failed_count"]),
        "partial_count": int(summary["partial_count"]),
        "new_publication_count": int(run.new_pub_count or 0),
        "reused_existing_run": reused_existing_run,
        "idempotency_key": idempotency_key,
        "safety_state": safety_state,
    }


def manual_run_success_payload(
    *,
    run_summary,
    idempotency_key: str | None,
    safety_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_summary.crawl_run_id,
        "status": run_summary.status.value,
        "scholar_count": run_summary.scholar_count,
        "succeeded_count": run_summary.succeeded_count,
        "failed_count": run_summary.failed_count,
        "partial_count": run_summary.partial_count,
        "new_publication_count": run_summary.new_publication_count,
        "reused_existing_run": False,
        "idempotency_key": idempotency_key,
        "safety_state": safety_state,
    }

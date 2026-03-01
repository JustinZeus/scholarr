from __future__ import annotations

import logging
from dataclasses import dataclass

from app.logging_utils import structured_log
from app.services.scholar.source import FetchResult, ScholarSource
from app.services.scholar.state_detection import (
    classify_block_or_captcha_reason,
    is_hard_challenge_reason,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    block_reason: str | None
    status_code: int | None


def _evaluate_fetch_result(fetch_result: FetchResult) -> PreflightResult:
    if fetch_result.status_code is None:
        return PreflightResult(passed=True, block_reason=None, status_code=None)
    block_reason = classify_block_or_captcha_reason(
        status_code=fetch_result.status_code,
        final_url=(fetch_result.final_url or "").lower(),
        body_lowered=fetch_result.body.lower(),
    )
    if block_reason is not None and is_hard_challenge_reason(block_reason):
        return PreflightResult(
            passed=False,
            block_reason=block_reason,
            status_code=fetch_result.status_code,
        )
    return PreflightResult(
        passed=True,
        block_reason=None,
        status_code=fetch_result.status_code,
    )


async def check_scholar_reachable(
    source: ScholarSource,
    *,
    scholar_id: str,
) -> PreflightResult:
    """Single-request probe to detect active Scholar blocks before a full run."""
    structured_log(logger, "info", "ingestion.preflight_started", scholar_id=scholar_id)
    fetch_result = await source.fetch_profile_html(scholar_id)
    result = _evaluate_fetch_result(fetch_result)
    if result.passed:
        structured_log(
            logger,
            "info",
            "ingestion.preflight_passed",
            scholar_id=scholar_id,
            status_code=result.status_code,
        )
    else:
        structured_log(
            logger,
            "warning",
            "ingestion.preflight_failed",
            scholar_id=scholar_id,
            block_reason=result.block_reason,
            status_code=result.status_code,
        )
    return result

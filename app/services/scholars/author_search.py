from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthorSearchRuntimeState
from app.logging_utils import structured_log
from app.services.scholar.parser import (
    ParsedAuthorSearchPage,
    ParseState,
    ScholarParserError,
    parse_author_search_page,
)
from app.services.scholar.source import ScholarSource
from app.services.scholars.author_search_cache import (
    cache_get_author_search_result,
    cache_set_author_search_result,
)
from app.services.scholars.constants import (
    AUTHOR_SEARCH_LOCK_KEY,
    AUTHOR_SEARCH_LOCK_NAMESPACE,
    AUTHOR_SEARCH_RUNTIME_STATE_KEY,
    DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS,
    DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES,
    DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD,
    DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD,
    DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS,
    DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS,
    DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS,
    DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD,
    MAX_AUTHOR_SEARCH_LIMIT,
    SEARCH_CACHED_BLOCK_REASON,
    SEARCH_COOLDOWN_REASON,
    SEARCH_DISABLED_REASON,
)
from app.services.scholars.exceptions import ScholarServiceError
from app.services.scholars.search_hints import (
    _merge_warnings,
    _policy_blocked_author_search_result,
    _trim_author_search_result,
)

logger = logging.getLogger(__name__)


async def _acquire_author_search_lock(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
        {
            "namespace": AUTHOR_SEARCH_LOCK_NAMESPACE,
            "lock_key": AUTHOR_SEARCH_LOCK_KEY,
        },
    )


async def _load_runtime_state_for_update(
    db_session: AsyncSession,
) -> AuthorSearchRuntimeState:
    result = await db_session.execute(
        select(AuthorSearchRuntimeState)
        .where(AuthorSearchRuntimeState.state_key == AUTHOR_SEARCH_RUNTIME_STATE_KEY)
        .with_for_update()
    )
    state = result.scalar_one_or_none()
    if state is not None:
        return state

    state = AuthorSearchRuntimeState(state_key=AUTHOR_SEARCH_RUNTIME_STATE_KEY)
    db_session.add(state)
    await db_session.flush()
    return state


def _is_author_search_block_state(parsed: ParsedAuthorSearchPage) -> bool:
    return parsed.state == ParseState.BLOCKED_OR_CAPTCHA


def _author_search_cooldown_remaining_seconds(
    runtime_state: AuthorSearchRuntimeState,
    now_utc: datetime,
) -> int:
    cooldown_until = runtime_state.cooldown_until
    if cooldown_until is None:
        return 0
    if cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=UTC)
    remaining_seconds = int((cooldown_until - now_utc).total_seconds())
    return max(0, remaining_seconds)


def _normalize_author_search_inputs(query: str, limit: int) -> tuple[str, int, str]:
    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise ScholarServiceError("Search query must be at least 2 characters.")
    bounded_limit = max(1, min(int(limit), MAX_AUTHOR_SEARCH_LIMIT))
    return normalized_query, bounded_limit, normalized_query.casefold()


def _disabled_search_result(*, normalized_query: str, bounded_limit: int) -> ParsedAuthorSearchPage:
    structured_log(
        logger,
        "warning",
        "scholar_search.disabled_by_configuration",
        query=normalized_query,
    )
    return _policy_blocked_author_search_result(
        reason=SEARCH_DISABLED_REASON,
        warning_codes=["author_search_disabled_by_configuration"],
        limit=bounded_limit,
    )


def _normalize_runtime_cooldown_state(
    runtime_state: AuthorSearchRuntimeState,
    *,
    now_utc: datetime,
) -> bool:
    if runtime_state.cooldown_until is None:
        return False
    cooldown_until = runtime_state.cooldown_until
    updated = False
    if cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=UTC)
        runtime_state.cooldown_until = cooldown_until
        updated = True
    if now_utc < cooldown_until:
        return updated
    structured_log(
        logger,
        "info",
        "scholar_search.cooldown_expired",
        cooldown_until_utc=cooldown_until.isoformat(),
    )
    runtime_state.cooldown_until = None
    runtime_state.cooldown_rejection_count = 0
    runtime_state.cooldown_alert_emitted = False
    return True


def _cooldown_warning_codes(
    *,
    runtime_state: AuthorSearchRuntimeState,
    cooldown_remaining_seconds: int,
) -> list[str]:
    warning_codes = [
        "author_search_cooldown_active",
        f"author_search_cooldown_remaining_{cooldown_remaining_seconds}s",
    ]
    if bool(runtime_state.cooldown_alert_emitted):
        warning_codes.append("author_search_cooldown_alert_threshold_exceeded")
    return warning_codes


def _emit_cooldown_threshold_alert(
    *,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    cooldown_rejection_alert_threshold: int,
) -> bool:
    runtime_state.cooldown_rejection_count = int(runtime_state.cooldown_rejection_count) + 1
    threshold = max(1, int(cooldown_rejection_alert_threshold))
    if int(runtime_state.cooldown_rejection_count) < threshold:
        return True
    if bool(runtime_state.cooldown_alert_emitted):
        return True
    structured_log(
        logger,
        "error",
        "scholar_search.cooldown_rejection_threshold_exceeded",
        query=normalized_query,
        cooldown_rejection_count=int(runtime_state.cooldown_rejection_count),
        threshold=threshold,
        cooldown_until_utc=runtime_state.cooldown_until.isoformat() if runtime_state.cooldown_until else None,
    )
    runtime_state.cooldown_alert_emitted = True
    return True


def _cooldown_block_result(
    *,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    bounded_limit: int,
    cooldown_rejection_alert_threshold: int,
    cooldown_remaining_seconds: int,
) -> ParsedAuthorSearchPage:
    _emit_cooldown_threshold_alert(
        runtime_state=runtime_state,
        normalized_query=normalized_query,
        cooldown_rejection_alert_threshold=cooldown_rejection_alert_threshold,
    )
    structured_log(
        logger,
        "warning",
        "scholar_search.cooldown_active",
        query=normalized_query,
        cooldown_remaining_seconds=cooldown_remaining_seconds,
        cooldown_until_utc=runtime_state.cooldown_until.isoformat() if runtime_state.cooldown_until else None,
    )
    return _policy_blocked_author_search_result(
        reason=SEARCH_COOLDOWN_REASON,
        warning_codes=_cooldown_warning_codes(
            runtime_state=runtime_state,
            cooldown_remaining_seconds=cooldown_remaining_seconds,
        ),
        limit=bounded_limit,
    )


async def _cache_hit_result(
    db_session: AsyncSession,
    *,
    query_key: str,
    now_utc: datetime,
    normalized_query: str,
    bounded_limit: int,
) -> ParsedAuthorSearchPage | None:
    cached = await cache_get_author_search_result(
        db_session,
        query_key=query_key,
        now_utc=now_utc,
    )
    if cached is None:
        return None
    structured_log(
        logger,
        "info",
        "scholar_search.cache_hit",
        query=normalized_query,
        state=cached.state.value,
        state_reason=cached.state_reason,
    )
    state_reason_override = SEARCH_CACHED_BLOCK_REASON if _is_author_search_block_state(cached) else None
    return _trim_author_search_result(
        cached,
        limit=bounded_limit,
        extra_warnings=["author_search_served_from_cache"],
        state_reason_override=state_reason_override,
    )


def _throttle_sleep_seconds(
    *,
    runtime_state: AuthorSearchRuntimeState,
    now_utc: datetime,
    min_interval_seconds: float,
    interval_jitter_seconds: float,
) -> tuple[float, bool]:
    updated = False
    if runtime_state.last_live_request_at is None:
        enforced_wait_seconds = 0.0
    else:
        last_live_request_at = runtime_state.last_live_request_at
        if last_live_request_at.tzinfo is None:
            last_live_request_at = last_live_request_at.replace(tzinfo=UTC)
            runtime_state.last_live_request_at = last_live_request_at
            updated = True
        enforced_wait_seconds = (
            last_live_request_at + timedelta(seconds=max(float(min_interval_seconds), 0.0)) - now_utc
        ).total_seconds()
    jitter_seconds = random.uniform(0.0, max(float(interval_jitter_seconds), 0.0))
    return max(0.0, float(enforced_wait_seconds)) + jitter_seconds, updated


async def _wait_for_author_search_throttle(
    *,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    now_utc: datetime,
    min_interval_seconds: float,
    interval_jitter_seconds: float,
) -> bool:
    sleep_seconds, updated = _throttle_sleep_seconds(
        runtime_state=runtime_state,
        now_utc=now_utc,
        min_interval_seconds=min_interval_seconds,
        interval_jitter_seconds=interval_jitter_seconds,
    )
    if sleep_seconds <= 0.0:
        return updated
    structured_log(
        logger,
        "info",
        "scholar_search.throttle_wait",
        query=normalized_query,
        sleep_seconds=round(sleep_seconds, 3),
    )
    await asyncio.sleep(sleep_seconds)
    return True


async def _fetch_author_search_with_retries(
    *,
    source: ScholarSource,
    normalized_query: str,
    network_error_retries: int,
    retry_backoff_seconds: float,
) -> tuple[ParsedAuthorSearchPage, int, list[str]]:
    max_attempts = max(1, int(network_error_retries) + 1)
    parsed: ParsedAuthorSearchPage | None = None
    retry_warnings: list[str] = []
    retry_scheduled_count = 0
    for attempt_index in range(max_attempts):
        fetch_result = await source.fetch_author_search_html(normalized_query, start=0)
        try:
            parsed = parse_author_search_page(fetch_result)
        except ScholarParserError as exc:
            parsed = ParsedAuthorSearchPage(
                state=ParseState.LAYOUT_CHANGED,
                state_reason=exc.code,
                candidates=[],
                marker_counts={},
                warnings=[exc.code],
            )
        if parsed.state != ParseState.NETWORK_ERROR or attempt_index >= max_attempts - 1:
            break
        retry_warnings.append("network_retry_scheduled_for_author_search")
        retry_scheduled_count += 1
        retry_sleep_seconds = max(float(retry_backoff_seconds), 0.0) * (2**attempt_index)
        if retry_sleep_seconds > 0:
            await asyncio.sleep(retry_sleep_seconds)
    if parsed is None:
        raise ScholarServiceError("Unable to complete scholar author search.")
    return parsed, retry_scheduled_count, retry_warnings


def _with_retry_warnings(
    parsed: ParsedAuthorSearchPage,
    *,
    retry_warnings: list[str],
    retry_scheduled_count: int,
    retry_alert_threshold: int,
    normalized_query: str,
) -> ParsedAuthorSearchPage:
    merged = replace(parsed, warnings=_merge_warnings(parsed.warnings, retry_warnings))
    threshold = max(1, int(retry_alert_threshold))
    if retry_scheduled_count < threshold:
        return merged
    structured_log(
        logger,
        "warning",
        "scholar_search.retry_threshold_exceeded",
        query=normalized_query,
        retry_scheduled_count=retry_scheduled_count,
        threshold=threshold,
        final_state=merged.state.value,
        final_state_reason=merged.state_reason,
    )
    return replace(
        merged,
        warnings=_merge_warnings(
            merged.warnings,
            [f"author_search_retry_threshold_exceeded_{retry_scheduled_count}"],
        ),
    )


def _apply_block_circuit_breaker(
    *,
    runtime_state: AuthorSearchRuntimeState,
    merged_parsed: ParsedAuthorSearchPage,
    cooldown_block_threshold: int,
    cooldown_seconds: int,
    normalized_query: str,
) -> ParsedAuthorSearchPage:
    if not _is_author_search_block_state(merged_parsed):
        runtime_state.consecutive_blocked_count = 0
        return merged_parsed
    runtime_state.consecutive_blocked_count = int(runtime_state.consecutive_blocked_count) + 1
    structured_log(
        logger,
        "warning",
        "scholar_search.block_detected",
        query=normalized_query,
        state_reason=merged_parsed.state_reason,
        consecutive_blocked_count=int(runtime_state.consecutive_blocked_count),
    )
    if int(runtime_state.consecutive_blocked_count) < max(1, int(cooldown_block_threshold)):
        return merged_parsed
    runtime_state.cooldown_until = datetime.now(UTC) + timedelta(seconds=max(60, int(cooldown_seconds)))
    runtime_state.consecutive_blocked_count = 0
    runtime_state.cooldown_rejection_count = 0
    runtime_state.cooldown_alert_emitted = False
    structured_log(
        logger,
        "error",
        "scholar_search.cooldown_activated",
        query=normalized_query,
        cooldown_until_utc=runtime_state.cooldown_until.isoformat() if runtime_state.cooldown_until else None,
    )
    return replace(
        merged_parsed,
        warnings=_merge_warnings(merged_parsed.warnings, ["author_search_circuit_breaker_armed"]),
    )


def _resolve_author_search_cache_ttl_seconds(
    *,
    merged_parsed: ParsedAuthorSearchPage,
    blocked_cache_ttl_seconds: int,
    cache_ttl_seconds: int,
) -> int:
    if _is_author_search_block_state(merged_parsed):
        return min(max(1, int(blocked_cache_ttl_seconds)), max(1, int(cache_ttl_seconds)))
    return max(1, int(cache_ttl_seconds))


async def _load_locked_runtime_state(
    db_session: AsyncSession,
) -> AuthorSearchRuntimeState:
    await _acquire_author_search_lock(db_session)
    return await _load_runtime_state_for_update(db_session)


async def _cooldown_or_cache_result(
    db_session: AsyncSession,
    *,
    runtime_state: AuthorSearchRuntimeState,
    query_key: str,
    normalized_query: str,
    bounded_limit: int,
    cooldown_rejection_alert_threshold: int,
) -> tuple[ParsedAuthorSearchPage | None, bool]:
    runtime_state_updated = _normalize_runtime_cooldown_state(
        runtime_state,
        now_utc=datetime.now(UTC),
    )
    cooldown_remaining_seconds = _author_search_cooldown_remaining_seconds(
        runtime_state,
        datetime.now(UTC),
    )
    if cooldown_remaining_seconds > 0:
        return (
            _cooldown_block_result(
                runtime_state=runtime_state,
                normalized_query=normalized_query,
                bounded_limit=bounded_limit,
                cooldown_rejection_alert_threshold=cooldown_rejection_alert_threshold,
                cooldown_remaining_seconds=cooldown_remaining_seconds,
            ),
            True,
        )
    cached_result = await _cache_hit_result(
        db_session,
        query_key=query_key,
        now_utc=datetime.now(UTC),
        normalized_query=normalized_query,
        bounded_limit=bounded_limit,
    )
    return cached_result, runtime_state_updated


async def _perform_live_author_search(
    db_session: AsyncSession,
    *,
    source: ScholarSource,
    runtime_state: AuthorSearchRuntimeState,
    normalized_query: str,
    query_key: str,
    network_error_retries: int,
    retry_backoff_seconds: float,
    min_interval_seconds: float,
    interval_jitter_seconds: float,
    retry_alert_threshold: int,
    cooldown_block_threshold: int,
    cooldown_seconds: int,
    blocked_cache_ttl_seconds: int,
    cache_ttl_seconds: int,
    cache_max_entries: int,
) -> tuple[ParsedAuthorSearchPage, bool]:
    await _wait_for_author_search_throttle(
        runtime_state=runtime_state,
        normalized_query=normalized_query,
        now_utc=datetime.now(UTC),
        min_interval_seconds=min_interval_seconds,
        interval_jitter_seconds=interval_jitter_seconds,
    )
    parsed, retry_count, retry_warnings = await _fetch_author_search_with_retries(
        source=source,
        normalized_query=normalized_query,
        network_error_retries=network_error_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    runtime_state.last_live_request_at = datetime.now(UTC)
    merged = _with_retry_warnings(
        parsed,
        retry_warnings=retry_warnings,
        retry_scheduled_count=retry_count,
        retry_alert_threshold=retry_alert_threshold,
        normalized_query=normalized_query,
    )
    merged = _apply_block_circuit_breaker(
        runtime_state=runtime_state,
        merged_parsed=merged,
        cooldown_block_threshold=cooldown_block_threshold,
        cooldown_seconds=cooldown_seconds,
        normalized_query=normalized_query,
    )
    ttl_seconds = _resolve_author_search_cache_ttl_seconds(
        merged_parsed=merged,
        blocked_cache_ttl_seconds=blocked_cache_ttl_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    await cache_set_author_search_result(
        db_session,
        query_key=query_key,
        parsed=merged,
        ttl_seconds=float(ttl_seconds),
        max_entries=cache_max_entries,
        now_utc=datetime.now(UTC),
    )
    return merged, True


async def search_author_candidates(
    *,
    source: ScholarSource,
    db_session: AsyncSession,
    query: str,
    limit: int,
    network_error_retries: int = 1,
    retry_backoff_seconds: float = 1.0,
    search_enabled: bool = True,
    cache_ttl_seconds: int = 21_600,
    blocked_cache_ttl_seconds: int = DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS,
    cache_max_entries: int = DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES,
    min_interval_seconds: float = DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS,
    interval_jitter_seconds: float = DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS,
    cooldown_block_threshold: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD,
    cooldown_seconds: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS,
    retry_alert_threshold: int = DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD,
    cooldown_rejection_alert_threshold: int = DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD,
) -> ParsedAuthorSearchPage:
    normalized_query, bounded_limit, query_key = _normalize_author_search_inputs(query, limit)
    if not search_enabled:
        return _disabled_search_result(
            normalized_query=normalized_query,
            bounded_limit=bounded_limit,
        )

    runtime_state = await _load_locked_runtime_state(db_session)
    early_result, runtime_state_updated = await _cooldown_or_cache_result(
        db_session,
        runtime_state=runtime_state,
        query_key=query_key,
        normalized_query=normalized_query,
        bounded_limit=bounded_limit,
        cooldown_rejection_alert_threshold=cooldown_rejection_alert_threshold,
    )
    if early_result is not None:
        await db_session.commit()
        return early_result

    merged_parsed, live_runtime_updated = await _perform_live_author_search(
        db_session,
        source=source,
        runtime_state=runtime_state,
        normalized_query=normalized_query,
        query_key=query_key,
        network_error_retries=network_error_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        min_interval_seconds=min_interval_seconds,
        interval_jitter_seconds=interval_jitter_seconds,
        retry_alert_threshold=retry_alert_threshold,
        cooldown_block_threshold=cooldown_block_threshold,
        cooldown_seconds=cooldown_seconds,
        blocked_cache_ttl_seconds=blocked_cache_ttl_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
        cache_max_entries=cache_max_entries,
    )
    runtime_state_updated = runtime_state_updated or live_runtime_updated
    if runtime_state_updated:
        await db_session.commit()
    return _trim_author_search_result(merged_parsed, limit=bounded_limit)

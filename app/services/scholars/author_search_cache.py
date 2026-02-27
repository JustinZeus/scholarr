from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthorSearchCacheEntry
from app.services.scholar.parser import (
    ParsedAuthorSearchPage,
    ParseState,
    ScholarSearchCandidate,
)


def _serialize_parsed_author_search_page(parsed: ParsedAuthorSearchPage) -> dict:
    return {
        "state": parsed.state.value,
        "state_reason": parsed.state_reason,
        "marker_counts": {str(key): int(value) for key, value in parsed.marker_counts.items()},
        "warnings": [str(value) for value in parsed.warnings],
        "candidates": [
            {
                "scholar_id": candidate.scholar_id,
                "display_name": candidate.display_name,
                "affiliation": candidate.affiliation,
                "email_domain": candidate.email_domain,
                "cited_by_count": candidate.cited_by_count,
                "interests": [str(interest) for interest in candidate.interests],
                "profile_url": candidate.profile_url,
                "profile_image_url": candidate.profile_image_url,
            }
            for candidate in parsed.candidates
        ],
    }


def _payload_state(payload: dict[str, object]) -> ParseState | None:
    state_raw = str(payload.get("state", "")).strip()
    try:
        return ParseState(state_raw)
    except ValueError:
        return None


def _payload_marker_counts(payload: dict[str, object]) -> dict[str, int]:
    marker_counts_payload = payload.get("marker_counts")
    if not isinstance(marker_counts_payload, dict):
        return {}
    parsed: dict[str, int] = {}
    for key, value in marker_counts_payload.items():
        try:
            parsed[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return parsed


def _payload_warnings(payload: dict[str, object]) -> list[str]:
    warnings_payload = payload.get("warnings")
    if not isinstance(warnings_payload, list):
        return []
    return [str(value) for value in warnings_payload if isinstance(value, str)]


def _parse_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _normalize_interests(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _deserialize_candidate_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    scholar_id = str(value.get("scholar_id", "")).strip()
    display_name = str(value.get("display_name", "")).strip()
    profile_url = str(value.get("profile_url", "")).strip()
    if not scholar_id or not display_name or not profile_url:
        return None
    return {
        "scholar_id": scholar_id,
        "display_name": display_name,
        "affiliation": _parse_optional_string(value.get("affiliation")),
        "email_domain": _parse_optional_string(value.get("email_domain")),
        "cited_by_count": _parse_optional_int(value.get("cited_by_count")),
        "interests": _normalize_interests(value.get("interests")),
        "profile_url": profile_url,
        "profile_image_url": _parse_optional_string(value.get("profile_image_url")),
    }


def _deserialize_candidates(payload: dict[str, object]) -> list[dict[str, object]]:
    candidates_payload = payload.get("candidates")
    if not isinstance(candidates_payload, list):
        return []
    normalized: list[dict[str, object]] = []
    for value in candidates_payload:
        candidate = _deserialize_candidate_payload(value)
        if candidate is not None:
            normalized.append(candidate)
    return normalized


def _deserialize_parsed_author_search_page(payload: object) -> ParsedAuthorSearchPage | None:
    if not isinstance(payload, dict):
        return None

    state = _payload_state(payload)
    if state is None:
        return None

    marker_counts = _payload_marker_counts(payload)
    warnings = _payload_warnings(payload)
    normalized_candidates = _deserialize_candidates(payload)

    return ParsedAuthorSearchPage(
        state=state,
        state_reason=str(payload.get("state_reason", "")).strip() or "unknown",
        candidates=[
            ScholarSearchCandidate(
                scholar_id=item["scholar_id"],
                display_name=item["display_name"],
                affiliation=item["affiliation"],
                email_domain=item["email_domain"],
                cited_by_count=item["cited_by_count"],
                interests=item["interests"],
                profile_url=item["profile_url"],
                profile_image_url=item["profile_image_url"],
            )
            for item in normalized_candidates
        ],
        marker_counts=marker_counts,
        warnings=warnings,
    )


async def cache_get_author_search_result(
    db_session: AsyncSession,
    *,
    query_key: str,
    now_utc: datetime,
) -> ParsedAuthorSearchPage | None:
    result = await db_session.execute(
        select(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.query_key == query_key)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    expires_at = entry.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now_utc:
        await db_session.delete(entry)
        return None
    parsed = _deserialize_parsed_author_search_page(entry.payload)
    if parsed is None:
        await db_session.delete(entry)
        return None
    return parsed


async def cache_set_author_search_result(
    db_session: AsyncSession,
    *,
    query_key: str,
    parsed: ParsedAuthorSearchPage,
    ttl_seconds: float,
    max_entries: int,
    now_utc: datetime,
) -> None:
    ttl = max(float(ttl_seconds), 0.0)
    existing_result = await db_session.execute(
        select(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.query_key == query_key)
    )
    existing = existing_result.scalar_one_or_none()

    if ttl <= 0.0:
        if existing is not None:
            await db_session.delete(existing)
        return

    expires_at = now_utc + timedelta(seconds=ttl)
    payload = _serialize_parsed_author_search_page(parsed)
    if existing is None:
        db_session.add(
            AuthorSearchCacheEntry(
                query_key=query_key,
                payload=payload,
                expires_at=expires_at,
                cached_at=now_utc,
                updated_at=now_utc,
            )
        )
    else:
        existing.payload = payload
        existing.expires_at = expires_at
        existing.cached_at = now_utc
        existing.updated_at = now_utc

    await prune_author_search_cache(db_session, now_utc=now_utc, max_entries=max_entries)


async def prune_author_search_cache(
    db_session: AsyncSession,
    *,
    now_utc: datetime,
    max_entries: int,
) -> None:
    await db_session.execute(delete(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.expires_at <= now_utc))
    bounded_max_entries = max(1, int(max_entries))
    count_result = await db_session.execute(select(func.count()).select_from(AuthorSearchCacheEntry))
    entry_count = int(count_result.scalar_one() or 0)
    overflow = max(0, entry_count - bounded_max_entries)
    if overflow <= 0:
        return
    stale_keys_result = await db_session.execute(
        select(AuthorSearchCacheEntry.query_key).order_by(AuthorSearchCacheEntry.cached_at.asc()).limit(overflow)
    )
    stale_keys = [str(row[0]) for row in stale_keys_result.all()]
    if stale_keys:
        await db_session.execute(delete(AuthorSearchCacheEntry).where(AuthorSearchCacheEntry.query_key.in_(stale_keys)))

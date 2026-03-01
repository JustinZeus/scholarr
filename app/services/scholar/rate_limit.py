from __future__ import annotations

import asyncio
import time

_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


def _normalize_interval_seconds(value: float) -> float:
    return max(float(value), 0.0)


def remaining_scholar_slot_seconds(*, min_interval_seconds: float) -> float:
    interval_seconds = _normalize_interval_seconds(min_interval_seconds)
    if interval_seconds <= 0:
        return 0.0
    elapsed_seconds = time.monotonic() - _LAST_REQUEST_AT
    return max(interval_seconds - elapsed_seconds, 0.0)


async def wait_for_scholar_slot(*, min_interval_seconds: float) -> None:
    global _LAST_REQUEST_AT
    interval = _normalize_interval_seconds(min_interval_seconds)
    async with _REQUEST_LOCK:
        remaining = remaining_scholar_slot_seconds(min_interval_seconds=interval)
        if remaining > 0:
            await asyncio.sleep(remaining)
        _LAST_REQUEST_AT = time.monotonic()


def reset_scholar_rate_limit_state_for_tests() -> None:
    global _LAST_REQUEST_AT
    _LAST_REQUEST_AT = 0.0

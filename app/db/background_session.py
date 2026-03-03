"""Semaphore-gated DB sessions for background tasks.

Background tasks (ingestion, PDF resolution, scheduler) acquire a semaphore
permit before checking out a database connection.  The semaphore cap is
``pool_size + max_overflow - reserved_for_api``, which guarantees that at
least *reserved_for_api* connections remain available for API request
handlers at all times.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.logging_utils import structured_log
from app.settings import settings

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None


def _build_semaphore() -> asyncio.Semaphore:
    pool_capacity = max(1, settings.database_pool_size) + max(0, settings.database_pool_max_overflow)
    reserved = max(0, settings.database_reserved_api_connections)
    limit = max(1, pool_capacity - reserved)
    structured_log(
        logger,
        "info",
        "db.background_semaphore_initialized",
        pool_capacity=pool_capacity,
        reserved_for_api=reserved,
        background_limit=limit,
    )
    return asyncio.Semaphore(limit)


def get_background_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = _build_semaphore()
    return _semaphore


@asynccontextmanager
async def background_session() -> AsyncIterator[AsyncSession]:
    """Yield a DB session after acquiring the background semaphore."""
    semaphore = get_background_semaphore()
    async with semaphore:
        session_factory = get_session_factory()
        async with session_factory() as session:
            yield session

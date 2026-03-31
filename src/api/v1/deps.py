"""API key authentication and rate limiting dependencies."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.database import get_session
from src.models.api_key import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key")


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class RateLimiter:
    """In-memory sliding window rate limiter."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key_hash: str, limit: int, window: int = 60) -> None:
        """Raise 429 if limit exceeded within window (seconds)."""
        now = time.monotonic()
        timestamps = self._requests[key_hash]
        self._requests[key_hash] = [t for t in timestamps if now - t < window]
        timestamps = self._requests[key_hash]

        if len(timestamps) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(window)},
            )
        timestamps.append(now)


rate_limiter = RateLimiter()


async def get_api_key(
    key: Annotated[str, Security(api_key_header)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiKey:
    """Validate API key, check rate limit, update last_used_at."""
    key_hash = hash_api_key(key)
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    result = await session.execute(stmt)
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    rate_limiter.check(api_key.key_hash, api_key.rate_limit)

    api_key.last_used_at = datetime.now(UTC)
    await session.commit()

    return api_key

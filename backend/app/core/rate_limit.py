"""Fixed-window rate limiting on top of KV (doc 01 section 7.2)."""

from __future__ import annotations

import time

from app.config import get_settings
from app.core.errors import AppError
from app.core.kv import get_kv


async def hit(scope: str, ident: str, limit: int, window: int = 60) -> None:
    """Count one request; raises 429 with Retry-After/X-RateLimit-* when over the limit."""
    if not get_settings().rate_limit_enabled:
        return
    bucket = int(time.time() // window)
    key = f"rl:{scope}:{ident}:{bucket}"
    n = await get_kv().incr(key, window + 1)
    if n > limit:
        retry = window - int(time.time() % window)
        raise AppError(
            429,
            "RATE_LIMITED",
            "So'rovlar soni chegaradan oshdi, birozdan so'ng urinib ko'ring",
            {"retry_after": retry},
            headers={
                "Retry-After": str(retry),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + retry),
            },
        )

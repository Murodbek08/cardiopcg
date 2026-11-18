"""Run an async service function inside a Celery (sync) task with a fresh engine per invocation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import get_settings
from app.core.kv import close_kv, init_kv
from app.db.session import dispose_engine, init_engine
from app.services.storage import init_storage


def run_async(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    async def main() -> Any:
        s = get_settings()
        init_engine(s)
        init_kv(s.redis_url)
        init_storage(s)
        try:
            return await fn(*args)
        finally:
            await dispose_engine()
            await close_kv()

    return asyncio.run(main())

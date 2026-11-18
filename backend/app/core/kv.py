"""Tiny key-value abstraction: Redis in production, in-process fallback for dev/tests."""

from __future__ import annotations

import time
from typing import Protocol

from redis import asyncio as aioredis


class KV(Protocol):
    async def incr(self, key: str, ttl: int) -> int: ...
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    async def delete(self, *keys: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class MemoryKV:
    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float | None]] = {}

    def _alive(self, key: str) -> bool:
        item = self._d.get(key)
        if item is None:
            return False
        if item[1] is not None and item[1] <= time.monotonic():
            self._d.pop(key, None)
            return False
        return True

    async def incr(self, key: str, ttl: int) -> int:
        if self._alive(key):
            val, exp = self._d[key]
            n = int(val) + 1
            self._d[key] = (str(n), exp)
            return n
        self._d[key] = ("1", time.monotonic() + ttl)
        return 1

    async def get(self, key: str) -> str | None:
        return self._d[key][0] if self._alive(key) else None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._d[key] = (value, time.monotonic() + ttl if ttl else None)

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._d.pop(k, None)

    async def delete_prefix(self, prefix: str) -> None:
        for k in [k for k in self._d if k.startswith(prefix)]:
            self._d.pop(k, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class RedisKV:
    def __init__(self, client: aioredis.Redis) -> None:
        self.client = client

    async def incr(self, key: str, ttl: int) -> int:
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        n, _ = await pipe.execute()
        return int(n)

    async def get(self, key: str) -> str | None:
        v = await self.client.get(key)
        return v.decode() if isinstance(v, bytes) else v

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        await self.client.set(key, value, ex=ttl)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self.client.delete(*keys)

    async def delete_prefix(self, prefix: str) -> None:
        async for k in self.client.scan_iter(match=prefix + "*", count=200):
            await self.client.delete(k)

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.aclose()


_kv: KV | None = None
_redis: aioredis.Redis | None = None


def init_kv(redis_url: str) -> KV:
    global _kv, _redis
    if redis_url:
        _redis = aioredis.from_url(redis_url, decode_responses=False)
        _kv = RedisKV(_redis)
    else:
        _redis = None
        _kv = MemoryKV()
    return _kv


def get_kv() -> KV:
    global _kv
    if _kv is None:
        from app.config import get_settings

        init_kv(get_settings().redis_url)
    assert _kv is not None
    return _kv


def get_redis() -> aioredis.Redis | None:
    get_kv()
    return _redis


async def close_kv() -> None:
    global _kv, _redis
    if _kv is not None:
        await _kv.close()
    _kv = None
    _redis = None

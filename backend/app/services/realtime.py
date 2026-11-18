"""Realtime event bus: in-process fan-out, bridged across processes through Redis Pub/Sub.

Channels: ``user:{id}``, ``role:{role}``, ``exam:{id}``. Envelope per doc 01 section 6.
Per-exam history (last 100 events) is kept for SSE ``Last-Event-ID`` replay
(Redis Stream ``exam_events:{id}`` when Redis is configured, in-memory ring buffer otherwise).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.kv import get_redis
from app.db.base import new_id

log = structlog.get_logger()

_PUBSUB_CHANNEL = "cardiopcg:events"
_HISTORY_MAX = 100


def make_envelope(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "v": 1,
        "id": str(new_id()),
        "type": event_type,
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data": data,
    }


class Subscription:
    def __init__(self, channels: Iterable[str]) -> None:
        self.channels: set[str] = set(channels)
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    def offer(self, envelope: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(envelope)
        except asyncio.QueueFull:  # slow consumer: drop oldest
            with contextlib.suppress(Exception):
                self.queue.get_nowait()
                self.queue.put_nowait(envelope)


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._origin = uuid.uuid4().hex
        self._listener: asyncio.Task | None = None

    # ---- subscription management ----
    def subscribe(self, channels: Iterable[str]) -> Subscription:
        sub = Subscription(channels)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    # ---- publish ----
    def _deliver_local(self, channels: list[str], envelope: dict[str, Any]) -> None:
        chset = set(channels)
        for sub in list(self._subs):
            if sub.channels & chset:
                sub.offer(envelope)

    def _remember(self, channels: list[str], envelope: dict[str, Any]) -> None:
        for ch in channels:
            if ch.startswith("exam:"):
                dq = self._history.setdefault(ch, deque(maxlen=_HISTORY_MAX))
                dq.append(envelope)

    async def publish(self, event_type: str, data: dict[str, Any], channels: list[str]) -> dict[str, Any]:
        envelope = make_envelope(event_type, data)
        self._remember(channels, envelope)
        self._deliver_local(channels, envelope)
        redis = get_redis()
        if redis is not None:
            try:
                msg = orjson.dumps({"o": self._origin, "c": channels, "e": envelope})
                await redis.publish(_PUBSUB_CHANNEL, msg)
                for ch in channels:
                    if ch.startswith("exam:"):
                        key = f"exam_events:{ch[5:]}"
                        await redis.xadd(
                            key, {"e": orjson.dumps(envelope)}, maxlen=_HISTORY_MAX, approximate=False
                        )
                        await redis.expire(key, 3600)
            except Exception as exc:  # realtime must never break the request
                log.warning("realtime_publish_failed", error=str(exc))
        return envelope

    async def history(self, exam_id: str, after_id: str | None) -> list[dict[str, Any]]:
        redis = get_redis()
        items: list[dict[str, Any]] = []
        if redis is not None:
            try:
                for _, fields in await redis.xrange(f"exam_events:{exam_id}"):
                    raw = fields.get(b"e") or fields.get("e")
                    items.append(orjson.loads(raw))
            except Exception:
                items = []
        else:
            items = list(self._history.get(f"exam:{exam_id}", []))
        if after_id:
            for i, env in enumerate(items):
                if env["id"] == after_id:
                    return items[i + 1 :]
            return items  # unknown id: replay everything we still have
        return []

    # ---- Redis bridge ----
    async def start_listener(self) -> None:
        redis = get_redis()
        if redis is None or self._listener is not None:
            return
        self._listener = asyncio.create_task(self._listen(), name="event-bus-listener")

    async def _listen(self) -> None:
        redis = get_redis()
        assert redis is not None
        while True:
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe(_PUBSUB_CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    payload = orjson.loads(msg["data"])
                    if payload.get("o") == self._origin:
                        continue
                    self._remember(payload["c"], payload["e"])
                    self._deliver_local(payload["c"], payload["e"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("realtime_listener_error", error=str(exc))
                await asyncio.sleep(1)

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
            self._listener = None


bus = EventBus()


# ---- transactional outbox: events / jobs fire only after the DB transaction commits ----
def queue_event(db: AsyncSession, event_type: str, data: dict[str, Any], channels: list[str]) -> None:
    db.info.setdefault("pending_events", []).append((event_type, data, channels))


def after_commit(db: AsyncSession, fn) -> None:
    """Register an async callable to run after the transaction commits (e.g. dispatch a background job)."""
    db.info.setdefault("after_commit", []).append(fn)


async def flush_events(db: AsyncSession) -> None:
    pending = db.info.pop("pending_events", [])
    callbacks = db.info.pop("after_commit", [])
    for event_type, data, channels in pending:
        await bus.publish(event_type, data, channels)
    for fn in callbacks:
        try:
            await fn()
        except Exception as exc:  # never break the request after commit
            log.error("after_commit_failed", error=str(exc))


def drop_events(db: AsyncSession) -> None:
    db.info.pop("pending_events", None)
    db.info.pop("after_commit", None)

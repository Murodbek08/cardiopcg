"""WebSocket realtime channel (doc 01 section 6). Auth via ?token=<access_jwt> (query), refreshable in-band."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import defaultdict

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.errors import AppError
from app.core.permissions import has_permission  # noqa: F401
from app.db.session import get_sessionmaker
from app.models.enums import UserRole
from app.models.examination import Examination
from app.models.user import User
from app.services import realtime
from app.services.exam_service import can_view_exam

router = APIRouter(tags=["realtime"])

MAX_CONN_PER_USER = 5
_conns: dict[uuid.UUID, int] = defaultdict(int)


async def _auth(token: str) -> User:
    from app.core.deps import user_from_token

    async with get_sessionmaker()() as s:
        return await user_from_token(s, token)


async def _can_subscribe(user: User, channel: str) -> bool:
    kind, _, ident = channel.partition(":")
    if kind == "user":
        return ident == str(user.id)
    if kind == "role":
        return (ident == user.role.value and user.role != UserRole.nurse) or (
            ident == "doctor" and user.role == UserRole.admin
        )
    if kind == "exam":
        try:
            eid = uuid.UUID(ident)
        except ValueError:
            return False
        async with get_sessionmaker()() as s:
            exam = await s.get(Examination, eid)
            return exam is not None and exam.deleted_at is None and await can_view_exam(s, user, exam)
    return False


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str | None = None):
    if not token:
        await ws.close(code=4401)
        return
    try:
        user = await _auth(token)
    except AppError:
        await ws.close(code=4401)
        return
    except Exception:
        await ws.close(code=4401)
        return
    if _conns[user.id] >= MAX_CONN_PER_USER:
        await ws.close(code=4429)
        return
    _conns[user.id] += 1
    await ws.accept()
    channels = {f"user:{user.id}"}
    if user.role in (UserRole.doctor, UserRole.admin):
        channels.add(f"role:{user.role.value}")
    sub = realtime.bus.subscribe(channels)

    async def pump() -> None:
        while True:
            env = await sub.queue.get()
            await ws.send_text(orjson.dumps(env).decode())

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = orjson.loads(raw)
            except orjson.JSONDecodeError:
                await ws.send_text(orjson.dumps({"type": "error", "message": "invalid json"}).decode())
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                await ws.send_text(orjson.dumps({"type": "pong"}).decode())
            elif mtype == "auth":
                try:
                    new_user = await _auth(str(msg.get("token", "")))
                except AppError:
                    await ws.close(code=4401)
                    return
                if new_user.id != user.id:
                    await ws.close(code=4403)
                    return
            elif mtype == "subscribe":
                for ch in msg.get("channels", []):
                    if not await _can_subscribe(user, str(ch)):
                        await ws.close(code=4403)
                        return
                    sub.channels.add(str(ch))
                await ws.send_text(
                    orjson.dumps({"type": "subscribed", "channels": sorted(sub.channels)}).decode()
                )
            elif mtype == "unsubscribe":
                for ch in msg.get("channels", []):
                    sub.channels.discard(str(ch))
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump_task
        realtime.bus.unsubscribe(sub)
        _conns[user.id] = max(_conns[user.id] - 1, 0)

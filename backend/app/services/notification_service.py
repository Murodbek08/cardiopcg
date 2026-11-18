from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationType, UserRole, UserStatus
from app.models.system import Notification
from app.models.user import User
from app.services import realtime


def _out(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "type": n.type.value,
        "title": n.title,
        "body": n.body,
        "payload": n.payload,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


async def notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    type_: NotificationType,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    from app.db.base import utcnow

    n = Notification(
        user_id=user_id, type=type_, title=title[:160], body=body, payload=payload or {}, created_at=utcnow()
    )
    db.add(n)
    await db.flush()
    realtime.queue_event(db, "notification.new", _out(n), [f"user:{user_id}"])
    return n


async def notify_role(
    db: AsyncSession,
    role: UserRole,
    type_: NotificationType,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    ids = (
        (
            await db.execute(
                select(User.id).where(
                    User.role == role, User.status == UserStatus.active, User.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for uid in ids:
        await notify(db, uid, type_, title, body, payload)
    return len(ids)

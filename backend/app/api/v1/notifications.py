from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from sqlalchemy import delete, func, select, update

from app.core.deps import DB, CurrentUser
from app.core.errors import not_found
from app.core.pagination import clamp_limit, paginate, parse_sort, with_sort_columns
from app.core.route import TxRoute
from app.db.base import utcnow
from app.models.enums import NotificationType
from app.models.system import Notification
from app.schemas.common import ERROR_RESPONSES
from app.schemas.misc import NotificationOut, UnreadCount

router = APIRouter(
    prefix="/notifications", tags=["notifications"], route_class=TxRoute, responses=ERROR_RESPONSES
)


@router.get("")
async def list_notifications(
    db: DB,
    user: CurrentUser,
    is_read: bool | None = None,
    type: NotificationType | None = None,
    limit: int | None = None,
    cursor: str | None = None,
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read == is_read)
    if type:
        stmt = stmt.where(Notification.type == type)
    keys = parse_sort("-created_at", {"created_at": Notification.created_at}, "-created_at")
    stmt = with_sort_columns(stmt, keys, Notification.id)
    rows, page = await paginate(
        db, stmt, id_col=Notification.id, sort=keys, cursor=cursor, limit=clamp_limit(limit), with_total=False
    )
    return {"items": [NotificationOut.model_validate(r[0]) for r in rows], "page": page}


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(db: DB, user: CurrentUser):
    n = (
        await db.execute(
            select(func.count()).where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
    ).scalar_one()
    return {"count": n}


@router.post("/read-all", status_code=204)
async def read_all(db: DB, user: CurrentUser):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=utcnow())
    )
    return Response(status_code=204)


@router.post("/{nid}/read", status_code=204)
async def mark_read(nid: uuid.UUID, db: DB, user: CurrentUser):
    n = await db.get(Notification, nid)
    if n is None or n.user_id != user.id:
        raise not_found("Bildirishnoma")
    n.is_read, n.read_at = True, utcnow()
    return Response(status_code=204)


@router.delete("/{nid}", status_code=204)
async def delete_notification(nid: uuid.UUID, db: DB, user: CurrentUser):
    res = await db.execute(
        delete(Notification).where(Notification.id == nid, Notification.user_id == user.id)
    )
    if res.rowcount == 0:
        raise not_found("Bildirishnoma")
    return Response(status_code=204)

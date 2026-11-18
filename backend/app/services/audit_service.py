"""Audit log writer (append-only). Sensitive fields are masked in before/after diffs."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_request_info
from app.db.session import get_sessionmaker
from app.models.enums import AuditAction
from app.models.system import AuditLog

log = structlog.get_logger()

_SENSITIVE = {
    "password",
    "password_hash",
    "new_password",
    "current_password",
    "token",
    "token_hash",
    "access_token",
    "refresh_token",
    "national_id",
    "national_id_enc",
    "national_id_hash",
    "password_history",
}


def mask(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if k in _SENSITIVE else mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    return obj


def _jsonable(v: Any) -> Any:
    import datetime as dt
    from decimal import Decimal
    from enum import Enum

    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set):
        return [_jsonable(x) for x in v]
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dt.datetime | dt.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, bytes):
        return "<bytes>"
    return v


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return mask(_jsonable({"before": {k: before.get(k) for k in keys}, "after": {k: after[k] for k in keys}}))


def build_row(
    action: AuditAction,
    *,
    user: Any = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    success: bool = True,
    status_code: int | None = None,
    username: str | None = None,
) -> AuditLog:
    info = get_request_info()
    uname = getattr(user, "username", None) or username
    return AuditLog(
        user_id=getattr(user, "id", None),
        username_snapshot=str(uname)[:32] if uname else None,
        role_snapshot=getattr(user, "role", None),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        ip=info.ip,
        user_agent=(info.user_agent or "")[:300] or None,
        request_id=(info.request_id or "")[:40] or None,
        method=info.method,
        path=(info.path or "")[:300] or None,
        status_code=status_code,
        success=success,
        changes=_jsonable(mask(changes)) if changes else None,
        meta=_jsonable(meta or {}),
    )


def log_event(db: AsyncSession, action: AuditAction, **kw: Any) -> AuditLog:
    """Add an audit row to the caller's transaction (atomic with the operation)."""
    row = build_row(action, **kw)
    db.add(row)
    return row


async def log_standalone(action: AuditAction, **kw: Any) -> None:
    """Write an audit row in its own transaction (for failures that roll back the request)."""
    try:
        async with get_sessionmaker()() as s:
            s.add(build_row(action, **kw))
            await s.commit()
    except Exception as exc:  # pragma: no cover
        log.error("audit_write_failed", error=str(exc))

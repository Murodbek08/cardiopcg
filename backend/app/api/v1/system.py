from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text

from app.config import get_settings
from app.core import rate_limit
from app.core.deps import DB, CurrentUser, Perm
from app.core.errors import AppError
from app.core.kv import get_kv
from app.core.pagination import clamp_limit
from app.core.permissions import Permission, has_permission
from app.core.route import TxRoute
from app.db.base import utcnow
from app.models.enums import AuditAction, UserRole
from app.models.system import AuditLog, SystemSetting
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.services import audit_service, settings_service
from app.services.analysis_port import UnavailableAnalysisService, get_analysis_service
from app.services.storage import get_storage

router = APIRouter(tags=["system"], route_class=TxRoute, responses=ERROR_RESPONSES)

# ----------------------------------------------------------------------------------- settings


@router.get("/settings")
async def get_settings_all(db: DB, user: User = Perm(Permission.settings_write)):
    values = await settings_service.get_all(db)
    return {
        "items": [
            {
                "key": k,
                "value": values[k],
                "value_type": d.type,
                "description": d.description,
                "is_public": d.public,
                "min": d.min,
                "max": d.max,
            }
            for k, d in settings_service.SETTING_DEFS.items()
        ]
    }


@router.patch("/settings")
async def patch_settings(
    db: DB, user: User = Perm(Permission.settings_write), body: dict[str, Any] = Body(...)
):
    if not body:
        raise AppError(422, "VALIDATION_ERROR", "Bo'sh so'rov")
    clean = {k: settings_service.coerce(k, v) for k, v in body.items()}
    before: dict[str, Any] = {}
    for k, v in clean.items():
        d = settings_service.SETTING_DEFS[k]
        row = await db.get(SystemSetting, k)
        if row is None:
            before[k] = d.default
            db.add(
                SystemSetting(
                    key=k,
                    value=v,
                    value_type=d.type,
                    description=d.description,
                    is_public=d.public,
                    updated_by=user.id,
                )
            )
        else:
            before[k] = row.value
            row.value, row.updated_by, row.updated_at = v, user.id, utcnow()
    audit_service.log_event(
        db,
        AuditAction.settings_change,
        user=user,
        resource_type="settings",
        changes=audit_service.diff(before, clean),
    )
    await db.flush()
    return {"updated": clean}


@router.get("/settings/public")
async def public_settings(db: DB, user: CurrentUser):
    values = await settings_service.get_all(db)
    return {k: values[k] for k, d in settings_service.SETTING_DEFS.items() if d.public}


# ------------------------------------------------------------------------------------ health
@router.get("/system/health")
async def health():
    return {"status": "ok"}


@router.get("/system/health/deep")
async def health_deep(db: DB, user: User = Perm(Permission.settings_write)):
    checks: dict[str, Any] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    checks["redis"] = "ok" if await get_kv().ping() else "error"
    checks["storage"] = "ok" if await get_storage().ping() else "error"
    s = get_settings()
    checks["analysis_service"] = (
        "not_configured" if isinstance(get_analysis_service(), UnavailableAnalysisService) else "configured"
    )
    checks["deepseek_key"] = "configured" if s.deepseek_api_key else "missing"
    checks["clamav"] = "configured" if s.clamav_host else "not_configured"
    ok = all(v in ("ok", "configured", "not_configured") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks, "job_runner": s.job_runner}


@router.get("/system/version")
async def version(db: DB):
    s = get_settings()
    mv = await settings_service.get_value(db, "analysis.model_version")
    return {"version": s.app_version, "model_version": mv, "commit": s.git_commit}


# --------------------------------------------------------------------------------- audit logs
def _audit_filters(stmt, user: User, f: dict[str, Any]):
    if user.role == UserRole.doctor:
        stmt = stmt.where(AuditLog.user_id == user.id)  # doctors only see their own actions
    elif f.get("user_id"):
        stmt = stmt.where(AuditLog.user_id == f["user_id"])
    if f.get("action"):
        stmt = stmt.where(AuditLog.action == f["action"])
    if f.get("resource_type"):
        stmt = stmt.where(AuditLog.resource_type == f["resource_type"])
    if f.get("resource_id"):
        stmt = stmt.where(AuditLog.resource_id == f["resource_id"])
    if f.get("patient_id"):
        stmt = stmt.where(AuditLog.patient_id == f["patient_id"])
    if f.get("success") is not None:
        stmt = stmt.where(AuditLog.success == f["success"])
    if f.get("from_"):
        stmt = stmt.where(AuditLog.ts >= f["from_"])
    if f.get("to"):
        stmt = stmt.where(AuditLog.ts <= f["to"])
    if f.get("ip"):
        stmt = stmt.where(text("audit_logs.ip = CAST(:ip AS inet)").bindparams(ip=f["ip"]))
    if f.get("q"):
        stmt = stmt.where(AuditLog.path.ilike(f"%{f['q']}%"))
    return stmt


def _audit_item(r: AuditLog) -> dict[str, Any]:
    return {
        "id": r.id,
        "ts": r.ts,
        "user": {
            "id": r.user_id,
            "username": r.username_snapshot,
            "role": r.role_snapshot.value if r.role_snapshot else None,
        }
        if r.user_id or r.username_snapshot
        else None,
        "action": r.action.value,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "patient_id": r.patient_id,
        "ip": str(r.ip) if r.ip else None,
        "method": r.method,
        "path": r.path,
        "status_code": r.status_code,
        "success": r.success,
        "changes": r.changes,
        "meta": r.meta,
    }


@router.get("/audit-logs")
async def list_audit(
    db: DB,
    user: CurrentUser,
    user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    success: bool | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    ip: str | None = Query(default=None, max_length=45),
    q: str | None = Query(default=None, max_length=100),
    limit: int | None = None,
    cursor: str | None = None,
):
    if not (
        has_permission(user.role, Permission.audit_read)
        or has_permission(user.role, Permission.audit_read_own)
    ):
        from app.core.deps import deny

        await deny(user, Permission.audit_read)
    lim = clamp_limit(limit, 50, 200)
    stmt = _audit_filters(
        select(AuditLog),
        user,
        dict(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=patient_id,
            success=success,
            from_=from_,
            to=to,
            ip=ip,
            q=q,
        ),
    )
    if cursor:
        if not cursor.isdigit():
            raise AppError(400, "BAD_CURSOR", "Kursor noto'g'ri")
        stmt = stmt.where(AuditLog.id < int(cursor))
    rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(lim + 1))).scalars().all()
    more = len(rows) > lim
    rows = rows[:lim]
    return {
        "items": [_audit_item(r) for r in rows],
        "page": {"limit": lim, "next_cursor": str(rows[-1].id) if more and rows else None},
    }


def _csv_safe(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/audit-logs/export")
async def export_audit(
    db: DB,
    user: User = Perm(Permission.export_audit),
    format: str = Query(default="csv", pattern="^csv$"),
    action: AuditAction | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=50000, ge=1, le=200000),
):
    await rate_limit.hit("export", str(user.id), get_settings().rate_limit_export_user, 3600)
    stmt = _audit_filters(select(AuditLog), user, dict(action=action, from_=from_, to=to))
    rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit))).scalars().all()
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "ts",
            "user",
            "role",
            "action",
            "resource_type",
            "resource_id",
            "patient_id",
            "ip",
            "method",
            "path",
            "status_code",
            "success",
        ]
    )
    for r in rows:
        w.writerow(
            [
                _csv_safe(x)
                for x in (
                    r.id,
                    r.ts.isoformat(),
                    r.username_snapshot,
                    r.role_snapshot.value if r.role_snapshot else "",
                    r.action.value,
                    r.resource_type,
                    r.resource_id,
                    r.patient_id,
                    r.ip,
                    r.method,
                    r.path,
                    r.status_code,
                    r.success,
                )
            ]
        )
    audit_service.log_event(
        db, AuditAction.export, user=user, resource_type="audit_logs", meta={"rows": len(rows)}
    )
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )


_ = StreamingResponse

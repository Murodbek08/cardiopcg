from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.permissions import Permission, has_permission
from app.core.route import TxRoute
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.services import analytics_service as an

router = APIRouter(prefix="/analytics", tags=["analytics"], route_class=TxRoute, responses=ERROR_RESPONSES)

TZ = Query(default="Asia/Tashkent", max_length=40)
FROM = Query(default=None, alias="from")


def _period(d_from: date | None, d_to: date | None, tz: str) -> an.Period:
    return an.parse_period(d_from, d_to, tz)


# ----------------------------------------------------------------------------------- admin
@router.get("/admin/kpis")
async def admin_kpis(
    db: DB,
    user: User = Perm(Permission.analytics_admin),
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    p = _period(d_from, to, tz)
    return await an.cached(
        "admin_kpis", user.id, {"f": p.d_from, "t": p.d_to, "tz": tz}, lambda: an.admin_kpis(db, p)
    )


@router.get("/admin/timeseries")
async def admin_timeseries(
    db: DB,
    user: User = Perm(Permission.analytics_admin),
    metric: str = "examinations",
    granularity: str = "day",
    group_by: str | None = None,
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    p = _period(d_from, to, tz)
    return await an.cached(
        "admin_ts",
        user.id,
        {"m": metric, "g": granularity, "gb": group_by, "f": p.d_from, "t": p.d_to, "tz": tz},
        lambda: an.admin_timeseries(db, p, metric, granularity, group_by),
    )


@router.get("/admin/distributions")
async def admin_distributions(
    db: DB,
    user: User = Perm(Permission.analytics_admin),
    dimension: str = "pcg_class",
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    p = _period(d_from, to, tz)

    async def go() -> dict[str, Any]:
        return an.to_distribution(dimension, await an.distribution_rows(db, p, dimension))

    return await an.cached("admin_dist", user.id, {"d": dimension, "f": p.d_from, "t": p.d_to}, go)


@router.get("/admin/workload")
async def admin_workload(
    db: DB,
    user: User = Perm(Permission.analytics_admin),
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    p = _period(d_from, to, tz)
    return await an.cached(
        "admin_wl", user.id, {"f": p.d_from, "t": p.d_to}, lambda: an.admin_workload(db, p)
    )


@router.get("/admin/heatmap")
async def admin_heatmap(
    db: DB,
    user: User = Perm(Permission.analytics_admin),
    metric: str = "examinations",
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    p = _period(d_from, to, tz)
    return await an.cached(
        "admin_hm",
        user.id,
        {"m": metric, "f": p.d_from, "t": p.d_to, "tz": tz},
        lambda: an.admin_heatmap(db, p, metric),
    )


@router.get("/admin/ai-performance")
async def admin_ai_perf(
    db: DB,
    user: User = Perm(Permission.analytics_admin),
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    p = _period(d_from, to, tz)
    return await an.cached(
        "admin_ai", user.id, {"f": p.d_from, "t": p.d_to}, lambda: an.ai_performance(db, p)
    )


@router.get("/admin/system")
async def admin_system(db: DB, user: User = Perm(Permission.analytics_admin)):
    return await an.admin_system(db)


# ---------------------------------------------------------------------------------- doctor
async def _doctor_scope(user: User, doctor_id: uuid.UUID | None) -> uuid.UUID | None:
    """doctor -> own data only; admin -> ?doctor_id= (or all doctors when omitted)."""
    if user.role == UserRole.doctor:
        if doctor_id and doctor_id != user.id:
            await deny(user, Permission.analytics_admin, "analytics:doctor")
        return user.id
    if not has_permission(user.role, Permission.analytics_doctor):
        await deny(user, Permission.analytics_doctor)
    return doctor_id


@router.get("/doctor/kpis")
async def doctor_kpis(
    db: DB,
    user: CurrentUser,
    doctor_id: uuid.UUID | None = None,
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    did = await _doctor_scope(user, doctor_id)
    p = _period(d_from, to, tz)
    return await an.cached(
        "doc_kpis",
        user.id,
        {"d": did, "f": p.d_from, "t": p.d_to, "tz": tz},
        lambda: an.doctor_kpis(db, p, did, tz),
    )


@router.get("/doctor/queue")
async def doctor_queue(db: DB, user: CurrentUser, doctor_id: uuid.UUID | None = None):
    did = await _doctor_scope(user, doctor_id)
    return await an.doctor_queue(db, did)


@router.get("/doctor/timeseries")
async def doctor_ts(
    db: DB,
    user: CurrentUser,
    metric: str = "completed",
    granularity: str = "day",
    doctor_id: uuid.UUID | None = None,
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    did = await _doctor_scope(user, doctor_id)
    p = _period(d_from, to, tz)
    return await an.cached(
        "doc_ts",
        user.id,
        {"m": metric, "g": granularity, "d": did, "f": p.d_from, "t": p.d_to},
        lambda: an.doctor_timeseries(db, p, did, metric, granularity),
    )


@router.get("/doctor/distributions")
async def doctor_dist(
    db: DB,
    user: CurrentUser,
    dimension: str = "final_pcg_class",
    doctor_id: uuid.UUID | None = None,
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    did = await _doctor_scope(user, doctor_id)
    p = _period(d_from, to, tz)
    allowed = {"final_pcg_class", "final_severity", "icd10", "age_group"}
    if dimension not in allowed:
        from app.core.errors import AppError

        raise AppError(422, "VALIDATION_ERROR", f"dimension: {', '.join(sorted(allowed))}")

    async def go() -> dict[str, Any]:
        return an.to_distribution(dimension, await an.distribution_rows(db, p, dimension, did))

    return await an.cached("doc_dist", user.id, {"d": dimension, "doc": did, "f": p.d_from, "t": p.d_to}, go)


@router.get("/doctor/ai-vs-doctor")
async def doctor_ai_vs(
    db: DB,
    user: CurrentUser,
    doctor_id: uuid.UUID | None = None,
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    did = await _doctor_scope(user, doctor_id)
    p = _period(d_from, to, tz)
    return await an.cached(
        "doc_ai", user.id, {"d": did, "f": p.d_from, "t": p.d_to}, lambda: an.ai_vs_doctor(db, p, did)
    )


@router.get("/doctor/follow-ups")
async def doctor_follow(
    db: DB, user: CurrentUser, doctor_id: uuid.UUID | None = None, days: int = Query(default=30, ge=1, le=365)
):
    did = await _doctor_scope(user, doctor_id)
    return await an.doctor_follow_ups(db, did, days)


# ----------------------------------------------------------------------------------- nurse
@router.get("/nurse/kpis")
async def nurse_kpis(
    db: DB,
    user: CurrentUser,
    nurse_id: uuid.UUID | None = None,
    d_from: date | None = FROM,
    to: date | None = None,
    tz: str = TZ,
):
    if user.role == UserRole.nurse:
        if nurse_id and nurse_id != user.id:
            await deny(user, Permission.analytics_admin, "analytics:nurse")
        nid: uuid.UUID | None = user.id
    elif user.role == UserRole.admin:
        nid = nurse_id
    else:
        await deny(user, Permission.analytics_nurse)
        return {}
    p = _period(d_from, to, tz)
    return await an.cached(
        "nurse_kpis",
        user.id,
        {"n": nid, "f": p.d_from, "t": p.d_to, "tz": tz},
        lambda: an.nurse_kpis(db, p, nid, tz),
    )

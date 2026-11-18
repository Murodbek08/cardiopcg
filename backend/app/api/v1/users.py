from __future__ import annotations

import secrets
import string
import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser, Perm
from app.core.errors import AppError, conflict, not_found
from app.core.pagination import clamp_limit
from app.core.permissions import Permission
from app.core.route import TxRoute
from app.core.security import hash_password, validate_password_strength
from app.db.base import utcnow
from app.models.enums import AuditAction, UserRole, UserStatus
from app.models.user import User
from app.schemas.auth import AdminResetIn, AdminResetOut, DoctorRef, UserCreate, UserOut, UserUpdate
from app.schemas.common import ERROR_RESPONSES
from app.services import audit_service, auth_service, settings_service

router = APIRouter(prefix="/users", tags=["users"], route_class=TxRoute)

SORTS = {"full_name": User.full_name, "created_at": User.created_at, "last_login_at": User.last_login_at}


async def _get(db, uid: uuid.UUID) -> User:
    u = await db.get(User, uid)
    if u is None or u.deleted_at is not None:
        raise not_found("Foydalanuvchi")
    return u


async def _active_admin_count(db, excluding: uuid.UUID | None = None) -> int:
    q = (
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.admin, User.status == UserStatus.active, User.deleted_at.is_(None))
    )
    if excluding:
        q = q.where(User.id != excluding)
    return (await db.execute(q)).scalar_one()


def _snap(u: User) -> dict:
    return {
        k: getattr(u, k)
        for k in ("full_name", "role", "status", "phone", "email", "specialty", "license_no", "department")
    }


@router.get("/doctors", response_model=list[DoctorRef])
async def list_doctors(user: CurrentUser, db: DB):
    """Minimal list of active doctors (for assignment) - all roles."""
    rows = (
        (
            await db.execute(
                select(User)
                .where(
                    User.role == UserRole.doctor, User.status == UserStatus.active, User.deleted_at.is_(None)
                )
                .order_by(User.full_name)
            )
        )
        .scalars()
        .all()
    )
    return rows


@router.get("", dependencies=[Perm(Permission.user_manage)], responses=ERROR_RESPONSES)
async def list_users(
    db: DB,
    role: UserRole | None = None,
    status: UserStatus | None = None,
    q: str | None = Query(default=None, min_length=2),
    sort: str = "-created_at",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    stmt = select(User).where(User.deleted_at.is_(None))
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(User.full_name.ilike(like) | User.username.ilike(like))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    name = sort.lstrip("-")
    if name not in SORTS:
        raise AppError(422, "VALIDATION_ERROR", "Saralash maydoni ruxsat etilmagan")
    col = SORTS[name]
    stmt = stmt.order_by(col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last(), User.id)
    rows = (
        (await db.execute(stmt.limit(clamp_limit(page_size)).offset((page - 1) * page_size))).scalars().all()
    )
    return {
        "items": [UserOut.model_validate(r) for r in rows],
        "page": {"page": page, "page_size": page_size, "total": total},
    }


@router.post(
    "",
    status_code=201,
    response_model=UserOut,
    responses={409: {"description": "USERNAME_TAKEN / EMAIL_TAKEN"}, 400: {"description": "WEAK_PASSWORD"}},
)
async def create_user(body: UserCreate, db: DB, admin: User = Perm(Permission.user_manage)):
    if (await db.execute(select(User.id).where(User.username == body.username))).first():
        raise conflict("USERNAME_TAKEN", "Bu username band")
    if body.email and (await db.execute(select(User.id).where(User.email == body.email))).first():
        raise conflict("EMAIL_TAKEN", "Bu email band")
    min_len = await settings_service.get_value(db, "security.password_min_length")
    validate_password_strength(body.password, min_len, [body.username, body.full_name])
    now = utcnow()
    u = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        status=UserStatus.active,
        phone=body.phone,
        specialty=body.specialty,
        license_no=body.license_no,
        department=body.department,
        must_change_password=body.must_change_password,
        password_changed_at=now,
        created_by=admin.id,
    )
    db.add(u)
    await db.flush()
    audit_service.log_event(
        db,
        AuditAction.create,
        user=admin,
        resource_type="user",
        resource_id=u.id,
        changes={"after": {"username": u.username, "role": u.role, "full_name": u.full_name}},
    )
    return u


@router.get("/{user_id}", response_model=UserOut, dependencies=[Perm(Permission.user_manage)])
async def get_user(user_id: uuid.UUID, db: DB):
    return await _get(db, user_id)


@router.patch(
    "/{user_id}", response_model=UserOut, responses={409: {"description": "LAST_ADMIN / EMAIL_TAKEN"}}
)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, db: DB, admin: User = Perm(Permission.user_manage)
):
    u = await _get(db, user_id)
    data = body.model_dump(exclude_unset=True)
    if "email" in data and data["email"] and data["email"] != u.email:
        if (await db.execute(select(User.id).where(User.email == data["email"], User.id != u.id))).first():
            raise conflict("EMAIL_TAKEN", "Bu email band")
    demoting = u.role == UserRole.admin and (
        data.get("role", u.role) != UserRole.admin or data.get("status", u.status) != UserStatus.active
    )
    if demoting and await _active_admin_count(db, excluding=u.id) == 0:
        raise conflict("LAST_ADMIN", "Oxirgi administratorni o'zgartirib bo'lmaydi")
    before = _snap(u)
    for k, v in data.items():
        setattr(u, k, v)
    if "role" in data and data["role"] != before["role"]:
        await auth_service.revoke_user_sessions(db, u, "admin")
    if data.get("status") == UserStatus.suspended:
        await auth_service.revoke_user_sessions(db, u, "admin")
    audit_service.log_event(
        db,
        AuditAction.update,
        user=admin,
        resource_type="user",
        resource_id=u.id,
        changes=audit_service.diff(before, _snap(u)),
    )
    return u


@router.post("/{user_id}/reset-password", response_model=AdminResetOut)
async def reset_password(
    user_id: uuid.UUID, db: DB, body: AdminResetIn | None = None, admin: User = Perm(Permission.user_manage)
):
    u = await _get(db, user_id)
    mode: Literal["link", "temp_password"] = body.mode if body else "link"
    audit_service.log_event(
        db,
        AuditAction.password_reset,
        user=admin,
        resource_type="user",
        resource_id=u.id,
        meta={"mode": mode},
    )
    if mode == "temp_password":
        alphabet = string.ascii_letters + string.digits
        temp = "".join(secrets.choice(alphabet) for _ in range(14)) + "-Aa1"
        u.password_hash = hash_password(temp)
        u.password_changed_at = utcnow()
        u.must_change_password = True
        await auth_service.revoke_user_sessions(db, u, "admin")
        return AdminResetOut(mode=mode, temp_password=temp)
    raw, prt = await auth_service.create_reset_token(db, u)
    return AdminResetOut(mode=mode, reset_token=raw, expires_at=prt.expires_at)


@router.post("/{user_id}/suspend", response_model=UserOut)
async def suspend(user_id: uuid.UUID, db: DB, admin: User = Perm(Permission.user_manage)):
    u = await _get(db, user_id)
    if u.id == admin.id:
        raise conflict("CANNOT_SUSPEND_SELF", "O'zingizni bloklab bo'lmaydi")
    if (
        u.role == UserRole.admin
        and u.status == UserStatus.active
        and await _active_admin_count(db, u.id) == 0
    ):
        raise conflict("LAST_ADMIN", "Oxirgi administratorni bloklab bo'lmaydi")
    u.status = UserStatus.suspended
    await auth_service.revoke_user_sessions(db, u, "admin")
    audit_service.log_event(
        db,
        AuditAction.update,
        user=admin,
        resource_type="user",
        resource_id=u.id,
        changes={"before": {"status": "active"}, "after": {"status": "suspended"}},
    )
    return u


@router.post("/{user_id}/activate", response_model=UserOut)
async def activate(user_id: uuid.UUID, db: DB, admin: User = Perm(Permission.user_manage)):
    u = await _get(db, user_id)
    prev = u.status.value
    u.status = UserStatus.active
    audit_service.log_event(
        db,
        AuditAction.update,
        user=admin,
        resource_type="user",
        resource_id=u.id,
        changes={"before": {"status": prev}, "after": {"status": "active"}},
    )
    return u


@router.post("/{user_id}/unlock", response_model=UserOut)
async def unlock(user_id: uuid.UUID, db: DB, admin: User = Perm(Permission.user_manage)):
    u = await _get(db, user_id)
    u.locked_until = None
    u.failed_login_count = 0
    u.lock_count = 0
    audit_service.log_event(
        db, AuditAction.update, user=admin, resource_type="user", resource_id=u.id, meta={"unlock": True}
    )
    return u


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, db: DB, admin: User = Perm(Permission.user_manage)):
    u = await _get(db, user_id)
    if u.id == admin.id:
        raise conflict("CANNOT_DELETE_SELF", "O'zingizni o'chirib bo'lmaydi")
    if (
        u.role == UserRole.admin
        and u.status == UserStatus.active
        and await _active_admin_count(db, u.id) == 0
    ):
        raise conflict("LAST_ADMIN", "Oxirgi administratorni o'chirib bo'lmaydi")
    u.deleted_at = utcnow()
    await auth_service.revoke_user_sessions(db, u, "admin")
    audit_service.log_event(db, AuditAction.delete, user=admin, resource_type="user", resource_id=u.id)
    return Response(status_code=204)

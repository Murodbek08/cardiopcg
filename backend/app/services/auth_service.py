"""Authentication: login with lockout, rotating refresh tokens with reuse detection, password flows."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import rate_limit
from app.core.context import get_request_info
from app.core.errors import AppError, bad_request
from app.core.kv import get_kv
from app.core.security import (
    create_access_token,
    dummy_verify,
    hash_password,
    needs_rehash,
    new_refresh_token,
    sha256_hex,
    validate_password_strength,
    verify_password,
)
from app.db.base import new_id, utcnow
from app.models.enums import AuditAction, UserStatus
from app.models.user import PasswordResetToken, RefreshToken, User
from app.services import audit_service, settings_service

GRACE_SECONDS = 10


@dataclass
class Tokens:
    access_token: str
    expires_in: int
    refresh_token: str | None
    user: User


def _device_label(ua: str | None) -> str | None:
    if not ua:
        return None
    browser = next((b for b in ("Edg", "Chrome", "Firefox", "Safari") if b in ua), "Browser")
    os_ = next((o for o in ("Windows", "Android", "iPhone", "Mac", "Linux") if o in ua), "")
    return f"{browser} / {os_}".strip(" /")[:120]


async def _issue_refresh(
    db: AsyncSession, user: User, family_id: uuid.UUID, parent: RefreshToken | None, family_started_at
) -> str:
    s = get_settings()
    raw, h = new_refresh_token()
    info = get_request_info()
    now = utcnow()
    expires = min(
        now + timedelta(days=s.jwt_refresh_ttl_days), family_started_at + timedelta(days=s.session_max_days)
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=h,
            parent_id=parent.id if parent else None,
            issued_at=now,
            family_started_at=family_started_at,
            expires_at=expires,
            ip=info.ip,
            user_agent=(info.user_agent or "")[:300] or None,
            device_label=_device_label(info.user_agent),
        )
    )
    return raw


def _access_for(user: User) -> tuple[str, int]:
    return create_access_token(str(user.id), user.role.value, user.security_version)


async def login(db: AsyncSession, username: str, password: str) -> Tokens:
    s = get_settings()
    info = get_request_info()
    uname = username.strip().lower()
    await rate_limit.hit("login-ip", info.ip or "unknown", s.rate_limit_login_ip)
    await rate_limit.hit("login-user", uname, s.rate_limit_login_user)

    user = (
        await db.execute(select(User).where(User.username == uname, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    cfg = await settings_service.get_many(db, "security.lockout_attempts", "security.lockout_minutes")
    now = utcnow()

    async def fail(reason: str, user_: User | None = None) -> AppError:
        audit_service.log_event(
            db,
            AuditAction.login_failed,
            user=user_,
            username=uname,
            resource_type="user",
            resource_id=user_.id if user_ else None,
            success=False,
            status_code=401,
            meta={"reason": reason},
        )
        await db.commit()
        return AppError(401, "INVALID_CREDENTIALS", "Foydalanuvchi nomi yoki parol noto'g'ri")

    if user is None:
        dummy_verify(password)
        raise await fail("unknown_user")

    if user.locked_until and user.locked_until > now:
        audit_service.log_event(
            db,
            AuditAction.login_failed,
            user=user,
            resource_type="user",
            resource_id=user.id,
            success=False,
            status_code=423,
            meta={"reason": "locked"},
        )
        await db.commit()
        raise AppError(
            423,
            "ACCOUNT_LOCKED",
            "Hisob vaqtincha bloklangan",
            {"locked_until": user.locked_until.isoformat()},
        )

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= cfg["security.lockout_attempts"]:
            user.lock_count += 1
            minutes = cfg["security.lockout_minutes"] * min(2 ** (user.lock_count - 1), 4)
            user.locked_until = now + timedelta(minutes=minutes)
            user.failed_login_count = 0
        raise await fail("bad_password", user)

    if user.status != UserStatus.active:
        audit_service.log_event(
            db,
            AuditAction.login_failed,
            user=user,
            resource_type="user",
            resource_id=user.id,
            success=False,
            status_code=403,
            meta={"reason": f"status_{user.status.value}"},
        )
        await db.commit()
        raise AppError(403, "ACCOUNT_SUSPENDED", "Hisob faol emas")

    user.failed_login_count = 0
    user.lock_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    family = new_id()
    refresh = await _issue_refresh(db, user, family, None, now)
    access, ttl = _access_for(user)
    audit_service.log_event(db, AuditAction.login, user=user, resource_type="user", resource_id=user.id)
    return Tokens(access, ttl, refresh, user)


def _check_origin(origin: str | None) -> None:
    if origin and origin.rstrip("/") not in get_settings().origins:
        raise AppError(403, "FORBIDDEN", "Origin ruxsat etilmagan")


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID, reason: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )


async def refresh(db: AsyncSession, raw_token: str | None, origin: str | None) -> Tokens:
    s = get_settings()
    _check_origin(origin)
    await rate_limit.hit("refresh-ip", get_request_info().ip or "unknown", s.rate_limit_refresh_ip)
    if not raw_token:
        raise AppError(401, "REFRESH_INVALID", "Refresh token yo'q")
    h = sha256_hex(raw_token)
    rt = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == h).with_for_update())
    ).scalar_one_or_none()
    if rt is None:
        raise AppError(401, "REFRESH_INVALID", "Refresh token yaroqsiz")
    now = utcnow()
    user = await db.get(User, rt.user_id)
    if user is None or user.deleted_at is not None or user.status != UserStatus.active:
        raise AppError(401, "REFRESH_INVALID", "Refresh token yaroqsiz")

    if rt.used_at is not None:
        # parallel-tab grace window: hand out the same successor token
        grace = await get_kv().get(f"refresh:grace:{h}")
        if grace and (now - rt.used_at).total_seconds() <= GRACE_SECONDS:
            access, ttl = _access_for(user)
            return Tokens(access, ttl, grace, user)
        await _revoke_family(db, rt.family_id, "reuse_detected")
        audit_service.log_event(
            db,
            AuditAction.token_reuse_detected,
            user=user,
            resource_type="user",
            resource_id=user.id,
            success=False,
            status_code=401,
            meta={"family_id": str(rt.family_id)},
        )
        await db.commit()
        raise AppError(401, "TOKEN_REUSE_DETECTED", "Token qayta ishlatildi, barcha sessiyalar bekor qilindi")

    if rt.revoked_at is not None:
        raise AppError(401, "REFRESH_INVALID", "Refresh token bekor qilingan")
    if rt.expires_at <= now:
        raise AppError(401, "REFRESH_EXPIRED", "Refresh token muddati tugagan")

    rt.used_at = now
    rt.revoked_at = now
    rt.revoked_reason = "rotated"
    new_raw = await _issue_refresh(db, user, rt.family_id, rt, rt.family_started_at)
    await get_kv().set(f"refresh:grace:{h}", new_raw, GRACE_SECONDS)
    access, ttl = _access_for(user)
    audit_service.log_event(
        db, AuditAction.token_refresh, user=user, resource_type="user", resource_id=user.id
    )
    return Tokens(access, ttl, new_raw, user)


async def logout(db: AsyncSession, user: User, raw_token: str | None, origin: str | None) -> None:
    _check_origin(origin)
    if raw_token:
        rt = (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == sha256_hex(raw_token), RefreshToken.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if rt:
            await _revoke_family(db, rt.family_id, "logout")
    audit_service.log_event(db, AuditAction.logout, user=user, resource_type="user", resource_id=user.id)


async def revoke_all(
    db: AsyncSession, user_id: uuid.UUID, reason: str, except_family: uuid.UUID | None = None
) -> None:
    q = update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    if except_family:
        q = q.where(RefreshToken.family_id != except_family)
    await db.execute(q.values(revoked_at=utcnow(), revoked_reason=reason))


async def change_password(
    db: AsyncSession, user: User, current: str, new: str, current_refresh: str | None
) -> None:
    s = get_settings()
    await rate_limit.hit("pwd", str(user.id), s.rate_limit_password)
    if not verify_password(user.password_hash, current):
        raise AppError(400, "WRONG_CURRENT_PASSWORD", "Joriy parol noto'g'ri")
    min_len = await settings_service.get_value(db, "security.password_min_length")
    validate_password_strength(new, min_len, [user.username, user.full_name])
    _ensure_not_reused(user, new)
    _set_password(user, new)
    keep = None
    if current_refresh:
        rt = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(current_refresh))
            )
        ).scalar_one_or_none()
        keep = rt.family_id if rt and rt.user_id == user.id else None
    await revoke_all(db, user.id, "password_change", except_family=keep)
    audit_service.log_event(
        db, AuditAction.password_change, user=user, resource_type="user", resource_id=user.id
    )


def _ensure_not_reused(user: User, new: str) -> None:
    for h in [user.password_hash, *(user.password_history or [])][:5]:
        if verify_password(h, new):
            raise AppError(400, "WEAK_PASSWORD", "Oxirgi 5 ta paroldan birini qayta ishlatib bo'lmaydi")


def _set_password(user: User, new: str, must_change: bool = False) -> None:
    history = [user.password_hash, *(user.password_history or [])][:4]
    user.password_history = history
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    user.must_change_password = must_change


async def create_reset_token(
    db: AsyncSession, user: User, ttl_min: int = 30
) -> tuple[str, PasswordResetToken]:
    raw = secrets.token_urlsafe(32)
    prt = PasswordResetToken(
        user_id=user.id, token_hash=sha256_hex(raw), expires_at=utcnow() + timedelta(minutes=ttl_min)
    )
    db.add(prt)
    return raw, prt


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    await rate_limit.hit("pwd-reset", get_request_info().ip or "unknown", get_settings().rate_limit_password)
    prt = (
        await db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == sha256_hex(token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = utcnow()
    if prt is None or prt.used_at is not None or prt.expires_at <= now:
        raise bad_request("TOKEN_INVALID_OR_EXPIRED", "Havola yaroqsiz yoki muddati tugagan")
    user = await db.get(User, prt.user_id)
    if user is None or user.deleted_at is not None:
        raise bad_request("TOKEN_INVALID_OR_EXPIRED", "Havola yaroqsiz yoki muddati tugagan")
    min_len = await settings_service.get_value(db, "security.password_min_length")
    validate_password_strength(new_password, min_len, [user.username, user.full_name])
    _set_password(user, new_password)
    user.security_version += 1
    user.failed_login_count = 0
    user.locked_until = None
    prt.used_at = now
    await revoke_all(db, user.id, "password_change")
    audit_service.log_event(
        db, AuditAction.password_reset, user=user, resource_type="user", resource_id=user.id
    )


async def revoke_user_sessions(db: AsyncSession, user: User, reason: str) -> None:
    """Suspend/admin action: kill refresh tokens and invalidate outstanding access tokens."""
    user.security_version += 1
    await revoke_all(db, user.id, reason)

"""FastAPI dependencies: DB session (commit/rollback + post-commit events), auth, RBAC."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import rate_limit
from app.core.context import get_request_info
from app.core.errors import AppError, forbidden, unauthenticated
from app.core.permissions import Permission, has_permission
from app.core.security import decode_access_token
from app.db.session import get_sessionmaker
from app.models.enums import AuditAction, UserRole, UserStatus
from app.models.user import User
from app.services import audit_service, realtime


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request. TxRoute commits before the response is sent (so clients never race
    uncommitted data); this dependency is the safety net (rollback on error, commit otherwise)."""
    async with get_sessionmaker()() as session:
        request.state.db = session
        try:
            yield session
        except BaseException:
            await session.rollback()
            realtime.drop_events(session)
            raise
        await session.commit()
        await realtime.flush_events(session)


DB = Annotated[AsyncSession, Depends(get_db)]


async def user_from_token(db: AsyncSession, token: str) -> User:
    claims = decode_access_token(token)
    try:
        uid = uuid.UUID(claims["sub"])
    except (ValueError, KeyError):
        raise unauthenticated()
    user = await db.get(User, uid)
    if user is None or user.deleted_at is not None:
        raise unauthenticated()
    if claims.get("sv") != user.security_version:
        raise AppError(
            401,
            "TOKEN_EXPIRED",
            "Sessiya bekor qilingan, qayta kiring",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status != UserStatus.active:
        raise forbidden("Hisob faol emas", "ACCOUNT_SUSPENDED")
    return user


async def get_current_user(request: Request, db: DB) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthenticated()
    user = await user_from_token(db, token.strip())
    info = get_request_info()
    info.user_id, info.role = str(user.id), user.role.value
    await rate_limit.hit("api", str(user.id), get_settings().rate_limit_api_user)
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def deny(user: User, perm: Permission | str, resource: str | None = None) -> None:
    """Audit a permission denial in its own transaction, then raise 403."""
    await audit_service.log_standalone(
        AuditAction.permission_denied,
        user=user,
        success=False,
        status_code=403,
        meta={"permission": str(perm), "resource": resource},
    )
    raise forbidden()


def require_permission(perm: Permission):
    async def dep(user: CurrentUser) -> User:
        if not has_permission(user.role, perm):
            await deny(user, perm)
        return user

    return dep


def require_roles(*roles: UserRole):
    async def dep(user: CurrentUser) -> User:
        if user.role not in roles:
            await deny(user, "role:" + ",".join(r.value for r in roles))
        return user

    return dep


def Perm(perm: Permission):  # noqa: N802 - dependency factory used like Depends(Perm(...))
    return Depends(require_permission(perm))

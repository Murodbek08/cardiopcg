from __future__ import annotations

from fastapi import APIRouter, File, Request, Response, UploadFile

from app.config import get_settings
from app.core.deps import DB, CurrentUser
from app.core.errors import AppError
from app.core.permissions import permissions_for
from app.core.route import TxRoute
from app.models.enums import AuditAction
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    LoginOut,
    MeOut,
    MeUpdate,
    RefreshOut,
    ResetPasswordIn,
)
from app.schemas.common import ERROR_RESPONSES
from app.services import audit_service, auth_service
from app.services.storage import get_storage

router = APIRouter(prefix="/auth", tags=["auth"], route_class=TxRoute)

COOKIE = "cp_refresh"
COOKIE_PATH = "/api/v1/auth"


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(
        COOKIE,
        token,
        max_age=s.jwt_refresh_ttl_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
        path=COOKIE_PATH,
    )


def _clear_cookie(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path=COOKIE_PATH)


@router.post(
    "/login",
    response_model=LoginOut,
    responses={401: ERROR_RESPONSES[401], 423: {"description": "ACCOUNT_LOCKED"}},
)
async def login(body: LoginIn, response: Response, db: DB):
    tokens = await auth_service.login(db, body.username, body.password)
    assert tokens.refresh_token
    _set_cookie(response, tokens.refresh_token)
    return LoginOut(access_token=tokens.access_token, expires_in=tokens.expires_in, user=tokens.user)


@router.post("/refresh", response_model=RefreshOut)
async def refresh(request: Request, response: Response, db: DB):
    try:
        tokens = await auth_service.refresh(db, request.cookies.get(COOKIE), request.headers.get("origin"))
    except AppError as exc:
        if exc.code in ("REFRESH_INVALID", "REFRESH_EXPIRED", "TOKEN_REUSE_DETECTED"):
            exc.headers["Set-Cookie"] = (
                f"{COOKIE}=; Max-Age=0; Path={COOKIE_PATH}; HttpOnly; SameSite={get_settings().cookie_samesite}"
            )
        raise
    assert tokens.refresh_token
    _set_cookie(response, tokens.refresh_token)
    return RefreshOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/logout", status_code=204)
async def logout(request: Request, user: CurrentUser, db: DB):
    await auth_service.logout(db, user, request.cookies.get(COOKIE), request.headers.get("origin"))
    resp = Response(status_code=204)
    _clear_cookie(resp)
    return resp


@router.post("/logout-all", status_code=204)
async def logout_all(user: CurrentUser, db: DB):
    await auth_service.revoke_all(db, user.id, "logout")
    audit_service.log_event(
        db, AuditAction.logout, user=user, resource_type="user", resource_id=user.id, meta={"all": True}
    )
    resp = Response(status_code=204)
    _clear_cookie(resp)
    return resp


def _me(user) -> MeOut:
    return MeOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        email=user.email,
        phone=user.phone,
        specialty=user.specialty,
        license_no=user.license_no,
        department=user.department,
        locale=user.locale,
        permissions=permissions_for(user.role),
        last_login_at=user.last_login_at,
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser):
    return _me(user)


@router.patch("/me", response_model=MeOut, responses=ERROR_RESPONSES)
async def update_me(body: MeUpdate, user: CurrentUser, db: DB):
    from sqlalchemy import select

    from app.models.user import User

    data = body.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        dup = (
            await db.execute(select(User.id).where(User.email == data["email"], User.id != user.id))
        ).first()
        if dup:
            raise AppError(409, "EMAIL_TAKEN", "Bu email band")
    before = {k: getattr(user, k) for k in data}
    for k, v in data.items():
        setattr(user, k, v)
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="user",
        resource_id=user.id,
        changes=audit_service.diff(before, data),
    )
    return _me(user)


@router.post("/me/avatar", status_code=200)
async def upload_avatar(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    from io import BytesIO

    from PIL import Image

    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise AppError(413, "FILE_TOO_LARGE", "Avatar 2 MB dan oshmasligi kerak")
    try:
        img = Image.open(BytesIO(data))
        img.verify()
        img = Image.open(BytesIO(data))
        fmt = (img.format or "").upper()
        if fmt not in ("PNG", "JPEG"):
            raise ValueError
        out = BytesIO()
        img.convert("RGB").resize((256, 256)).save(out, "PNG")
    except Exception:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Faqat PNG/JPG rasm")
    key = f"avatars/{user.id}.png"
    await get_storage().put_bytes(key, out.getvalue(), "image/png")
    user.avatar_key = key
    audit_service.log_event(
        db, AuditAction.upload, user=user, resource_type="user", resource_id=user.id, meta={"kind": "avatar"}
    )
    return {"avatar_key": key}


@router.post(
    "/change-password",
    status_code=204,
    responses={400: {"description": "WEAK_PASSWORD / WRONG_CURRENT_PASSWORD"}},
)
async def change_password(body: ChangePasswordIn, request: Request, user: CurrentUser, db: DB):
    await auth_service.change_password(
        db, user, body.current_password, body.new_password, request.cookies.get(COOKIE)
    )
    return Response(status_code=204)


@router.post("/reset-password", status_code=204, responses={400: {"description": "TOKEN_INVALID_OR_EXPIRED"}})
async def reset_password(body: ResetPasswordIn, db: DB):
    await auth_service.reset_password(db, body.token, body.new_password)
    return Response(status_code=204)

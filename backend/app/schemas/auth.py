from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.models.enums import UserRole, UserStatus
from app.schemas.common import Out, Strict

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def _norm_username(v: str) -> str:
    v = v.strip().lower()
    if not USERNAME_RE.match(v):
        raise ValueError("username 3-32 belgi, faqat [a-z0-9._-]")
    return v


def _check_phone(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    v = v.replace(" ", "").replace("-", "")
    if not PHONE_RE.match(v):
        raise ValueError("telefon E.164 formatida bo'lishi kerak")
    return v


class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginUser(Out):
    id: UUID
    username: str
    full_name: str
    role: UserRole
    locale: str
    must_change_password: bool


class LoginOut(Out):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: LoginUser


class RefreshOut(Out):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(Out):
    id: UUID
    username: str
    full_name: str
    role: UserRole
    email: str | None = None
    phone: str | None = None
    specialty: str | None = None
    license_no: str | None = None
    department: str | None = None
    locale: str
    permissions: list[str]
    last_login_at: datetime | None = None
    must_change_password: bool


class MeUpdate(Strict):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = None
    email: EmailStr | None = None
    locale: Literal["uz", "ru", "en"] | None = None

    _phone = field_validator("phone")(_check_phone)


class ChangePasswordIn(Strict):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ResetPasswordIn(Strict):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=256)


# ------------------------------------------------------------------------------------------ users
class UserCreate(Strict):
    username: str
    full_name: str = Field(min_length=2, max_length=160)
    role: UserRole
    email: EmailStr | None = None
    phone: str | None = None
    specialty: str | None = Field(default=None, max_length=120)
    license_no: str | None = Field(default=None, max_length=64)
    department: str | None = Field(default=None, max_length=120)
    password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = True

    _u = field_validator("username")(_norm_username)
    _p = field_validator("phone")(_check_phone)


class UserUpdate(Strict):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    role: UserRole | None = None
    status: UserStatus | None = None
    phone: str | None = None
    email: EmailStr | None = None
    specialty: str | None = Field(default=None, max_length=120)
    license_no: str | None = Field(default=None, max_length=64)
    department: str | None = Field(default=None, max_length=120)

    _p = field_validator("phone")(_check_phone)


class UserOut(Out):
    id: UUID
    username: str
    full_name: str
    role: UserRole
    status: UserStatus
    email: str | None = None
    phone: str | None = None
    specialty: str | None = None
    license_no: str | None = None
    department: str | None = None
    locale: str
    must_change_password: bool
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class DoctorRef(Out):
    id: UUID
    full_name: str
    specialty: str | None = None


class AdminResetIn(Strict):
    mode: Literal["link", "temp_password"] = "link"


class AdminResetOut(Out):
    mode: str
    reset_token: str | None = None
    temp_password: str | None = None
    expires_at: datetime | None = None

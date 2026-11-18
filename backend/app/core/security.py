"""argon2id hashing, JWT access tokens, refresh token helpers, password policy."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from zxcvbn import zxcvbn

from app.config import get_settings
from app.core.errors import AppError

# argon2id: time_cost=3, memory_cost=64 MiB, parallelism=4 (doc 01 section 7.1)
ARGON2_PARAMS = {"time_cost": 3, "memory_cost": 65536, "parallelism": 4}
_hasher = PasswordHasher(**ARGON2_PARAMS)

# Minimal embedded list of the most common breached passwords (full top-10k list not bundled).
COMMON_PASSWORDS = frozenset(
    p.lower()
    for p in (
        "password",
        "password1",
        "password123",
        "123456789",
        "1234567890",
        "12345678910",
        "qwertyuiop",
        "qwerty123456",
        "1q2w3e4r5t",
        "iloveyou123",
        "admin12345",
        "administrator",
        "welcome12345",
        "letmein12345",
        "abc123456789",
        "passw0rd123",
        "parol12345",
        "cardiopcg123",
        "0123456789",
        "11111111111",
    )
)

_DUMMY_HASH: str | None = None


def _pre(password: str) -> str:
    pepper = get_settings().password_pepper
    if not pepper:
        return password
    return hmac.new(pepper.encode(), password.encode(), hashlib.sha256).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(_pre(password))


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, _pre(password))
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


def dummy_verify(password: str) -> None:
    """Burn the same CPU as a real verification (timing attack mitigation for unknown users)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _hasher.hash("dummy-password-for-timing")
    verify_password(_DUMMY_HASH, password)


def validate_password_strength(
    password: str, min_length: int = 10, user_inputs: list[str] | None = None
) -> None:
    """Raises 400 WEAK_PASSWORD."""
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"Parol kamida {min_length} belgidan iborat bo'lishi kerak")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("Parol juda keng tarqalgan")
    if len(password) <= 128:
        score = zxcvbn(password[:72], user_inputs=user_inputs or [])["score"]
        if score < 3:
            problems.append("Parol yetarlicha murakkab emas")
    else:
        problems.append("Parol juda uzun (maks. 128)")
    if problems:
        raise AppError(400, "WEAK_PASSWORD", problems[0], {"problems": problems})


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)


def create_access_token(user_id: str, role: str, security_version: int) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = timedelta(minutes=s.jwt_access_ttl_min)
    payload = {
        "sub": user_id,
        "role": role,
        "jti": secrets.token_hex(8),
        "iat": now,
        "exp": now + ttl,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "sv": security_version,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_alg), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_alg],  # explicit allowlist: rejects alg=none
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
            leeway=10,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "sv"]},
        )
    except jwt.ExpiredSignatureError:
        raise AppError(401, "TOKEN_EXPIRED", "Token muddati tugagan", headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise AppError(401, "UNAUTHENTICATED", "Token yaroqsiz", headers={"WWW-Authenticate": "Bearer"})

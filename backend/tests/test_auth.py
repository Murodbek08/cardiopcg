from __future__ import annotations

import time

import jwt
import pytest
from sqlalchemy import select, text
from support import PASSWORD, create_user

from app.config import get_settings, reset_settings_cache
from app.core import security
from app.db import session as dbs
from app.models.enums import UserRole
from app.models.system import AuditLog
from app.models.user import RefreshToken, User


def test_production_argon2_params():
    assert security.ARGON2_PARAMS == {"time_cost": 3, "memory_cost": 65536, "parallelism": 4}
    h = security.PasswordHasher(**security.ARGON2_PARAMS).hash("x")
    assert h.startswith("$argon2id$")


async def test_login_me_logout(client):
    u = await create_user(UserRole.doctor, "dr.karimov")
    r = await client.post("/api/v1/auth/login", json={"username": "DR.Karimov", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900 and body["user"]["role"] == "doctor"
    assert "cp_refresh" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert "Path=/api/v1/auth" in r.headers["set-cookie"] and "SameSite=strict" in r.headers[
        "set-cookie"
    ].replace("Strict", "strict")
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert (
        me.status_code == 200
        and "conclusion:sign" in me.json()["permissions"]
        and me.json()["id"] == str(u.id)
    )
    assert (
        await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {body['access_token']}"})
    ).status_code == 204
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401  # family revoked + cookie cleared


async def test_invalid_credentials_same_message(client):
    await create_user(UserRole.nurse, "nurse.x")
    a = await client.post("/api/v1/auth/login", json={"username": "nurse.x", "password": "wrong-password"})
    b = await client.post("/api/v1/auth/login", json={"username": "ghost", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert a.json()["error"]["message"] == b.json()["error"]["message"]
    assert a.json()["error"]["request_id"]


async def test_lockout_after_5_failures_and_admin_unlock(client, admin):
    u = await create_user(UserRole.nurse, "nurse.lock")
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/login", json={"username": "nurse.lock", "password": "bad-password-1"}
        )
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"username": "nurse.lock", "password": PASSWORD})
    assert (
        r.status_code == 423
        and r.json()["error"]["code"] == "ACCOUNT_LOCKED"
        and "locked_until" in r.json()["error"]["details"]
    )
    assert (await admin.post(f"/users/{u.id}/unlock")).status_code == 200
    assert (
        await client.post("/api/v1/auth/login", json={"username": "nurse.lock", "password": PASSWORD})
    ).status_code == 200
    async with dbs.get_sessionmaker()() as s:
        n = (await s.execute(select(AuditLog).where(AuditLog.action == "login_failed"))).scalars().all()
        assert len(n) >= 6


async def test_suspended_user_cannot_login(client):
    await create_user(UserRole.nurse, "nurse.susp", status="suspended")
    r = await client.post("/api/v1/auth/login", json={"username": "nurse.susp", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


async def test_refresh_rotation_and_reuse_detection(client):
    await create_user(UserRole.doctor, "dr.rot")
    await client.post("/api/v1/auth/login", json={"username": "dr.rot", "password": PASSWORD})
    old = client.cookies.get("cp_refresh")
    client.cookies.clear()

    async def refresh(tok):
        return await client.post("/api/v1/auth/refresh", headers={"Cookie": f"cp_refresh={tok}"})

    r2 = await refresh(old)
    assert r2.status_code == 200 and r2.json()["access_token"]
    new = r2.cookies.get("cp_refresh")
    assert new and new != old
    # grace window: same old token within 10 s returns the SAME successor (parallel tabs)
    r3 = await refresh(old)
    assert r3.status_code == 200 and r3.cookies.get("cp_refresh") == new
    # after the grace window the old token is a reuse -> entire family revoked
    from app.core.kv import get_kv

    await get_kv().delete(f"refresh:grace:{security.sha256_hex(old)}")
    r4 = await refresh(old)
    assert r4.status_code == 401 and r4.json()["error"]["code"] == "TOKEN_REUSE_DETECTED"
    r5 = await refresh(new)
    assert r5.status_code == 401  # successor also dead
    async with dbs.get_sessionmaker()() as s:
        acts = {a.action.value for a in (await s.execute(select(AuditLog))).scalars()}
        assert "token_reuse_detected" in acts
        toks = (await s.execute(select(RefreshToken))).scalars().all()
        assert all(t.revoked_at for t in toks)


async def test_refresh_rejects_foreign_origin(client):
    await create_user(UserRole.doctor, "dr.org")
    await client.post("/api/v1/auth/login", json={"username": "dr.org", "password": PASSWORD})
    r = await client.post("/api/v1/auth/refresh", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def _forge(sub: str, alg: str = "HS256", secret: str | None = None, **claims):
    s = get_settings()
    now = int(time.time())
    p = {
        "sub": sub,
        "role": "admin",
        "jti": "x",
        "iat": now,
        "exp": now + 600,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "sv": 1,
        **claims,
    }
    return jwt.encode(p, secret or s.jwt_secret, algorithm=alg)


async def test_jwt_attacks(client):
    u = await create_user(UserRole.admin, "adm.jwt")
    uid = str(u.id)
    none_tok = jwt.encode(
        {"sub": uid, "iss": "cardiopcg", "aud": "cardiopcg-web", "sv": 1, "iat": 1, "exp": 4102444800},
        None,
        algorithm="none",
    )
    for tok in (
        none_tok,
        _forge(uid, secret="wrong-secret-wrong-secret-wrong-secret"),
        _forge(uid, exp=1),
        _forge(uid, aud="other"),
    ):
        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, tok
    ok = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {_forge(uid)}"})
    assert ok.status_code == 200
    old_sv = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {_forge(uid, sv=0)}"})
    assert old_sv.status_code == 401  # security_version mismatch


async def test_change_password_policy(client, doctor):
    r = await doctor.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "WEAK_PASSWORD"
    r = await doctor.post(
        "/auth/change-password", json={"current_password": "nope", "new_password": "N3w-Long-Pass-2026-xq"}
    )
    assert r.json()["error"]["code"] == "WRONG_CURRENT_PASSWORD"
    r = await doctor.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD}
    )
    assert r.status_code == 400  # reuse
    r = await doctor.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": "N3w-Long-Pass-2026-xq"}
    )
    assert r.status_code == 204
    assert (
        await client.post(
            "/api/v1/auth/login", json={"username": "doctor.main", "password": "N3w-Long-Pass-2026-xq"}
        )
    ).status_code == 200


async def test_admin_reset_password_flow(client, admin):
    u = await create_user(UserRole.nurse, "nurse.reset")
    r = await admin.post(f"/users/{u.id}/reset-password", json={"mode": "link"})
    assert r.status_code == 200
    tok = r.json()["reset_token"]
    r2 = await client.post(
        "/api/v1/auth/reset-password", json={"token": tok, "new_password": "Fresh-Reset-Pass-77!"}
    )
    assert r2.status_code == 204
    assert (
        await client.post(
            "/api/v1/auth/reset-password", json={"token": tok, "new_password": "Fresh-Reset-Pass-88!"}
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/auth/login", json={"username": "nurse.reset", "password": "Fresh-Reset-Pass-77!"}
        )
    ).status_code == 200


async def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    reset_settings_cache()
    await create_user(UserRole.nurse, "nurse.rl")
    # per-username: 5/min
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"username": "same.user", "password": "whatever-pass"}
            )
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    # per-IP: 10/min across usernames
    r = None
    for i in range(12):
        r = await client.post(
            "/api/v1/auth/login", json={"username": f"user{i}", "password": "whatever-pass"}
        )
    assert r.status_code == 429 and r.headers["retry-after"] and r.json()["error"]["code"] == "RATE_LIMITED"
    reset_settings_cache()


async def test_timing_unknown_vs_known_user_similar(client):
    await create_user(UserRole.nurse, "nurse.time")
    security._hasher = security.PasswordHasher(time_cost=2, memory_cost=16384, parallelism=1)
    security._DUMMY_HASH = None
    try:
        await create_user(UserRole.nurse, "nurse.time2")  # prime

        def avg(fn):
            return fn

        async def t(name):
            t0 = time.perf_counter()
            await client.post("/api/v1/auth/login", json={"username": name, "password": "wrong-password-x"})
            return time.perf_counter() - t0

        for _ in range(2):
            await t("ghost")
        known = sorted([await t("nurse.time2") for _ in range(5)])[2]
        unknown = sorted([await t("ghost") for _ in range(5)])[2]
        assert abs(known - unknown) / max(known, unknown) < 0.5  # no user-enumeration timing oracle
    finally:
        security._hasher = security.PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
        security._DUMMY_HASH = None
        _ = avg


async def test_error_envelope_and_security_headers(client):
    r = await client.get("/api/v1/examinations")
    assert r.status_code == 401
    e = r.json()["error"]
    assert e["code"] == "UNAUTHENTICATED" and e["request_id"] == r.headers["x-request-id"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    r = await client.post("/api/v1/auth/login", json={"username": "x"})
    assert (
        r.status_code == 422
        and r.json()["error"]["code"] == "VALIDATION_ERROR"
        and r.json()["error"]["details"][0]["field"] == "password"
    )


async def test_cors_preflight_only_allowed_origin(client):
    ok = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    bad = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


async def test_json_body_limit(client):
    r = await client.post(
        "/api/v1/auth/login",
        content=b"{" + b" " * 1_100_000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


async def test_no_pii_secret_columns_in_user_row(client):
    await create_user(UserRole.nurse, "nurse.row")
    async with dbs.get_sessionmaker()() as s:
        h = (await s.execute(select(User.password_hash).where(User.username == "nurse.row"))).scalar_one()
        assert h.startswith("$argon2id$") and PASSWORD not in h
    _ = text, pytest

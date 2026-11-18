"""Shared helpers for backend tests (not fixtures)."""

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
from httpx import AsyncClient

from app.core.security import hash_password
from app.db import session as dbs
from app.db.base import utcnow
from app.models.enums import UserRole, UserStatus
from app.models.user import User

BACKEND = Path(__file__).resolve().parent.parent
INFRA = os.environ.get("TEST_INFRA") == "1"  # real Redis + MinIO containers
PASSWORD = "Str0ng-Test-Pass-2026!"


class Actor:
    def __init__(self, user: User, client: AsyncClient, token: str) -> None:
        self.user, self.client, self.token, self.id = user, client, token, user.id

    @property
    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def req(self, method: str, url: str, **kw):
        headers = {**self.h, **kw.pop("headers", {})}
        return await self.client.request(method, "/api/v1" + url, headers=headers, **kw)

    async def get(self, url, **kw):
        return await self.req("GET", url, **kw)

    async def post(self, url, **kw):
        return await self.req("POST", url, **kw)

    async def patch(self, url, **kw):
        return await self.req("PATCH", url, **kw)

    async def put(self, url, **kw):
        return await self.req("PUT", url, **kw)

    async def delete(self, url, **kw):
        return await self.req("DELETE", url, **kw)


async def create_user(role: UserRole, username: str | None = None, **kw) -> User:
    username = username or f"{role.value}.{uuid.uuid4().hex[:6]}"
    async with dbs.get_sessionmaker()() as s:
        u = User(
            username=username,
            password_hash=hash_password(PASSWORD),
            full_name=kw.pop("full_name", f"{role.value.title()} {username}"),
            role=role,
            status=kw.pop("status", UserStatus.active),
            password_changed_at=utcnow(),
            **kw,
        )
        s.add(u)
        await s.commit()
        return u


async def login_as(client: AsyncClient, user: User) -> Actor:
    r = await client.post("/api/v1/auth/login", json={"username": user.username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return Actor(user, client, r.json()["access_token"])


# ----------------------------------------------------------------------------- data helpers
def make_wav(
    seconds: float = 8.0,
    sr: int = 4000,
    amp: float = 0.5,
    silent: bool = False,
    clip: bool = False,
    seed: int = 1,
) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    rng = np.random.default_rng(seed)
    x = np.zeros_like(t)
    for beat in np.arange(0.2, seconds, 0.8):
        for off, f in ((0.0, 60), (0.3, 80)):
            m = (t >= beat + off) & (t < beat + off + 0.08)
            x[m] += np.sin(2 * np.pi * f * (t[m] - beat)) * np.hanning(m.sum())
    x = x / (np.abs(x).max() + 1e-9) * amp + rng.normal(0, 0.01, x.shape)
    if silent:
        x = np.zeros_like(t)
    if clip:
        x = np.clip(x * 20, -1, 1)
    buf = io.BytesIO()
    sf.write(buf, x.astype("float32"), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def make_flac(seconds: float = 8.0, seed: int = 2) -> bytes:
    raw = sf.read(io.BytesIO(make_wav(seconds, seed=seed)))
    buf = io.BytesIO()
    sf.write(buf, raw[0], raw[1], format="FLAC")
    return buf.getvalue()


async def new_patient(actor: Actor, **kw) -> dict:
    body = {
        "last_name": "Rahimov",
        "first_name": "Jasur",
        "birth_date": "1975-04-12",
        "gender": "male",
        "ai_consent": True,
        **kw,
    }
    r = await actor.post("/patients?force=true", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def new_exam(actor: Actor, patient_id: str, **kw) -> dict:
    r = await actor.post("/examinations", json={"patient_id": patient_id, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def upload(
    actor: Actor, exam_id: str, data: bytes | None = None, site: str = "mitral", name: str = "a.wav", **params
):
    data = data if data is not None else make_wav()
    return await actor.post(
        f"/examinations/{exam_id}/recordings",
        files={"file": (name, data, "audio/wav")},
        data={"site": site},
        params=params,
    )


async def ready_exam(nurse: Actor, sites=("mitral",)) -> tuple[dict, dict]:
    p = await new_patient(nurse)
    e = await new_exam(nurse, p["id"])
    for i, s in enumerate(sites):
        r = await upload(nurse, e["id"], make_wav(seed=10 + i), site=s, name=f"{s}.wav")
        assert r.status_code == 201, r.text
    return p, e


async def run_analysis(actor: Actor, exam_id: str) -> str:
    """analyze via API then execute the job synchronously (JOB_RUNNER=none in tests)."""
    from app.services import analysis_service

    r = await actor.post(f"/examinations/{exam_id}/analyze")
    assert r.status_code == 202, r.text
    return await analysis_service.run_job(r.json()["job_id"])

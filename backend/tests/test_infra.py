"""Checks that need the real infrastructure: run with TEST_INFRA=1 (Redis + MinIO containers)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading

import pytest
from support import BACKEND, INFRA, make_wav, new_exam, new_patient, upload

from app.config import get_settings, reset_settings_cache
from app.core import kv
from app.services import realtime
from app.services.storage import S3Storage, get_storage

pytestmark = pytest.mark.skipif(not INFRA, reason="set TEST_INFRA=1 (needs Docker: redis + minio)")


async def test_real_backends_are_in_use():
    assert isinstance(get_storage(), S3Storage) and isinstance(kv.get_kv(), kv.RedisKV)
    assert await kv.get_kv().ping()
    assert await get_storage().ping()
    await get_storage().put_bytes("exams/x/y/t.bin", b"0123456789", "application/octet-stream")
    assert [c async for c in get_storage().iter_range("exams/x/y/t.bin", 2, 5)] == [b"2345"]
    assert await get_storage().size("exams/x/y/t.bin") == 10
    await get_storage().delete("exams/x/y/t.bin")
    assert not await get_storage().exists("exams/x/y/t.bin")


async def test_redis_pubsub_bridge_and_streams():
    """A second 'process' (separate bus instance) sees events through Redis pub/sub; SSE history uses a Redis stream."""
    other = realtime.EventBus()
    sub = other.subscribe(["exam:XR1"])
    await other.start_listener()
    try:
        await asyncio.sleep(0.3)
        env = await realtime.bus.publish("analysis.progress", {"n": 1}, ["exam:XR1"])
        got = await asyncio.wait_for(sub.queue.get(), 3)
        assert got["id"] == env["id"]
        env2 = await realtime.bus.publish("analysis.progress", {"n": 2}, ["exam:XR1"])
        hist = await realtime.bus.history("XR1", env["id"])
        assert [h["id"] for h in hist] == [env2["id"]]
    finally:
        await other.stop()


async def test_refresh_grace_and_rate_limit_use_redis(client):
    from support import PASSWORD, create_user

    from app.models.enums import UserRole

    await create_user(UserRole.nurse, "redis.nurse")
    r = await client.post("/api/v1/auth/login", json={"username": "redis.nurse", "password": PASSWORD})
    old = client.cookies.get("cp_refresh")
    client.cookies.clear()
    ok = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"cp_refresh={old}"})
    again = await client.post("/api/v1/auth/refresh", headers={"Cookie": f"cp_refresh={old}"})
    assert r.status_code == ok.status_code == again.status_code == 200
    assert again.cookies.get("cp_refresh") == ok.cookies.get("cp_refresh")


async def test_celery_worker_end_to_end(nurse, doctor, monkeypatch):
    """Real Celery worker (Redis broker) + real engine (app.ml) + Postgres + MinIO; events cross processes via Redis."""
    monkeypatch.setenv("JOB_RUNNER", "celery")
    reset_settings_cache()
    assert get_settings().job_runner == "celery"
    env = {**os.environ, "JOB_RUNNER": "celery", "DEEPSEEK_API_KEY": "", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(  # noqa: ASYNC220
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.workers.celery_app",
            "worker",
            "-Q",
            "analysis,default,exports,llm",
            "--pool=solo",
            "-l",
            "info",
        ],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []
    threading.Thread(target=lambda: [lines.append(ln) for ln in proc.stdout], daemon=True).start()
    try:
        for _ in range(120):
            if any("ready." in ln for ln in lines):
                break
            assert proc.poll() is None, "".join(lines[-30:])
            await asyncio.sleep(0.5)
        else:
            pytest.fail("celery worker did not start:\n" + "".join(lines[-30:]))
        await realtime.bus.start_listener()
        p = await new_patient(nurse)
        e = await new_exam(nurse, p["id"], assigned_doctor_id=str(doctor.id))
        assert (await upload(nurse, e["id"], make_wav(10.0), site="apex")).status_code == 201
        sub = realtime.bus.subscribe([f"exam:{e['id']}"])
        r = await nurse.post(f"/examinations/{e['id']}/analyze")
        assert r.status_code == 202
        status = None
        for _ in range(240):
            status = (await nurse.get(f"/examinations/{e['id']}/status")).json()
            if status["status"] in ("ai_ready", "failed", "in_review"):
                break
            await asyncio.sleep(0.5)
        assert status["status"] == "ai_ready", (status, "".join(lines[-40:]))
        assert status["job"]["progress_pct"] == 100
        events = []
        while not sub.queue.empty():
            events.append(sub.queue.get_nowait())
        types = {ev["type"] for ev in events}
        assert {
            "analysis.progress",
            "analysis.signal_done",
            "analysis.completed",
            "exam.status_changed",
        } <= types, types
        a = (await doctor.get(f"/examinations/{e['id']}/analysis")).json()
        assert a["recordings"][0]["spectrogram_url"]
        sp = await doctor.get(a["recordings"][0]["spectrogram_url"].removeprefix("/api/v1"))
        assert sp.content[:4] == b"\x89PNG"  # artifact stored by the worker in MinIO, read back by the API
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
        await realtime.bus.stop()
        monkeypatch.setenv("JOB_RUNNER", "none")
        reset_settings_cache()

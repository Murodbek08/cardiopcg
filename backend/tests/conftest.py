"""Test harness: real PostgreSQL 17 (testcontainers, Docker) + Alembic migrations + in-process ASGI client.

Redis is NOT started: the in-process KV fallback (MemoryKV) is used, so the Redis code path
(RedisKV, pub/sub bridge, streams) is not exercised by this suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

_TMP = tempfile.mkdtemp(prefix="cpcg-test-")
os.environ.update(
    {
        "APP_ENV": "test",
        "JOB_RUNNER": "none",
        "REDIS_URL": "",
        "RATE_LIMIT_ENABLED": "false",
        "ANALYTICS_CACHE_TTL": "0",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_DIR": os.path.join(_TMP, "storage"),
        "ANALYSIS_RETRY_BACKOFF_SEC": "0,0,0",
        "ALLOWED_ORIGINS": "http://localhost:5173",
        "ALLOWED_HOSTS": "*",
        "PUBLIC_URL": "http://localhost:5173",
        "DEEPSEEK_API_KEY": "",
    }
)

from argon2 import PasswordHasher  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from support import INFRA, create_user, login_as  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402
from app.core import kv, security  # noqa: E402
from app.db import session as dbs  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services import realtime  # noqa: E402
from app.services.analysis_port import set_analysis_service  # noqa: E402
from app.services.settings_service import SETTING_DEFS  # noqa: E402
from app.services.storage import init_storage  # noqa: E402

# cheap argon2 for tests (production parameters are asserted separately in test_auth)
security._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


@pytest.fixture(scope="session")
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", username="t", password="t", dbname="t") as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        yield f"postgresql+asyncpg://t:t@{host}:{port}/t"


@pytest.fixture(scope="session")
def infra():
    if not INFRA:
        yield None
        return
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    redis = DockerContainer("redis:7-alpine").with_exposed_ports(6379)
    minio = (
        DockerContainer("minio/minio:latest")
        .with_command("server /data")
        .with_env("MINIO_ROOT_USER", "testaccesskey")
        .with_env("MINIO_ROOT_PASSWORD", "testsecretkey123")
        .with_exposed_ports(9000)
    )
    with redis, minio:
        wait_for_logs(redis, "Ready to accept connections")
        wait_for_logs(minio, "API:")
        cfg = {
            "REDIS_URL": f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0",
            "CELERY_BROKER_URL": f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/1",
            "STORAGE_BACKEND": "s3",
            "S3_ENDPOINT": f"http://{minio.get_container_host_ip()}:{minio.get_exposed_port(9000)}",
            "S3_ACCESS_KEY": "testaccesskey",
            "S3_SECRET_KEY": "testsecretkey123",
            "S3_BUCKET_AUDIO": "pcg-audio",
            "S3_BUCKET_REPORTS": "pcg-reports",
        }
        os.environ.update(cfg)
        yield cfg


@pytest.fixture(scope="session", autouse=True)
def migrated(pg_url, infra):
    os.environ["DATABASE_URL"] = pg_url
    os.environ["ALEMBIC_DATABASE_URL"] = pg_url
    reset_settings_cache()
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    return pg_url


TABLES = (
    "pcg_segments, ai_reports, drug_recommendations, prescriptions, doctor_conclusions, analysis_results, analysis_jobs, "
    "exam_status_history, recordings, examinations, exam_counters, allergies, current_medications, medical_history, patients, "
    "notifications, refresh_tokens, password_reset_tokens, idempotency_keys, export_jobs, kb_drug_versions, kb_drugs, kb_interactions, kb_meta, system_settings, users"
)


@pytest_asyncio.fixture(scope="session")
async def engine(migrated):
    reset_settings_cache()
    eng = dbs.init_engine(get_settings())
    st = init_storage(get_settings())
    if INFRA:
        await st.ensure_buckets()
    async with eng.begin() as c:
        await c.execute(
            text("UPDATE system_settings SET value='false'::jsonb WHERE key='analysis.auto_start'")
        )
    yield eng
    await dbs.dispose_engine()


@pytest_asyncio.fixture(autouse=True)
async def clean(engine):
    kv.init_kv(get_settings().redis_url)
    if INFRA:
        await kv.get_redis().flushall()
    realtime.bus._subs.clear()
    realtime.bus._history.clear()
    set_analysis_service(None)
    yield
    async with engine.begin() as c:
        await c.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER USER"))
        await c.execute(text(f"TRUNCATE {TABLES}, audit_logs RESTART IDENTITY CASCADE"))  # noqa: S608
        await c.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER USER"))
        for k, d in SETTING_DEFS.items():
            await c.execute(
                text(
                    "INSERT INTO system_settings(key, value, value_type, description, is_public) VALUES (:k, CAST(:v AS jsonb), :t, :d, :p)"
                ),
                {
                    "k": k,
                    "v": __import__("json").dumps(False if k == "analysis.auto_start" else d.default),
                    "t": d.type,
                    "d": d.description,
                    "p": d.public,
                },
            )
    reset_settings_cache()
    os.environ["RATE_LIMIT_ENABLED"] = "false"


@pytest_asyncio.fixture
async def app(engine):
    from app.main import create_app

    return create_app(get_settings())


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin(client):
    return await login_as(client, await create_user(UserRole.admin, "admin.main", specialty=None))


@pytest_asyncio.fixture
async def doctor(client):
    return await login_as(
        client, await create_user(UserRole.doctor, "doctor.main", specialty="Kardiolog", license_no="L-1")
    )


@pytest_asyncio.fixture
async def doctor2(client):
    return await login_as(client, await create_user(UserRole.doctor, "doctor.two"))


@pytest_asyncio.fixture
async def nurse(client):
    return await login_as(client, await create_user(UserRole.nurse, "nurse.main"))


@pytest_asyncio.fixture
async def nurse2(client):
    return await login_as(client, await create_user(UserRole.nurse, "nurse.two"))

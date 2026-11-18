"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.core.errors import register_handlers
from app.core.kv import close_kv, init_kv
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_engine, init_engine
from app.services import realtime
from app.services.storage import init_storage

log = structlog.get_logger()


async def _seed_kb() -> None:
    """Load the YAML KB seed into the DB when the KB table is empty (drafts; idempotent)."""
    try:
        from sqlalchemy import func, select

        from app.db.session import get_sessionmaker
        from app.models.kb import KbDrug
        from app.services import kb_service

        async with get_sessionmaker()() as sess:
            if (await sess.execute(select(func.count()).select_from(KbDrug))).scalar_one() == 0:
                res = await kb_service.seed_from_yaml(sess)
                await sess.commit()
                log.info("kb_seeded", **res)
    except Exception as exc:  # table may not exist before migrations
        log.warning("kb_seed_skipped", error=str(exc))


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_engine(s)
        init_kv(s.redis_url)
        storage = init_storage(s)
        ensure = getattr(storage, "ensure_buckets", None)
        if ensure is not None:
            try:
                await ensure()
            except Exception as exc:  # pragma: no cover - storage may come up later
                log.warning("storage_bucket_check_failed", error=str(exc))
        await _seed_kb()
        await realtime.bus.start_listener()
        log.info(
            "startup",
            env=s.app_env,
            version=s.app_version,
            job_runner=s.job_runner,
            storage=s.storage_backend,
        )
        try:
            yield
        finally:
            await realtime.bus.stop()
            await dispose_engine()
            await close_kv()

    docs = s.docs_enabled and not s.is_prod
    app = FastAPI(
        title="CardioPCG AI API",
        version=s.app_version,
        description=(
            "CardioPCG AI backend. Clinical decision support only - not a certified medical device. "
            "Errors use a unified envelope: {error: {code, message, details, request_id}}."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    register_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "If-Match",
            "Idempotency-Key",
            "X-Request-ID",
            "Last-Event-ID",
        ],
        expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After", "ETag"],
    )
    if s.hosts and s.hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.hosts)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router)
    return app


def _lazy_app() -> FastAPI:
    return create_app()


# `uvicorn app.main:app` / gunicorn entrypoint
app = _lazy_app()

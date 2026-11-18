# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir "uv==0.13.9"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.13-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 libgl1 libglib2.0-0 curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app --gid 10001 && useradd -r -g app --uid 10001 -d /app -s /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mpl NUMBA_CACHE_DIR=/tmp/numba
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8000/api/v1/system/health || exit 1
# api: gunicorn+uvicorn. worker: celery -A app.workers.celery_app worker -Q analysis,llm,default,exports ; beat: celery -A app.workers.celery_app beat
# migrations (one-shot container before api): alembic upgrade head
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30", "--control-socket", "/tmp/gunicorn.ctl"]

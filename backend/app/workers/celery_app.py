"""Celery app: queues analysis / llm / default / exports; beat schedule for maintenance."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

_s = get_settings()
_broker = _s.celery_broker_url or _s.redis_url or "memory://"

celery_app = Celery(
    "cardiopcg",
    broker=_broker,
    backend=None,
    include=["app.workers.tasks_analysis", "app.workers.tasks_maintenance", "app.workers.tasks_export"],
)
celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "analysis.*": {"queue": "analysis"},
        "llm.*": {"queue": "llm"},
        "exports.*": {"queue": "exports"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 900},
    timezone="UTC",
    beat_schedule={
        "reap-stuck-jobs": {"task": "maintenance.reap_stuck_jobs", "schedule": 300.0},
        "cleanup-uploading-recordings": {
            "task": "maintenance.cleanup_uploading_recordings",
            "schedule": 3600.0,
        },
        "purge-expired-refresh-tokens": {
            "task": "maintenance.purge_expired_refresh_tokens",
            "schedule": crontab(hour=2, minute=10),
        },
        "purge-old-notifications": {
            "task": "maintenance.purge_old_notifications",
            "schedule": crontab(hour=2, minute=20),
        },
        "purge-raw-llm-responses": {
            "task": "maintenance.purge_raw_llm_responses",
            "schedule": crontab(hour=2, minute=30),
        },
        "purge-expired-exports": {"task": "maintenance.purge_expired_exports", "schedule": 3600.0},
    },
)

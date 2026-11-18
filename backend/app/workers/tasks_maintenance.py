from __future__ import annotations

from app.services import analysis_service, export_service, maintenance
from app.workers._run import run_async
from app.workers.celery_app import celery_app


@celery_app.task(name="maintenance.reap_stuck_jobs")
def reap_stuck_jobs() -> int:
    return run_async(analysis_service.reap_stuck_jobs)


@celery_app.task(name="maintenance.cleanup_uploading_recordings")
def cleanup_uploading_recordings() -> int:
    return run_async(maintenance.cleanup_uploading_recordings)


@celery_app.task(name="maintenance.purge_expired_refresh_tokens")
def purge_expired_refresh_tokens() -> int:
    return run_async(maintenance.purge_expired_refresh_tokens)


@celery_app.task(name="maintenance.purge_old_notifications")
def purge_old_notifications() -> int:
    return run_async(maintenance.purge_old_notifications)


@celery_app.task(name="maintenance.purge_raw_llm_responses")
def purge_raw_llm_responses() -> int:
    return run_async(maintenance.purge_raw_llm_responses)


@celery_app.task(name="maintenance.purge_expired_exports")
def purge_expired_exports() -> int:
    return run_async(export_service.purge_expired_exports)

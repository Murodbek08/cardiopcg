from __future__ import annotations

from app.services import export_service
from app.workers._run import run_async
from app.workers.celery_app import celery_app


@celery_app.task(name="exports.run_export", acks_late=True)
def run_export(job_id: str) -> str:
    return run_async(export_service.run_export_job, job_id)

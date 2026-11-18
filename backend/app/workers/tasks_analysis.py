from __future__ import annotations

from app.services import analysis_service
from app.workers._run import run_async
from app.workers.celery_app import celery_app


@celery_app.task(name="analysis.analyze_examination", bind=True, acks_late=True, max_retries=0)
def analyze_examination(self, job_id: str) -> str:
    """Delegates to analysis_service.run_job (idempotent; retries/backoff handled inside)."""
    return run_async(analysis_service.run_job, job_id)

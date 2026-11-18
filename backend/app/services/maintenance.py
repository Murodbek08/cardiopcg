"""Periodic maintenance jobs (Celery beat wrappers live in app/workers/tasks_maintenance.py)."""

from __future__ import annotations

import contextlib
from datetime import timedelta

from sqlalchemy import delete, select, update

from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.models.clinical import AiReport
from app.models.enums import RecordingStatus
from app.models.recording import Recording
from app.models.system import Notification
from app.models.user import PasswordResetToken, RefreshToken
from app.services import settings_service
from app.services.storage import get_storage


async def cleanup_uploading_recordings(max_age_minutes: int = 60) -> int:
    """Dangling uploading rows older than 1 hour: delete the row and best-effort remove the stored object."""
    n = 0
    async with get_sessionmaker()() as s:
        rows = (
            (
                await s.execute(
                    select(Recording).where(
                        Recording.status == RecordingStatus.uploading,
                        Recording.created_at < utcnow() - timedelta(minutes=max_age_minutes),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            with contextlib.suppress(Exception):
                await get_storage().delete(r.storage_key)
            await s.delete(r)
            n += 1
        await s.commit()
    return n


async def purge_expired_refresh_tokens() -> int:
    async with get_sessionmaker()() as s:
        res = await s.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < utcnow() - timedelta(days=1))
        )
        await s.execute(
            delete(PasswordResetToken).where(PasswordResetToken.expires_at < utcnow() - timedelta(days=1))
        )
        await s.commit()
        return res.rowcount or 0


async def purge_old_notifications(days: int = 90) -> int:
    async with get_sessionmaker()() as s:
        res = await s.execute(
            delete(Notification).where(
                Notification.is_read, Notification.read_at < utcnow() - timedelta(days=days)
            )
        )
        await s.commit()
        return res.rowcount or 0


async def purge_raw_llm_responses() -> int:
    async with get_sessionmaker()() as s:
        days = await settings_service.get_value(s, "retention.raw_llm_days")
        res = await s.execute(
            update(AiReport)
            .where(
                AiReport.raw_response.is_not(None), AiReport.created_at < utcnow() - timedelta(days=int(days))
            )
            .values(raw_response=None)
        )
        await s.commit()
        return res.rowcount or 0

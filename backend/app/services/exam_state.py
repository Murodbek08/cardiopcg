"""Examination status state machine (doc 01 section 5). Single entry point: ``transition``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, invalid_state
from app.db.base import utcnow
from app.models.enums import AuditAction, ExamStatus, UserRole
from app.models.examination import Examination, ExamStatusHistory
from app.services import audit_service, realtime

S = ExamStatus
SYSTEM = "system"
WORKER = "worker"
ALL_ROLES = {"admin", "doctor", "nurse"}
DOC_ADMIN = {"admin", "doctor"}

# (from, to) -> actors allowed. 'system' = internal automatic transitions, 'worker' = analysis worker.
TRANSITIONS: dict[tuple[ExamStatus, ExamStatus], set[str]] = {
    (S.draft, S.uploaded): {SYSTEM},
    (S.uploaded, S.draft): {SYSTEM},
    (S.uploaded, S.queued): ALL_ROLES | {SYSTEM},
    (S.queued, S.processing): {WORKER},
    (S.processing, S.ai_ready): {WORKER},
    (S.processing, S.failed): {WORKER},
    (S.failed, S.queued): DOC_ADMIN | {WORKER},
    (S.ai_ready, S.in_review): {"doctor", SYSTEM},
    (S.in_review, S.completed): {"doctor"},
    (S.ai_ready, S.queued): DOC_ADMIN,
    (S.in_review, S.queued): DOC_ADMIN,
    (S.draft, S.cancelled): ALL_ROLES,
    (S.uploaded, S.cancelled): ALL_ROLES,
    (S.failed, S.cancelled): DOC_ADMIN,
    (S.queued, S.cancelled): DOC_ADMIN,
    (S.processing, S.cancelled): DOC_ADMIN,
    (S.ai_ready, S.cancelled): DOC_ADMIN,
    (S.in_review, S.cancelled): DOC_ADMIN,
}

TERMINAL = {S.completed, S.cancelled}


def allowed_targets(current: ExamStatus, actor_key: str) -> list[str]:
    return sorted(t.value for (f, t), who in TRANSITIONS.items() if f == current and actor_key in who)


def _actor_key(actor: Any | None, system: bool, worker: bool) -> str:
    if worker:
        return WORKER
    if actor is None or system:
        return SYSTEM
    return actor.role.value if isinstance(actor.role, UserRole) else str(actor.role)


async def lock_exam(db: AsyncSession, exam_id) -> Examination:
    await db.flush()  # autoflush is off: persist pending changes before populate_existing reloads the row
    res = await db.execute(
        select(Examination)
        .where(Examination.id == exam_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return res.scalar_one()


async def transition(
    db: AsyncSession,
    exam: Examination,
    to: ExamStatus,
    actor: Any | None = None,
    reason: str | None = None,
    *,
    system: bool = False,
    worker: bool = False,
) -> Examination:
    exam = await lock_exam(db, exam.id)
    current = exam.status
    key = _actor_key(actor, system, worker)
    rule = TRANSITIONS.get((current, to))
    if rule is None:
        raise invalid_state(current.value, allowed_targets(current, key))
    if key not in rule:
        # role not allowed for this transition (e.g. nurse trying to cancel a processing exam)
        raise AppError(
            403, "FORBIDDEN", "Bu o'tish uchun ruxsat yo'q", {"current": current.value, "to": to.value}
        )

    now = utcnow()
    exam.status = to
    exam.version += 1
    if to == S.cancelled:
        exam.cancel_reason = reason
    if to == S.completed:
        exam.completed_at = now
    if to == S.failed:
        exam.failure_reason = reason
    db.add(
        ExamStatusHistory(
            examination_id=exam.id,
            from_status=current,
            to_status=to,
            changed_by=getattr(actor, "id", None),
            reason=reason,
            created_at=now,
        )
    )
    audit_service.log_event(
        db,
        AuditAction.status_change,
        user=actor,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
        changes={"before": {"status": current.value}, "after": {"status": to.value}},
        meta={"reason": reason, "actor": key},
    )
    channels = [f"exam:{exam.id}", "role:doctor", "role:admin"]
    realtime.queue_event(
        db,
        "exam.status_changed",
        {
            "examination_id": str(exam.id),
            "from": current.value,
            "to": to.value,
            "by": str(actor.id) if actor is not None else None,
        },
        channels,
    )
    await db.flush()
    return exam

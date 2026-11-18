from __future__ import annotations

import hashlib
import uuid
from typing import Any

import orjson
from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import deny
from app.core.errors import AppError, conflict, invalid_state, unprocessable
from app.core.http import check_if_match
from app.core.kv import get_kv
from app.db.base import utcnow
from app.models.clinical import DoctorConclusion
from app.models.enums import (
    AgreementLevel,
    AuditAction,
    ConclusionStatus,
    ExamStatus,
    NotificationType,
)
from app.models.examination import Examination
from app.models.user import User
from app.schemas.clinical import AmendIn, ConclusionIn
from app.services import audit_service, notification_service, prescription_service, realtime
from app.services.exam_service import current_analysis, current_conclusion, open_for_review
from app.services.exam_state import lock_exam, transition


async def invalidate_analytics() -> None:
    await get_kv().delete_prefix("analytics:")


async def ensure_doctor_scope(doctor: User, exam: Examination) -> None:
    """A doctor may work on an exam if it is assigned to them or not assigned to anyone."""
    if exam.assigned_doctor_id and exam.assigned_doctor_id != doctor.id:
        await deny(doctor, "conclusion:write", f"examination:{exam.id}")


def _hash(c: DoctorConclusion, exam: Examination, doctor: User, signed_at) -> str:
    payload = {
        "exam": str(exam.id),
        "doctor": str(doctor.id),
        "diagnosis_text": c.diagnosis_text,
        "icd10": c.icd10_codes,
        "final_pcg_class": c.final_pcg_class.value,
        "final_severity": c.final_severity.value,
        "agreement": c.agreement_with_ai.value,
        "disagreement_reason": c.disagreement_reason,
        "recommendations": c.recommendations,
        "follow_up_date": c.follow_up_date.isoformat() if c.follow_up_date else None,
        "referred_to": c.referred_to,
        "signed_at": signed_at.isoformat(),
    }
    return hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _fields(data: ConclusionIn) -> dict[str, Any]:
    return {
        "diagnosis_text": data.diagnosis_text,
        "icd10_codes": data.icd10_codes,
        "final_pcg_class": data.final_pcg_class,
        "final_severity": data.final_severity,
        "agreement_with_ai": data.agreement_with_ai,
        "disagreement_reason": data.disagreement_reason,
        "recommendations": data.recommendations,
        "follow_up_date": data.follow_up_date,
        "follow_up_notes": data.follow_up_notes,
        "referred_to": data.referred_to,
    }


async def put_draft(
    db: AsyncSession, request: Request, exam: Examination, doctor: User, data: ConclusionIn
) -> DoctorConclusion:
    await ensure_doctor_scope(doctor, exam)
    exam = await lock_exam(db, exam.id)
    if exam.status not in (ExamStatus.ai_ready, ExamStatus.in_review):
        raise invalid_state(
            exam.status.value,
            ["ai_ready", "in_review"],
            "Xulosa qoralamasi faqat AI tahlili tayyor bo'lganda saqlanadi",
        )
    if await current_analysis(db, exam.id) is None:
        raise unprocessable("NO_ANALYSIS", "Signal tahlili natijasi yo'q")
    exam = await open_for_review(db, exam, doctor)
    cur = await current_conclusion(db, exam.id)
    fields = _fields(data)
    if cur is None:
        c = DoctorConclusion(
            examination_id=exam.id,
            doctor_id=doctor.id,
            status=ConclusionStatus.draft,
            is_current=True,
            **fields,
        )
        db.add(c)
        await db.flush()
        audit_service.log_event(
            db,
            AuditAction.create,
            user=doctor,
            resource_type="conclusion",
            resource_id=c.id,
            patient_id=exam.patient_id,
        )
        return c
    if cur.status != ConclusionStatus.draft:
        raise invalid_state(
            cur.status.value, [], "Imzolangan xulosa o'zgarmaydi; tuzatish uchun amend ishlating"
        )
    check_if_match(request, cur.version)
    before = {k: getattr(cur, k) for k in fields}
    for k, v in fields.items():
        setattr(cur, k, v)
    cur.doctor_id = doctor.id
    cur.version += 1
    audit_service.log_event(
        db,
        AuditAction.update,
        user=doctor,
        resource_type="conclusion",
        resource_id=cur.id,
        patient_id=exam.patient_id,
        changes=audit_service.diff(before, fields),
    )
    return cur


async def sign(db: AsyncSession, exam: Examination, doctor: User) -> tuple[DoctorConclusion, Examination]:
    await ensure_doctor_scope(doctor, exam)
    exam = await lock_exam(db, exam.id)
    if exam.status != ExamStatus.in_review:
        raise invalid_state(exam.status.value, ["in_review"])
    c = await current_conclusion(db, exam.id)
    if c is None or c.status != ConclusionStatus.draft:
        raise unprocessable("NO_CONCLUSION_DRAFT", "Imzolash uchun xulosa qoralamasi yo'q")
    if not c.diagnosis_text.strip() or not c.recommendations.strip():
        raise unprocessable(
            "VALIDATION_ERROR",
            "diagnosis_text va recommendations bo'sh bo'lmasligi kerak",
            [{"field": "recommendations", "msg": "required to sign", "type": "value_error"}],
        )
    if c.agreement_with_ai != AgreementLevel.agree and not (
        c.disagreement_reason and c.disagreement_reason.strip()
    ):
        raise unprocessable("DISAGREEMENT_REASON_REQUIRED", "AI bilan mos kelmaslik sababi majburiy")
    rx = await prescription_service.get_prescription(db, exam.id)
    if rx is not None and prescription_service.has_undecided(await prescription_service.items_of(db, rx)):
        raise conflict("PRESCRIPTION_PENDING", "Barcha dori satrlari tasdiqlanishi yoki rad etilishi kerak")
    now = utcnow()
    c.status = ConclusionStatus.signed
    c.signed_at = now
    c.doctor_id = doctor.id
    c.signature_hash = _hash(c, exam, doctor, now)
    c.version += 1
    exam.assigned_doctor_id = exam.assigned_doctor_id or doctor.id
    exam = await transition(db, exam, ExamStatus.completed, doctor, "conclusion signed")
    audit_service.log_event(
        db,
        AuditAction.sign,
        user=doctor,
        resource_type="conclusion",
        resource_id=c.id,
        patient_id=exam.patient_id,
        meta={"signature_hash": c.signature_hash},
    )
    await notification_service.notify(
        db,
        exam.performed_by,
        NotificationType.conclusion_signed,
        f"Xulosa imzolandi: {exam.exam_no}",
        None,
        {"examination_id": str(exam.id), "patient_id": str(exam.patient_id)},
    )
    realtime.queue_event(
        db,
        "conclusion.signed",
        {"examination_id": str(exam.id), "doctor_id": str(doctor.id), "signed_at": now.isoformat()},
        [f"exam:{exam.id}", f"user:{exam.performed_by}"],
    )
    realtime.after_commit(db, invalidate_analytics)
    return c, exam


async def amend(db: AsyncSession, exam: Examination, doctor: User, data: AmendIn) -> DoctorConclusion:
    await ensure_doctor_scope(doctor, exam)
    exam = await lock_exam(db, exam.id)
    if exam.status != ExamStatus.completed:
        raise invalid_state(exam.status.value, ["completed"], "Tuzatish faqat imzolangan xulosa uchun")
    cur = await current_conclusion(db, exam.id)
    if cur is None or cur.status not in (ConclusionStatus.signed, ConclusionStatus.amended):
        raise unprocessable("NO_SIGNED_CONCLUSION", "Tuzatish uchun imzolangan xulosa yo'q")
    if data.agreement_with_ai != AgreementLevel.agree and not (
        data.disagreement_reason and data.disagreement_reason.strip()
    ):
        raise unprocessable("DISAGREEMENT_REASON_REQUIRED", "AI bilan mos kelmaslik sababi majburiy")
    await db.execute(update(DoctorConclusion).where(DoctorConclusion.id == cur.id).values(is_current=False))
    await db.flush()
    now = utcnow()
    fields = _fields(data)
    new = DoctorConclusion(
        examination_id=exam.id,
        doctor_id=doctor.id,
        status=ConclusionStatus.amended,
        is_current=True,
        amends_id=cur.id,
        amend_reason=data.amend_reason,
        signed_at=now,
        version=cur.version + 1,
        **fields,
    )
    db.add(new)
    await db.flush()
    new.signature_hash = _hash(new, exam, doctor, now)
    audit_service.log_event(
        db,
        AuditAction.sign,
        user=doctor,
        resource_type="conclusion",
        resource_id=new.id,
        patient_id=exam.patient_id,
        meta={"amends": str(cur.id), "reason": data.amend_reason, "signature_hash": new.signature_hash},
        changes=audit_service.diff({k: getattr(cur, k) for k in fields}, fields),
    )
    realtime.queue_event(
        db,
        "conclusion.signed",
        {
            "examination_id": str(exam.id),
            "doctor_id": str(doctor.id),
            "signed_at": now.isoformat(),
            "amended": True,
        },
        [f"exam:{exam.id}", f"user:{exam.performed_by}"],
    )
    realtime.after_commit(db, invalidate_analytics)
    return new


async def history(db: AsyncSession, exam_id: uuid.UUID) -> list[DoctorConclusion]:
    return list(
        (
            await db.execute(
                select(DoctorConclusion)
                .where(DoctorConclusion.examination_id == exam_id)
                .order_by(DoctorConclusion.created_at)
            )
        ).scalars()
    )


_ = AppError

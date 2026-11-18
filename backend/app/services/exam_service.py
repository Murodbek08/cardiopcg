from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import deny
from app.core.errors import AppError, not_found
from app.core.permissions import Permission, has_permission
from app.db.base import utcnow
from app.models.analysis import AnalysisJob, AnalysisResult
from app.models.clinical import AiReport, DoctorConclusion
from app.models.enums import (
    ConclusionStatus,
    ExamStatus,
    NotificationType,
    RecordingKind,
    UserRole,
    UserStatus,
)
from app.models.examination import ExamCounter, Examination, ExamStatusHistory
from app.models.patient import Patient
from app.models.recording import Recording
from app.models.user import User
from app.services import notification_service, patient_service, realtime
from app.services.exam_state import transition

TASHKENT = ZoneInfo("Asia/Tashkent")

DISCLAIMER_AI = (
    "Bu natija sun'iy intellekt tomonidan hosil qilingan qaror qo'llab-quvvatlash vositasi; "
    "yakuniy tashxisni shifokor qo'yadi."
)
DISCLAIMER_RX = "AI taklifi. Faqat ma'lumot uchun; shifokor tasdiqlaydi."


async def next_exam_no(db: AsyncSession) -> str:
    day = datetime.now(TASHKENT).date()
    stmt = (
        pg_insert(ExamCounter)
        .values(day=day, last=1)
        .on_conflict_do_update(index_elements=[ExamCounter.day], set_={"last": ExamCounter.last + 1})
        .returning(ExamCounter.last)
    )
    n = (await db.execute(stmt)).scalar_one()
    return f"E-{day:%Y%m%d}-{n:04d}"


async def load_exam(db: AsyncSession, exam_id: uuid.UUID, *, include_deleted: bool = False) -> Examination:
    e = await db.get(Examination, exam_id)
    if e is None or (e.deleted_at is not None and not include_deleted):
        raise not_found("Tekshiruv")
    return e


async def can_view_exam(db: AsyncSession, user: User, exam: Examination) -> bool:
    if user.role != UserRole.nurse:
        return True
    if exam.performed_by == user.id:
        return True
    created_by = (
        await db.execute(select(Patient.created_by).where(Patient.id == exam.patient_id))
    ).scalar_one_or_none()
    return created_by == user.id


async def get_exam_for(db: AsyncSession, user: User, exam_id: uuid.UUID) -> Examination:
    """Load an exam and enforce object-level visibility (nurse: own exams / own patients)."""
    exam = await load_exam(db, exam_id)
    if not await can_view_exam(db, user, exam):
        await deny(user, "exam:read", f"examination:{exam_id}")
    return exam


def nurse_scope(user: User):
    """SQL condition limiting examinations for nurses (requires Patient joined)."""
    return (Examination.performed_by == user.id) | (Patient.created_by == user.id)


async def valid_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> User:
    d = await db.get(User, doctor_id)
    if d is None or d.deleted_at is not None or d.role != UserRole.doctor or d.status != UserStatus.active:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Shifokor topilmadi yoki faol emas",
            [{"field": "assigned_doctor_id", "msg": "invalid doctor", "type": "value_error"}],
        )
    return d


async def assign_doctor(db: AsyncSession, exam: Examination, doctor_id: uuid.UUID, by: User) -> None:
    doctor = await valid_doctor(db, doctor_id)
    exam.assigned_doctor_id = doctor.id
    exam.version += 1
    patient = await db.get(Patient, exam.patient_id)
    await notification_service.notify(
        db,
        doctor.id,
        NotificationType.assignment,
        f"Sizga tekshiruv biriktirildi: {exam.exam_no}",
        f"{patient_service.full_name(patient)}" if patient else None,
        {"examination_id": str(exam.id), "patient_id": str(exam.patient_id)},
    )
    realtime.queue_event(
        db, "exam.assigned", {"examination_id": str(exam.id), "by": str(by.id)}, [f"user:{doctor.id}"]
    )


async def open_for_review(db: AsyncSession, exam: Examination, doctor: User) -> Examination:
    """ai_ready -> in_review when a doctor opens the report/conclusion (auto-assign if unassigned)."""
    if exam.status == ExamStatus.ai_ready:
        if exam.assigned_doctor_id is None:
            exam.assigned_doctor_id = doctor.id
        exam.reviewed_by = doctor.id
        exam = await transition(db, exam, ExamStatus.in_review, doctor, "opened by doctor")
    return exam


# --------------------------------------------------------------------------------- serialization
def person(u: User | None) -> dict[str, Any] | None:
    return {"id": u.id, "full_name": u.full_name} if u else None


async def users_map(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, User]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


def recording_dict(r: Recording) -> dict[str, Any]:
    d = {
        c: getattr(r, c)
        for c in (
            "id",
            "examination_id",
            "kind",
            "site",
            "status",
            "original_filename",
            "mime_type",
            "ext",
            "size_bytes",
            "sha256",
            "duration_sec",
            "sample_rate_hz",
            "channels",
            "bit_depth",
            "codec",
            "width_px",
            "height_px",
            "snr_db",
            "quality_score",
            "validation_report",
            "scan_status",
            "notes",
            "derived_from_id",
            "created_at",
        )
    }
    for k in ("duration_sec", "snr_db", "quality_score"):
        d[k] = float(d[k]) if d[k] is not None else None
    d["url"] = f"/api/v1/recordings/{r.id}/file"
    return d


async def analysis_dict(db: AsyncSession, res: AnalysisResult | None) -> dict[str, Any] | None:
    if res is None:
        return None
    per_rec = []
    recs = (
        (
            await db.execute(
                select(Recording).where(
                    Recording.examination_id == res.examination_id,
                    Recording.kind == RecordingKind.audio,
                    Recording.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    spect = {
        r.derived_from_id: r
        for r in (
            await db.execute(
                select(Recording).where(
                    Recording.examination_id == res.examination_id,
                    Recording.kind == RecordingKind.spectrogram,
                    Recording.deleted_at.is_(None),
                )
            )
        ).scalars()
    }
    pr = (res.features or {}).get("per_recording", {})
    for r in recs:
        info = pr.get(str(r.id), {})
        per_rec.append(
            {
                "recording_id": str(r.id),
                "site": r.site.value if r.site else None,
                "pcg_class": info.get("pcg_class"),
                "confidence": info.get("confidence"),
                "spectrogram_url": f"/api/v1/recordings/{r.id}/spectrogram" if r.id in spect else None,
            }
        )
    f = lambda v: float(v) if v is not None else None  # noqa: E731
    return {
        "id": res.id,
        "model_version": res.model_version,
        "pcg_class": res.pcg_class.value,
        "class_probs": res.class_probs,
        "confidence": float(res.confidence),
        "severity": res.severity.value,
        "murmur_timing": res.murmur_timing.value,
        "murmur_grade": res.murmur_grade,
        "murmur_shape": res.murmur_shape,
        "heart_rate_bpm": f(res.heart_rate_bpm),
        "hr_variability_ms": f(res.hr_variability_ms),
        "s1_count": res.s1_count,
        "s2_count": res.s2_count,
        "mean_s1_s2_ms": f(res.mean_s1_s2_ms),
        "mean_s2_s1_ms": f(res.mean_s2_s1_ms),
        "systole_ms": f(res.systole_ms),
        "diastole_ms": f(res.diastole_ms),
        "dominant_freq_hz": f(res.dominant_freq_hz),
        "quality_ok": res.quality_ok,
        "quality_notes": res.quality_notes,
        "processing_ms": res.processing_ms,
        "is_current": res.is_current,
        "recordings": per_rec,
        "created_at": res.created_at,
    }


def report_full(r: AiReport) -> dict[str, Any]:
    return {
        "id": r.id,
        "status": r.status.value,
        "llm_model": r.llm_model,
        "prompt_version": r.prompt_version,
        "summary": r.summary,
        "findings": r.findings,
        "differential_diagnoses": r.differential_diagnoses,
        "recommended_tests": r.recommended_tests,
        "red_flags": r.red_flags,
        "patient_friendly_text": r.patient_friendly_text,
        "disclaimer": r.disclaimer,
        "error_message": r.error_message,
        "created_at": r.created_at,
    }


def report_nurse(r: AiReport) -> dict[str, Any]:
    return {
        "id": r.id,
        "status": r.status.value,
        "summary": r.summary,
        "findings": r.findings,
        "red_flags": r.red_flags,
        "disclaimer": r.disclaimer,
        "created_at": r.created_at,
    }


async def current_report(db: AsyncSession, exam_id: uuid.UUID) -> AiReport | None:
    return (
        await db.execute(select(AiReport).where(AiReport.examination_id == exam_id, AiReport.is_current))
    ).scalar_one_or_none()


async def current_analysis(db: AsyncSession, exam_id: uuid.UUID) -> AnalysisResult | None:
    return (
        await db.execute(
            select(AnalysisResult).where(AnalysisResult.examination_id == exam_id, AnalysisResult.is_current)
        )
    ).scalar_one_or_none()


async def current_conclusion(db: AsyncSession, exam_id: uuid.UUID) -> DoctorConclusion | None:
    return (
        await db.execute(
            select(DoctorConclusion).where(
                DoctorConclusion.examination_id == exam_id, DoctorConclusion.is_current
            )
        )
    ).scalar_one_or_none()


def conclusion_visible_to_nurse(c: DoctorConclusion | None) -> bool:
    return c is not None and c.status in (ConclusionStatus.signed, ConclusionStatus.amended)


async def exam_detail(db: AsyncSession, exam: Examination, user: User) -> dict[str, Any]:
    from app.services import prescription_service  # local import (cycle)

    patient = await db.get(Patient, exam.patient_id)
    um = await users_map(db, {exam.performed_by, exam.assigned_doctor_id})
    recs = (
        (
            await db.execute(
                select(Recording)
                .where(Recording.examination_id == exam.id, Recording.deleted_at.is_(None))
                .order_by(Recording.created_at)
            )
        )
        .scalars()
        .all()
    )
    analysis = await current_analysis(db, exam.id)
    report = await current_report(db, exam.id)
    conclusion = await current_conclusion(db, exam.id)
    history = (
        (
            await db.execute(
                select(ExamStatusHistory)
                .where(ExamStatusHistory.examination_id == exam.id)
                .order_by(ExamStatusHistory.created_at, ExamStatusHistory.id)
            )
        )
        .scalars()
        .all()
    )
    hist_users = await users_map(db, {h.changed_by for h in history})
    is_nurse = user.role == UserRole.nurse
    from app.services.patient_service import calc_age, full_name

    out: dict[str, Any] = {
        "id": exam.id,
        "exam_no": exam.exam_no,
        "status": exam.status,
        "priority": exam.priority,
        "patient": {
            "id": patient.id,
            "mrn": patient.mrn,
            "full_name": full_name(patient),
            "age": calc_age(patient.birth_date),
            "gender": patient.gender.value,
        },
        "performed_by": person(um.get(exam.performed_by)),
        "assigned_doctor": person(um.get(exam.assigned_doctor_id)),
        "examined_at": exam.examined_at,
        "complaints": exam.complaints,
        "symptoms": exam.symptoms or [],
        "patient_position": exam.patient_position,
        "heart_rate_bpm": exam.heart_rate_bpm,
        "bp_systolic": exam.bp_systolic,
        "bp_diastolic": exam.bp_diastolic,
        "spo2_pct": exam.spo2_pct,
        "temperature_c": float(exam.temperature_c) if exam.temperature_c is not None else None,
        "weight_kg_at_exam": float(exam.weight_kg_at_exam) if exam.weight_kg_at_exam is not None else None,
        "ai_requested_at": exam.ai_requested_at,
        "ai_completed_at": exam.ai_completed_at,
        "completed_at": exam.completed_at,
        "cancel_reason": exam.cancel_reason,
        "failure_reason": exam.failure_reason,
        "version": exam.version,
        "recordings": [recording_dict(r) for r in recs],
        "analysis": await analysis_dict(db, analysis),
        "report": None,
        "prescription": None,
        "conclusion": None,
        "status_history": [
            {
                "from": h.from_status.value if h.from_status else None,
                "to": h.to_status.value,
                "at": h.created_at,
                "by": str(h.changed_by) if h.changed_by else None,
                "by_name": hist_users[h.changed_by].full_name if h.changed_by in hist_users else None,
                "reason": h.reason,
            }
            for h in history
        ],
        "created_at": exam.created_at,
        "updated_at": exam.updated_at,
    }
    if report:
        out["report"] = report_nurse(report) if is_nurse else report_full(report)
    if is_nurse:
        out["conclusion"] = conclusion_out(conclusion) if conclusion_visible_to_nurse(conclusion) else None
    else:
        out["conclusion"] = conclusion_out(conclusion) if conclusion else None
        if has_permission(user.role, Permission.prescription_read):
            rx = await prescription_service.get_prescription(db, exam.id)
            out["prescription"] = await prescription_service.prescription_out(db, rx) if rx else None
    return out


def conclusion_out(c: DoctorConclusion | None) -> dict[str, Any] | None:
    if c is None:
        return None
    from app.schemas.clinical import ConclusionOut

    return ConclusionOut.model_validate(c).model_dump(mode="json")


async def job_for(db: AsyncSession, exam: Examination) -> AnalysisJob | None:
    if exam.current_job_id:
        return await db.get(AnalysisJob, exam.current_job_id)
    return None


_ = (RecordingKind, utcnow)

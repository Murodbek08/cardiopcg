from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_pii, hmac_hash
from app.core.errors import AppError, conflict, not_found
from app.core.permissions import Permission, has_permission
from app.db.base import utcnow
from app.models.analysis import AnalysisResult
from app.models.enums import ExamStatus
from app.models.examination import Examination
from app.models.patient import Allergy, CurrentMedication, MedicalHistory, Patient
from app.models.user import User


def calc_age(birth: date, today: date | None = None) -> int:
    t = today or date.today()
    return t.year - birth.year - ((t.month, t.day) < (birth.month, birth.day))


def calc_bmi(height_cm, weight_kg) -> float | None:
    if not height_cm or not weight_kg:
        return None
    h = float(height_cm) / 100
    return round(float(weight_kg) / (h * h), 1)


def normalize_national_id(v: str) -> str:
    return "".join(ch for ch in v if ch.isalnum()).upper()


async def next_mrn(db: AsyncSession) -> str:
    n = (await db.execute(text("SELECT nextval('patient_mrn_seq')"))).scalar_one()
    return f"P-{date.today().year}-{n:06d}"


async def get_patient(db: AsyncSession, pid: uuid.UUID, *, include_deleted: bool = False) -> Patient:
    p = await db.get(Patient, pid)
    if p is None or (p.deleted_at is not None and not include_deleted):
        raise not_found("Bemor")
    return p


def full_name(p: Patient) -> str:
    return " ".join(x for x in (p.last_name, p.first_name, p.middle_name) if x)


async def doctor_brief(db: AsyncSession, uid: uuid.UUID | None) -> dict[str, Any] | None:
    if uid is None:
        return None
    u = await db.get(User, uid)
    return {"id": u.id, "full_name": u.full_name} if u else None


def national_id_for(p: Patient, viewer: User) -> str | None:
    if p.national_id_enc is None:
        return None
    if not has_permission(viewer.role, Permission.national_id_read):
        return "****"
    return decrypt_pii(p.national_id_enc)


async def patient_out(db: AsyncSession, p: Patient, viewer: User) -> dict[str, Any]:
    return {
        "id": p.id,
        "mrn": p.mrn,
        "last_name": p.last_name,
        "first_name": p.first_name,
        "middle_name": p.middle_name,
        "full_name": full_name(p),
        "birth_date": p.birth_date,
        "age": calc_age(p.birth_date),
        "gender": p.gender,
        "phone": p.phone,
        "email": p.email,
        "address": p.address,
        "national_id": national_id_for(p, viewer),
        "blood_group": p.blood_group,
        "height_cm": float(p.height_cm) if p.height_cm is not None else None,
        "weight_kg": float(p.weight_kg) if p.weight_kg is not None else None,
        "bmi": calc_bmi(p.height_cm, p.weight_kg),
        "emergency_contact_name": p.emergency_contact_name,
        "emergency_contact_phone": p.emergency_contact_phone,
        "primary_doctor": await doctor_brief(db, p.primary_doctor_id),
        "notes": p.notes,
        "ai_consent": p.ai_consent,
        "is_active": p.is_active,
        "version": p.version,
        "created_by": p.created_by,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "deleted_at": p.deleted_at,
    }


async def patient_detail(db: AsyncSession, p: Patient, viewer: User) -> dict[str, Any]:
    out = await patient_out(db, p, viewer)
    out["allergies"] = list(
        (
            await db.execute(
                select(Allergy)
                .where(Allergy.patient_id == p.id, Allergy.is_active)
                .order_by(Allergy.created_at)
            )
        ).scalars()
    )
    out["medical_history"] = list(
        (
            await db.execute(
                select(MedicalHistory)
                .where(MedicalHistory.patient_id == p.id, MedicalHistory.is_active)
                .order_by(MedicalHistory.created_at)
            )
        ).scalars()
    )
    out["current_medications"] = list(
        (
            await db.execute(
                select(CurrentMedication)
                .where(CurrentMedication.patient_id == p.id, CurrentMedication.is_active)
                .order_by(CurrentMedication.created_at)
            )
        ).scalars()
    )
    cnt, last = (
        await db.execute(
            select(func.count(), func.max(Examination.examined_at)).where(
                Examination.patient_id == p.id, Examination.deleted_at.is_(None)
            )
        )
    ).one()
    last_class = (
        await db.execute(
            select(AnalysisResult.pcg_class)
            .join(Examination, Examination.id == AnalysisResult.examination_id)
            .where(
                Examination.patient_id == p.id, Examination.deleted_at.is_(None), AnalysisResult.is_current
            )
            .order_by(Examination.examined_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    out["stats"] = {
        "exam_count": cnt,
        "last_exam_at": last,
        "last_pcg_class": last_class.value if last_class else None,
    }
    return out


async def check_duplicates(
    db: AsyncSession,
    *,
    national_id_hash: str | None,
    last_name: str,
    first_name: str,
    birth_date: date,
    force: bool,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if national_id_hash:
        q = select(Patient.id).where(Patient.national_id_hash == national_id_hash)
        if exclude_id:
            q = q.where(Patient.id != exclude_id)
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            raise conflict(
                "PATIENT_DUPLICATE", "Bu JShShIR bilan bemor mavjud", {"patient_id": str(existing)}
            )
    if not force:
        q = select(Patient.id).where(
            func.lower(Patient.last_name) == last_name.lower(),
            func.lower(Patient.first_name) == first_name.lower(),
            Patient.birth_date == birth_date,
            Patient.deleted_at.is_(None),
        )
        if exclude_id:
            q = q.where(Patient.id != exclude_id)
        dup = (await db.execute(q.limit(1))).scalar_one_or_none()
        if dup:
            raise conflict(
                "POSSIBLE_DUPLICATE",
                "Ism va tug'ilgan sana bir xil bemor mavjud (?force=true bilan davom ettiring)",
                {"patient_id": str(dup)},
            )


def hash_national_id(raw: str) -> str:
    return hmac_hash(normalize_national_id(raw))


async def has_active_exams(db: AsyncSession, patient_id: uuid.UUID) -> bool:
    q = select(func.count()).where(
        Examination.patient_id == patient_id,
        Examination.deleted_at.is_(None),
        Examination.status.notin_([ExamStatus.completed, ExamStatus.cancelled, ExamStatus.failed]),
    )
    return (await db.execute(q)).scalar_one() > 0


_ = (AppError, utcnow)

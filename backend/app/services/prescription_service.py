"""Prescriptions / drug recommendations: AI suggestions + doctor edits, safety checks, approval flow."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, conflict, invalid_state, not_found
from app.db.base import utcnow
from app.models.clinical import DrugRecommendation, Prescription
from app.models.enums import AuditAction, ExamStatus, PrescriptionStatus
from app.models.examination import Examination
from app.models.patient import Allergy, CurrentMedication, MedicalHistory
from app.models.user import User
from app.services import audit_service, drug_safety
from app.services.analysis_port import DrugSuggestion
from app.services.exam_service import DISCLAIMER_RX

OPEN = (PrescriptionStatus.suggested, PrescriptionStatus.draft)


async def get_prescription(db: AsyncSession, exam_id: uuid.UUID) -> Prescription | None:
    return (
        await db.execute(
            select(Prescription)
            .where(Prescription.examination_id == exam_id)
            .order_by(Prescription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_or_create(
    db: AsyncSession, exam: Examination, ai_report_id: uuid.UUID | None = None
) -> Prescription:
    rx = await get_prescription(db, exam.id)
    if rx is None:
        rx = Prescription(
            examination_id=exam.id,
            patient_id=exam.patient_id,
            ai_report_id=ai_report_id,
            status=PrescriptionStatus.suggested,
            safety_check={},
        )
        db.add(rx)
        await db.flush()
    elif ai_report_id:
        rx.ai_report_id = ai_report_id
    return rx


async def items_of(db: AsyncSession, rx: Prescription) -> list[DrugRecommendation]:
    return list(
        (
            await db.execute(
                select(DrugRecommendation)
                .where(DrugRecommendation.prescription_id == rx.id)
                .order_by(DrugRecommendation.sort_order, DrugRecommendation.created_at)
            )
        ).scalars()
    )


def _item_dict(it: DrugRecommendation) -> dict[str, Any]:
    return {
        "id": it.id,
        "source": it.source,
        "drug_name": it.drug_name,
        "inn_code": it.inn_code,
        "atc_code": it.atc_code,
        "dose": it.dose,
        "route": it.route,
        "frequency": it.frequency,
        "duration_days": it.duration_days,
        "instructions": it.instructions,
        "rationale": it.rationale,
        "contraindications": it.contraindications or [],
        "side_effects": it.side_effects or [],
        "interaction_warnings": it.interaction_warnings or [],
        "allergy_warning": it.allergy_warning,
        "safety_pending": it.safety_pending,
        "override_reason": it.override_reason,
        "status": it.status,
        "sort_order": it.sort_order,
    }


async def prescription_out(
    db: AsyncSession, rx: Prescription, *, only_approved: bool = False
) -> dict[str, Any]:
    items = await items_of(db, rx)
    if only_approved:
        items = [i for i in items if i.status == PrescriptionStatus.approved]
    return {
        "id": rx.id,
        "status": rx.status,
        "disclaimer": DISCLAIMER_RX,
        "safety_check": rx.safety_check or {},
        "doctor_notes": rx.doctor_notes,
        "approved_at": rx.approved_at,
        "items": [_item_dict(i) for i in items],
        "version": rx.version,
    }


async def _patient_context(db: AsyncSession, patient_id: uuid.UUID):
    allergies = [
        {"substance": a.substance, "substance_code": a.substance_code, "severity": a.severity.value}
        for a in (
            await db.execute(select(Allergy).where(Allergy.patient_id == patient_id, Allergy.is_active))
        ).scalars()
    ]
    meds = [
        {"drug_name": m.drug_name, "inn_code": m.inn_code}
        for m in (
            await db.execute(
                select(CurrentMedication).where(
                    CurrentMedication.patient_id == patient_id, CurrentMedication.is_active
                )
            )
        ).scalars()
    ]
    hist = [
        {"title": h.title, "icd10_code": h.icd10_code, "description": h.description, "is_active": h.is_active}
        for h in (
            await db.execute(
                select(MedicalHistory).where(
                    MedicalHistory.patient_id == patient_id, MedicalHistory.is_active
                )
            )
        ).scalars()
    ]
    return allergies, meds, hist


async def run_safety_check(db: AsyncSession, rx: Prescription) -> dict[str, Any]:
    """(Re)compute allergy/interaction/contraindication/dose checks for all not-yet-rejected items."""
    allergies, meds, hist = await _patient_context(db, rx.patient_id)
    items = [
        i
        for i in await items_of(db, rx)
        if i.status not in (PrescriptionStatus.rejected, PrescriptionStatus.cancelled)
    ]
    di = [
        drug_safety.Item(str(i.id), i.drug_name, i.inn_code, i.atc_code, i.dose, i.frequency) for i in items
    ]
    res = drug_safety.run_checks(di, allergies, meds, hist)
    by_item_inter: dict[str, list[dict[str, Any]]] = {}
    for ix in res.interactions:
        for it in items:
            if it.drug_name in ix["items"]:
                by_item_inter.setdefault(str(it.id), []).append(ix)
    allergic = {c["item_id"] for c in res.allergy_conflicts}
    for it in items:
        it.allergy_warning = str(it.id) in allergic
        it.interaction_warnings = by_item_inter.get(str(it.id), [])
        it.safety_pending = False
    prev = rx.safety_check or {}
    rx.safety_check = {
        "checked_at": utcnow().isoformat(),
        "allergy_conflicts": res.allergy_conflicts,
        "interactions": res.interactions,
        "contraindications": res.contraindications,
        "dose_warnings": res.dose_warnings,
        "overrides": prev.get("overrides", []),
    }
    return rx.safety_check


async def recheck_patient(db: AsyncSession, patient_id: uuid.UUID) -> int:
    """After allergy/medication changes: recompute safety for the patient's open (suggested) prescriptions."""
    rxs = (
        (
            await db.execute(
                select(Prescription)
                .join(Examination, Examination.id == Prescription.examination_id)
                .where(
                    Prescription.patient_id == patient_id,
                    Prescription.status.in_(OPEN),
                    Examination.status != ExamStatus.completed,
                    Examination.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for rx in rxs:
        await run_safety_check(db, rx)
    return len(rxs)


async def add_ai_suggestions(
    db: AsyncSession, exam: Examination, suggestions: list[DrugSuggestion], ai_report_id: uuid.UUID | None
) -> Prescription | None:
    """Replace previous AI-suggested (still undecided) rows with a fresh AI proposal; doctor rows are kept."""
    if not suggestions:
        return None
    rx = await get_or_create(db, exam, ai_report_id)
    for it in await items_of(db, rx):
        if it.source == "ai" and it.status == PrescriptionStatus.suggested:
            await db.delete(it)
    await db.flush()
    existing = len(await items_of(db, rx))
    for n, s in enumerate(suggestions):
        db.add(
            DrugRecommendation(
                prescription_id=rx.id,
                source="ai",
                drug_name=s.drug_name[:160],
                inn_code=s.inn_code,
                atc_code=s.atc_code,
                dose=s.dose[:60],
                route=s.route[:30],
                frequency=s.frequency[:80],
                duration_days=s.duration_days,
                instructions=s.instructions,
                rationale=s.rationale,
                contraindications=s.contraindications,
                side_effects=s.side_effects,
                status=PrescriptionStatus.suggested,
                safety_pending=True,
                sort_order=existing + n,
            )
        )
    await db.flush()
    rx.status = PrescriptionStatus.suggested
    await run_safety_check(db, rx)
    return rx


# ------------------------------------------------------------------------------- doctor operations
async def assert_editable(db: AsyncSession, exam: Examination) -> None:
    if exam.status in (ExamStatus.completed, ExamStatus.cancelled):
        raise invalid_state(
            exam.status.value, [], "Xulosa imzolangan yoki tekshiruv bekor qilingan; retsept o'zgarmaydi"
        )


async def item_for(
    db: AsyncSession, item_id: uuid.UUID
) -> tuple[DrugRecommendation, Prescription, Examination]:
    it = await db.get(DrugRecommendation, item_id)
    if it is None:
        raise not_found("Dori satri")
    rx = await db.get(Prescription, it.prescription_id)
    exam = await db.get(Examination, rx.examination_id)
    return it, rx, exam


async def add_item(
    db: AsyncSession, exam: Examination, data: dict[str, Any], doctor: User
) -> DrugRecommendation:
    await assert_editable(db, exam)
    rx = await get_or_create(db, exam)
    n = len(await items_of(db, rx))
    it = DrugRecommendation(
        prescription_id=rx.id,
        source="doctor",
        status=PrescriptionStatus.suggested,
        sort_order=n,
        safety_pending=True,
        **data,
    )
    db.add(it)
    await db.flush()
    await run_safety_check(db, rx)
    audit_service.log_event(
        db,
        AuditAction.create,
        user=doctor,
        resource_type="prescription_item",
        resource_id=it.id,
        patient_id=exam.patient_id,
    )
    return it


def refresh_status(rx: Prescription, items: list[DrugRecommendation]) -> None:
    live = [i for i in items if i.status != PrescriptionStatus.cancelled]
    if not live:
        rx.status = PrescriptionStatus.draft
    elif any(i.status == PrescriptionStatus.suggested for i in live):
        rx.status = PrescriptionStatus.suggested
    elif any(i.status == PrescriptionStatus.approved for i in live):
        rx.status = PrescriptionStatus.approved
        rx.approved_at = rx.approved_at or utcnow()
    else:
        rx.status = PrescriptionStatus.rejected
    rx.version += 1


async def approve_item(
    db: AsyncSession,
    it: DrugRecommendation,
    rx: Prescription,
    exam: Examination,
    doctor: User,
    override_reason: str | None,
) -> None:
    await assert_editable(db, exam)
    if it.status == PrescriptionStatus.rejected:
        raise invalid_state(it.status.value, [], "Rad etilgan satrni tasdiqlab bo'lmaydi")
    if it.safety_pending:
        await run_safety_check(db, rx)
    if it.allergy_warning and not (override_reason and override_reason.strip()):
        raise conflict(
            "ALLERGY_OVERRIDE_REQUIRED",
            "Allergiya ogohlantirishi: override_reason majburiy",
            {"item_id": str(it.id)},
        )
    it.status = PrescriptionStatus.approved
    if override_reason:
        it.override_reason = override_reason.strip()
        sc = dict(rx.safety_check or {})
        sc["overrides"] = [
            *sc.get("overrides", []),
            {
                "item_id": str(it.id),
                "reason": it.override_reason,
                "by": str(doctor.id),
                "at": utcnow().isoformat(),
            },
        ]
        rx.safety_check = sc
    rx.prescribed_by = doctor.id
    refresh_status(rx, await items_of(db, rx))
    audit_service.log_event(
        db,
        AuditAction.approve,
        user=doctor,
        resource_type="prescription_item",
        resource_id=it.id,
        patient_id=exam.patient_id,
        meta={"drug": it.drug_name, "override": bool(override_reason)},
    )


async def reject_item(
    db: AsyncSession, it: DrugRecommendation, rx: Prescription, exam: Examination, doctor: User, reason: str
) -> None:
    await assert_editable(db, exam)
    it.status = PrescriptionStatus.rejected
    it.reject_reason = reason
    refresh_status(rx, await items_of(db, rx))
    audit_service.log_event(
        db,
        AuditAction.reject,
        user=doctor,
        resource_type="prescription_item",
        resource_id=it.id,
        patient_id=exam.patient_id,
        meta={"drug": it.drug_name},
    )


async def approve_all(db: AsyncSession, exam: Examination, doctor: User) -> dict[str, Any]:
    await assert_editable(db, exam)
    rx = await get_prescription(db, exam.id)
    if rx is None:
        raise not_found("Retsept")
    await run_safety_check(db, rx)
    approved, skipped = 0, []
    for it in await items_of(db, rx):
        if it.status != PrescriptionStatus.suggested:
            continue
        if it.allergy_warning or it.interaction_warnings:
            skipped.append(str(it.id))
            continue
        it.status = PrescriptionStatus.approved
        approved += 1
        audit_service.log_event(
            db,
            AuditAction.approve,
            user=doctor,
            resource_type="prescription_item",
            resource_id=it.id,
            patient_id=exam.patient_id,
            meta={"bulk": True},
        )
    rx.prescribed_by = doctor.id
    refresh_status(rx, await items_of(db, rx))
    return {"approved": approved, "skipped_with_warnings": skipped}


def has_undecided(items: list[DrugRecommendation]) -> bool:
    return any(i.status == PrescriptionStatus.suggested for i in items)


_ = AppError

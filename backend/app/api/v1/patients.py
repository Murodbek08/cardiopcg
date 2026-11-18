from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import Text, and_, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_pii
from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.errors import AppError, conflict, not_found
from app.core.http import check_if_match, etag
from app.core.pagination import clamp_limit, paginate, parse_sort, with_sort_columns
from app.core.permissions import Permission, has_permission
from app.core.route import TxRoute
from app.db.base import utcnow
from app.models.analysis import AnalysisResult
from app.models.clinical import DoctorConclusion, Prescription
from app.models.enums import AuditAction, ConclusionStatus, Gender, PrescriptionStatus
from app.models.examination import Examination
from app.models.patient import Allergy, CurrentMedication, MedicalHistory, Patient
from app.models.system import AuditLog
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.patients import (
    AllergyIn,
    AllergyOut,
    AllergyPatch,
    HistoryIn,
    HistoryOut,
    HistoryPatch,
    MedicationIn,
    MedicationOut,
    MedicationPatch,
    PatientCreate,
    PatientDetail,
    PatientOut,
    PatientUpdate,
)
from app.services import audit_service, patient_service, prescription_service
from app.services.patient_service import (
    calc_age,
    check_duplicates,
    full_name,
    get_patient,
    hash_national_id,
    next_mrn,
    normalize_national_id,
    patient_detail,
    patient_out,
)

router = APIRouter(prefix="/patients", tags=["patients"], route_class=TxRoute, responses=ERROR_RESPONSES)

_EPOCH = datetime(1970, 1, 1, tzinfo=utcnow().tzinfo)


def _name_expr():
    return func.concat(
        Patient.last_name, " ", Patient.first_name, " ", func.coalesce(Patient.middle_name, "")
    )


@router.get("")
async def list_patients(
    db: DB,
    user: CurrentUser,
    q: str | None = Query(default=None, min_length=2, max_length=100),
    gender: Gender | None = None,
    age_min: int | None = Query(default=None, ge=0, le=130),
    age_max: int | None = Query(default=None, ge=0, le=130),
    primary_doctor_id: uuid.UUID | None = None,
    has_allergies: bool | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    is_active: bool | None = None,
    sort: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    with_total: bool = False,
):
    if not has_permission(user.role, Permission.patient_read):
        await deny(user, Permission.patient_read)
    ex = (
        select(
            Examination.patient_id.label("pid"),
            func.count().label("cnt"),
            func.max(Examination.examined_at).label("last_at"),
        )
        .where(Examination.deleted_at.is_(None))
        .group_by(Examination.patient_id)
        .subquery()
    )
    al = select(Allergy.patient_id.label("pid")).where(Allergy.is_active).distinct().subquery()
    doc = User
    last_exam_expr = func.coalesce(ex.c.last_at, _EPOCH)
    sorts = {
        "last_name": func.lower(Patient.last_name),
        "birth_date": Patient.birth_date,
        "created_at": Patient.created_at,
        "last_exam_at": last_exam_expr,
    }
    keys = parse_sort(sort, sorts, "-created_at")
    stmt = (
        select(
            Patient,
            func.coalesce(ex.c.cnt, 0).label("exam_count"),
            ex.c.last_at.label("last_exam_at"),
            (al.c.pid.is_not(None)).label("has_allergies"),
            doc.full_name.label("doctor_name"),
        )
        .outerjoin(ex, ex.c.pid == Patient.id)
        .outerjoin(al, al.c.pid == Patient.id)
        .outerjoin(doc, doc.id == Patient.primary_doctor_id)
        .where(Patient.deleted_at.is_(None))
    )
    if q:
        like = f"%{q}%"
        cond = (
            _name_expr().ilike(like)
            | Patient.mrn.ilike(like)
            | Patient.phone.ilike(like)
            | (func.similarity(_name_expr(), q) > 0.3)
        )
        stmt = stmt.where(cond)
    if gender:
        stmt = stmt.where(Patient.gender == gender)
    today = date.today()
    if age_min is not None:
        stmt = stmt.where(Patient.birth_date <= date(today.year - age_min, today.month, min(today.day, 28)))
    if age_max is not None:
        stmt = stmt.where(
            Patient.birth_date > date(today.year - age_max - 1, today.month, min(today.day, 28))
        )
    if primary_doctor_id:
        stmt = stmt.where(Patient.primary_doctor_id == primary_doctor_id)
    if has_allergies is not None:
        stmt = stmt.where(al.c.pid.is_not(None) if has_allergies else al.c.pid.is_(None))
    if created_from:
        stmt = stmt.where(
            Patient.created_at >= datetime.combine(created_from, datetime.min.time(), tzinfo=_EPOCH.tzinfo)
        )
    if created_to:
        stmt = stmt.where(
            Patient.created_at
            < datetime.combine(created_to, datetime.min.time(), tzinfo=_EPOCH.tzinfo) + timedelta(days=1)
        )
    if is_active is not None:
        stmt = stmt.where(Patient.is_active == is_active)
    stmt = with_sort_columns(stmt, keys, Patient.id)
    rows, page = await paginate(
        db, stmt, id_col=Patient.id, sort=keys, cursor=cursor, limit=clamp_limit(limit), with_total=with_total
    )
    items = []
    for r in rows:
        p: Patient = r[0]
        items.append(
            {
                "id": p.id,
                "mrn": p.mrn,
                "full_name": full_name(p),
                "birth_date": p.birth_date,
                "age": calc_age(p.birth_date),
                "gender": p.gender,
                "phone": p.phone,
                "primary_doctor": {"id": p.primary_doctor_id, "full_name": r.doctor_name}
                if p.primary_doctor_id and r.doctor_name
                else None,
                "last_exam_at": r.last_exam_at,
                "exam_count": r.exam_count,
                "has_allergies": bool(r.has_allergies),
            }
        )
    return {"items": items, "page": page}


@router.post(
    "",
    status_code=201,
    response_model=PatientOut,
    responses={409: {"description": "PATIENT_DUPLICATE / POSSIBLE_DUPLICATE"}},
)
async def create_patient(
    body: PatientCreate, db: DB, user: User = Perm(Permission.patient_write), force: bool = False
):
    nid_hash = hash_national_id(body.national_id) if body.national_id else None
    await check_duplicates(
        db,
        national_id_hash=nid_hash,
        last_name=body.last_name,
        first_name=body.first_name,
        birth_date=body.birth_date,
        force=force,
    )
    if body.primary_doctor_id:
        from app.services.exam_service import valid_doctor

        await valid_doctor(db, body.primary_doctor_id)
    data = body.model_dump(exclude={"national_id"})
    p = Patient(mrn=await next_mrn(db), created_by=user.id, **data)
    if body.national_id:
        p.national_id_enc = encrypt_pii(normalize_national_id(body.national_id))
        p.national_id_hash = nid_hash
    db.add(p)
    await db.flush()
    audit_service.log_event(
        db,
        AuditAction.create,
        user=user,
        resource_type="patient",
        resource_id=p.id,
        patient_id=p.id,
        changes={"after": {"mrn": p.mrn, "national_id": "set" if body.national_id else None}},
    )
    return await patient_out(db, p, user)


@router.get("/{patient_id}", response_model=PatientDetail)
async def get_patient_detail(
    patient_id: uuid.UUID, db: DB, response: Response, user: User = Perm(Permission.patient_read)
):
    p = await get_patient(db, patient_id)
    audit_service.log_event(
        db, AuditAction.read, user=user, resource_type="patient", resource_id=p.id, patient_id=p.id
    )
    response.headers.update(etag(p.version))
    return await patient_detail(db, p, user)


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: uuid.UUID,
    body: PatientUpdate,
    request: Request,
    db: DB,
    response: Response,
    user: User = Perm(Permission.patient_write),
):
    p = await get_patient(db, patient_id)
    check_if_match(request, p.version)
    data = body.model_dump(exclude_unset=True)
    nid = data.pop("national_id", None)
    new_hash = None
    if nid:
        new_hash = hash_national_id(nid)
    await check_duplicates(
        db,
        national_id_hash=new_hash if new_hash != p.national_id_hash else None,
        last_name=data.get("last_name", p.last_name),
        first_name=data.get("first_name", p.first_name),
        birth_date=data.get("birth_date", p.birth_date),
        force=True,
        exclude_id=p.id,
    )
    if data.get("primary_doctor_id"):
        from app.services.exam_service import valid_doctor

        await valid_doctor(db, data["primary_doctor_id"])
    before = {k: getattr(p, k) for k in data}
    for k, v in data.items():
        setattr(p, k, v)
    if nid:
        p.national_id_enc = encrypt_pii(normalize_national_id(nid))
        p.national_id_hash = new_hash
        before["national_id"], data["national_id"] = "old", "new"  # masked by audit_service.mask
    p.version += 1
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="patient",
        resource_id=p.id,
        patient_id=p.id,
        changes=audit_service.diff(before, data),
    )
    await db.flush()
    response.headers.update(etag(p.version))
    return await patient_out(db, p, user)


@router.delete("/{patient_id}", status_code=204, responses={409: {"description": "PATIENT_HAS_ACTIVE_EXAMS"}})
async def delete_patient(patient_id: uuid.UUID, db: DB, user: User = Perm(Permission.patient_delete)):
    p = await get_patient(db, patient_id)
    if await patient_service.has_active_exams(db, p.id):
        raise conflict("PATIENT_HAS_ACTIVE_EXAMS", "Bemorning faol tekshiruvlari bor")
    p.deleted_at = utcnow()
    p.version += 1
    audit_service.log_event(
        db, AuditAction.delete, user=user, resource_type="patient", resource_id=p.id, patient_id=p.id
    )
    return Response(status_code=204)


@router.post("/{patient_id}/restore", response_model=PatientOut)
async def restore_patient(patient_id: uuid.UUID, db: DB, user: User = Perm(Permission.patient_restore)):
    p = await get_patient(db, patient_id, include_deleted=True)
    p.deleted_at = None
    p.version += 1
    audit_service.log_event(
        db, AuditAction.restore, user=user, resource_type="patient", resource_id=p.id, patient_id=p.id
    )
    return await patient_out(db, p, user)


@router.get("/{patient_id}/timeline")
async def timeline(
    patient_id: uuid.UUID,
    db: DB,
    user: User = Perm(Permission.patient_read),
    limit: int | None = None,
    cursor: str | None = None,
):
    p = await get_patient(db, patient_id)
    exams = (
        select(
            Examination.examined_at.label("ts"),
            literal("examination").label("type"),
            Examination.id.label("uid"),
            Examination.id.label("exam_id"),
            Examination.exam_no.label("exam_no"),
            cast(AnalysisResult.pcg_class, Text).label("pcg_class"),
            cast(AnalysisResult.severity, Text).label("severity"),
            cast(Examination.status, Text).label("status"),
        )
        .outerjoin(
            AnalysisResult, and_(AnalysisResult.examination_id == Examination.id, AnalysisResult.is_current)
        )
        .where(Examination.patient_id == p.id, Examination.deleted_at.is_(None))
    )
    concl = (
        select(
            DoctorConclusion.signed_at.label("ts"),
            literal("conclusion").label("type"),
            DoctorConclusion.id.label("uid"),
            DoctorConclusion.examination_id.label("exam_id"),
            Examination.exam_no.label("exam_no"),
            cast(DoctorConclusion.final_pcg_class, Text).label("pcg_class"),
            cast(DoctorConclusion.final_severity, Text).label("severity"),
            cast(DoctorConclusion.status, Text).label("status"),
        )
        .join(Examination, Examination.id == DoctorConclusion.examination_id)
        .where(
            Examination.patient_id == p.id,
            DoctorConclusion.is_current,
            DoctorConclusion.status.in_([ConclusionStatus.signed, ConclusionStatus.amended]),
        )
    )
    rx = (
        select(
            Prescription.approved_at.label("ts"),
            literal("prescription").label("type"),
            Prescription.id.label("uid"),
            Prescription.examination_id.label("exam_id"),
            Examination.exam_no.label("exam_no"),
            literal(None).label("pcg_class"),
            literal(None).label("severity"),
            cast(Prescription.status, Text).label("status"),
        )
        .join(Examination, Examination.id == Prescription.examination_id)
        .where(
            Prescription.patient_id == p.id,
            Prescription.status == PrescriptionStatus.approved,
            Prescription.approved_at.is_not(None),
        )
    )
    if user.role.value == "nurse":
        u = union_all(exams, concl).subquery()  # nurses do not see prescriptions
    else:
        u = union_all(exams, concl, rx).subquery()
    stmt = select(u.c.ts, u.c.type, u.c.exam_id, u.c.exam_no, u.c.pcg_class, u.c.severity, u.c.status)
    keys = parse_sort("-ts", {"ts": u.c.ts}, "-ts")
    stmt = with_sort_columns(stmt, keys, u.c.uid)
    rows, page = await paginate(
        db, stmt, id_col=u.c.uid, sort=keys, cursor=cursor, limit=clamp_limit(limit), with_total=False
    )
    return {
        "items": [
            {
                "ts": r.ts,
                "type": r.type,
                "exam_id": r.exam_id,
                "exam_no": r.exam_no,
                "pcg_class": r.pcg_class,
                "severity": r.severity,
                "status": r.status,
            }
            for r in rows
        ],
        "page": page,
    }


@router.get("/{patient_id}/audit")
async def patient_audit(
    patient_id: uuid.UUID, db: DB, user: User = Perm(Permission.audit_read), limit: int | None = None
):
    await get_patient(db, patient_id, include_deleted=True)
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.patient_id == patient_id)
                .order_by(AuditLog.id.desc())
                .limit(clamp_limit(limit, 50, 200))
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "ts": r.ts,
                "user_id": r.user_id,
                "username": r.username_snapshot,
                "role": r.role_snapshot,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "success": r.success,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------- sub-resources
async def _sub_get(db: AsyncSession, model, patient_id: uuid.UUID, sub_id: uuid.UUID):
    await get_patient(db, patient_id)
    obj = await db.get(model, sub_id)
    if obj is None or obj.patient_id != patient_id:
        raise not_found("Yozuv")
    return obj


async def _archive(db: AsyncSession, user: User, obj: Any, patient_id: uuid.UUID, rtype: str) -> Response:
    if not has_permission(user.role, Permission.history_delete):
        await deny(user, Permission.history_delete, rtype)
    obj.is_active = False
    audit_service.log_event(
        db, AuditAction.delete, user=user, resource_type=rtype, resource_id=obj.id, patient_id=patient_id
    )
    return Response(status_code=204)


@router.get("/{patient_id}/history", response_model=list[HistoryOut])
async def list_history(
    patient_id: uuid.UUID, db: DB, user: User = Perm(Permission.patient_read), include_inactive: bool = False
):
    await get_patient(db, patient_id)
    q = select(MedicalHistory).where(MedicalHistory.patient_id == patient_id)
    if not include_inactive:
        q = q.where(MedicalHistory.is_active)
    return (await db.execute(q.order_by(MedicalHistory.created_at))).scalars().all()


@router.post("/{patient_id}/history", status_code=201, response_model=HistoryOut)
async def add_history(
    patient_id: uuid.UUID, body: HistoryIn, db: DB, user: User = Perm(Permission.patient_write)
):
    await get_patient(db, patient_id)
    h = MedicalHistory(patient_id=patient_id, recorded_by=user.id, **body.model_dump())
    db.add(h)
    await db.flush()
    audit_service.log_event(
        db,
        AuditAction.create,
        user=user,
        resource_type="medical_history",
        resource_id=h.id,
        patient_id=patient_id,
    )
    await prescription_service.recheck_patient(db, patient_id)
    return h


@router.patch("/{patient_id}/history/{hid}", response_model=HistoryOut)
async def patch_history(
    patient_id: uuid.UUID,
    hid: uuid.UUID,
    body: HistoryPatch,
    db: DB,
    user: User = Perm(Permission.patient_write),
):
    h = await _sub_get(db, MedicalHistory, patient_id, hid)
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(h, k) for k in data}
    for k, v in data.items():
        setattr(h, k, v)
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="medical_history",
        resource_id=h.id,
        patient_id=patient_id,
        changes=audit_service.diff(before, data),
    )
    await prescription_service.recheck_patient(db, patient_id)
    return h


@router.delete("/{patient_id}/history/{hid}", status_code=204)
async def delete_history(patient_id: uuid.UUID, hid: uuid.UUID, db: DB, user: CurrentUser):
    h = await _sub_get(db, MedicalHistory, patient_id, hid)
    return await _archive(db, user, h, patient_id, "medical_history")


@router.get("/{patient_id}/allergies", response_model=list[AllergyOut])
async def list_allergies(
    patient_id: uuid.UUID, db: DB, user: User = Perm(Permission.patient_read), include_inactive: bool = False
):
    await get_patient(db, patient_id)
    q = select(Allergy).where(Allergy.patient_id == patient_id)
    if not include_inactive:
        q = q.where(Allergy.is_active)
    return (await db.execute(q.order_by(Allergy.created_at))).scalars().all()


async def _allergy_dup(
    db: AsyncSession, patient_id: uuid.UUID, substance: str, exclude: uuid.UUID | None = None
) -> None:
    q = select(Allergy.id).where(
        Allergy.patient_id == patient_id,
        Allergy.is_active,
        func.lower(Allergy.substance) == substance.lower(),
    )
    if exclude:
        q = q.where(Allergy.id != exclude)
    if (await db.execute(q)).first():
        raise conflict("ALLERGY_EXISTS", "Bu allergen allaqachon kiritilgan")


@router.post("/{patient_id}/allergies", status_code=201, response_model=AllergyOut)
async def add_allergy(
    patient_id: uuid.UUID, body: AllergyIn, db: DB, user: User = Perm(Permission.patient_write)
):
    await get_patient(db, patient_id)
    await _allergy_dup(db, patient_id, body.substance)
    a = Allergy(patient_id=patient_id, recorded_by=user.id, **body.model_dump())
    db.add(a)
    await db.flush()
    audit_service.log_event(
        db, AuditAction.create, user=user, resource_type="allergy", resource_id=a.id, patient_id=patient_id
    )
    await prescription_service.recheck_patient(db, patient_id)
    return a


@router.patch("/{patient_id}/allergies/{aid}", response_model=AllergyOut)
async def patch_allergy(
    patient_id: uuid.UUID,
    aid: uuid.UUID,
    body: AllergyPatch,
    db: DB,
    user: User = Perm(Permission.patient_write),
):
    a = await _sub_get(db, Allergy, patient_id, aid)
    data = body.model_dump(exclude_unset=True)
    if "substance" in data:
        await _allergy_dup(db, patient_id, data["substance"], exclude=a.id)
    before = {k: getattr(a, k) for k in data}
    for k, v in data.items():
        setattr(a, k, v)
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="allergy",
        resource_id=a.id,
        patient_id=patient_id,
        changes=audit_service.diff(before, data),
    )
    await db.flush()
    await prescription_service.recheck_patient(db, patient_id)
    return a


@router.delete("/{patient_id}/allergies/{aid}", status_code=204)
async def delete_allergy(patient_id: uuid.UUID, aid: uuid.UUID, db: DB, user: CurrentUser):
    a = await _sub_get(db, Allergy, patient_id, aid)
    resp = await _archive(db, user, a, patient_id, "allergy")
    await db.flush()
    await prescription_service.recheck_patient(db, patient_id)
    return resp


@router.get("/{patient_id}/medications", response_model=list[MedicationOut])
async def list_meds(
    patient_id: uuid.UUID, db: DB, user: User = Perm(Permission.patient_read), include_inactive: bool = False
):
    await get_patient(db, patient_id)
    q = select(CurrentMedication).where(CurrentMedication.patient_id == patient_id)
    if not include_inactive:
        q = q.where(CurrentMedication.is_active)
    return (await db.execute(q.order_by(CurrentMedication.created_at))).scalars().all()


@router.post("/{patient_id}/medications", status_code=201, response_model=MedicationOut)
async def add_med(
    patient_id: uuid.UUID, body: MedicationIn, db: DB, user: User = Perm(Permission.patient_write)
):
    await get_patient(db, patient_id)
    m = CurrentMedication(patient_id=patient_id, recorded_by=user.id, **body.model_dump())
    db.add(m)
    await db.flush()
    audit_service.log_event(
        db, AuditAction.create, user=user, resource_type="medication", resource_id=m.id, patient_id=patient_id
    )
    await prescription_service.recheck_patient(db, patient_id)
    return m


@router.patch("/{patient_id}/medications/{mid}", response_model=MedicationOut)
async def patch_med(
    patient_id: uuid.UUID,
    mid: uuid.UUID,
    body: MedicationPatch,
    db: DB,
    user: User = Perm(Permission.patient_write),
):
    m = await _sub_get(db, CurrentMedication, patient_id, mid)
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(m, k) for k in data}
    for k, v in data.items():
        setattr(m, k, v)
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="medication",
        resource_id=m.id,
        patient_id=patient_id,
        changes=audit_service.diff(before, data),
    )
    await db.flush()
    await prescription_service.recheck_patient(db, patient_id)
    return m


@router.delete("/{patient_id}/medications/{mid}", status_code=204)
async def delete_med(patient_id: uuid.UUID, mid: uuid.UUID, db: DB, user: CurrentUser):
    m = await _sub_get(db, CurrentMedication, patient_id, mid)
    resp = await _archive(db, user, m, patient_id, "medication")
    await db.flush()
    await prescription_service.recheck_patient(db, patient_id)
    return resp


_ = AppError

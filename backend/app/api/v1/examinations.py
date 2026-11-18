from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, time, timedelta

import orjson
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Text, case, cast, func, select

from app.config import get_settings
from app.core import idempotency, rate_limit
from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.errors import AppError, invalid_state
from app.core.http import check_if_match, etag
from app.core.pagination import clamp_limit, paginate, parse_sort, with_sort_columns
from app.core.permissions import Permission, has_permission
from app.core.route import TxRoute
from app.models.analysis import AnalysisJob, AnalysisResult
from app.models.clinical import DoctorConclusion
from app.models.enums import (
    AgreementLevel,
    AuditAction,
    ExamPriority,
    ExamStatus,
    PcgClass,
    RecordingKind,
    Severity,
    UserRole,
)
from app.models.examination import Examination, ExamStatusHistory
from app.models.patient import Patient
from app.models.recording import Recording
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES, json_response
from app.schemas.exams import (
    AnalyzeAccepted,
    AnalyzeIn,
    AssignIn,
    CancelIn,
    ExamCreate,
    ExamDetail,
    ExamUpdate,
    StatusOut,
)
from app.services import analysis_service, audit_service, exam_service, notification_service, realtime
from app.services.analysis_port import AnalysisOptions
from app.services.exam_service import get_exam_for, load_exam, nurse_scope
from app.services.exam_state import allowed_targets, transition
from app.services.patient_service import calc_age, full_name, get_patient
from app.services.realtime import bus

router = APIRouter(
    prefix="/examinations", tags=["examinations"], route_class=TxRoute, responses=ERROR_RESPONSES
)

CLINICAL_FIELDS = {
    "complaints",
    "symptoms",
    "patient_position",
    "heart_rate_bpm",
    "bp_systolic",
    "bp_diastolic",
    "spo2_pct",
    "temperature_c",
    "weight_kg_at_exam",
}
PRIORITY_RANK = case(
    {ExamPriority.emergency: 3, ExamPriority.urgent: 2, ExamPriority.routine: 1}, value=Examination.priority
)
SEV_RANK = case(
    {Severity.critical: 5, Severity.severe: 4, Severity.moderate: 3, Severity.mild: 2, Severity.none: 1},
    value=AnalysisResult.severity,
    else_=0,
)


@router.post("", status_code=201, response_model=ExamDetail)
async def create_exam(body: ExamCreate, db: DB, user: User = Perm(Permission.exam_create)):
    patient = await get_patient(db, body.patient_id)
    data = body.model_dump(exclude={"patient_id", "assigned_doctor_id"})
    if body.assigned_doctor_id:
        await exam_service.valid_doctor(db, body.assigned_doctor_id)
    e = Examination(
        exam_no=await exam_service.next_exam_no(db),
        patient_id=patient.id,
        performed_by=user.id,
        status=ExamStatus.draft,
        **data,
    )
    db.add(e)
    await db.flush()
    db.add(
        ExamStatusHistory(
            examination_id=e.id, from_status=None, to_status=ExamStatus.draft, changed_by=user.id
        )
    )
    audit_service.log_event(
        db,
        AuditAction.create,
        user=user,
        resource_type="examination",
        resource_id=e.id,
        patient_id=patient.id,
        meta={"exam_no": e.exam_no},
    )
    chans = ["role:admin"]
    if body.assigned_doctor_id:
        e.assigned_doctor_id = body.assigned_doctor_id
        chans.append(f"user:{body.assigned_doctor_id}")
        await exam_service.assign_doctor(db, e, body.assigned_doctor_id, user)
    realtime.queue_event(
        db,
        "exam.created",
        {"examination_id": str(e.id), "exam_no": e.exam_no, "patient_id": str(patient.id)},
        chans,
    )
    await db.flush()
    return await exam_service.exam_detail(db, e, user)


@router.get("")
async def list_exams(
    db: DB,
    user: CurrentUser,
    status: list[ExamStatus] = Query(default_factory=list),
    priority: ExamPriority | None = None,
    patient_id: uuid.UUID | None = None,
    assigned_doctor_id: uuid.UUID | None = None,
    performed_by: uuid.UUID | None = None,
    mine: bool = False,
    pcg_class: PcgClass | None = None,
    severity: Severity | None = None,
    agreement: AgreementLevel | None = None,
    examined_from: date | None = None,
    examined_to: date | None = None,
    q: str | None = Query(default=None, min_length=2, max_length=100),
    needs_review: bool = False,
    sort: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    with_total: bool = False,
):
    rec_cnt = (
        select(Recording.examination_id.label("eid"), func.count().label("cnt"))
        .where(Recording.deleted_at.is_(None), Recording.kind == RecordingKind.audio)
        .group_by(Recording.examination_id)
        .subquery()
    )
    sorts = {
        "examined_at": Examination.examined_at,
        "priority": PRIORITY_RANK,
        "status": cast(Examination.status, Text),
        "created_at": Examination.created_at,
        "severity": SEV_RANK,
    }
    keys = parse_sort(sort, sorts, "-examined_at")
    stmt = (
        select(
            Examination,
            Patient,
            AnalysisResult.pcg_class.label("ai_class"),
            AnalysisResult.severity.label("ai_severity"),
            AnalysisResult.confidence.label("ai_conf"),
            DoctorConclusion.status.label("concl_status"),
            func.coalesce(rec_cnt.c.cnt, 0).label("rec_count"),
        )
        .join(Patient, Patient.id == Examination.patient_id)
        .outerjoin(
            AnalysisResult, (AnalysisResult.examination_id == Examination.id) & AnalysisResult.is_current
        )
        .outerjoin(
            DoctorConclusion,
            (DoctorConclusion.examination_id == Examination.id) & DoctorConclusion.is_current,
        )
        .outerjoin(rec_cnt, rec_cnt.c.eid == Examination.id)
        .where(Examination.deleted_at.is_(None))
    )
    if user.role == UserRole.nurse:
        stmt = stmt.where(nurse_scope(user))
    if status:
        stmt = stmt.where(Examination.status.in_(status))
    if needs_review:
        stmt = stmt.where(Examination.status.in_([ExamStatus.ai_ready, ExamStatus.in_review]))
    if priority:
        stmt = stmt.where(Examination.priority == priority)
    if patient_id:
        stmt = stmt.where(Examination.patient_id == patient_id)
    if assigned_doctor_id:
        stmt = stmt.where(Examination.assigned_doctor_id == assigned_doctor_id)
    if performed_by:
        stmt = stmt.where(Examination.performed_by == performed_by)
    if mine:
        stmt = stmt.where((Examination.assigned_doctor_id == user.id) | (Examination.performed_by == user.id))
    if pcg_class:
        stmt = stmt.where(AnalysisResult.pcg_class == pcg_class)
    if severity:
        stmt = stmt.where(AnalysisResult.severity == severity)
    if agreement:
        stmt = stmt.where(DoctorConclusion.agreement_with_ai == agreement)
    if examined_from:
        stmt = stmt.where(
            Examination.examined_at >= datetime.combine(examined_from, time.min, tzinfo=exam_service.TASHKENT)
        )
    if examined_to:
        stmt = stmt.where(
            Examination.examined_at
            < datetime.combine(examined_to + timedelta(days=1), time.min, tzinfo=exam_service.TASHKENT)
        )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Examination.exam_no.ilike(like)
            | Patient.mrn.ilike(like)
            | func.concat(Patient.last_name, " ", Patient.first_name).ilike(like)
        )
    stmt = with_sort_columns(stmt, keys, Examination.id)
    rows, page = await paginate(
        db,
        stmt,
        id_col=Examination.id,
        sort=keys,
        cursor=cursor,
        limit=clamp_limit(limit),
        with_total=with_total,
    )
    um = await exam_service.users_map(
        db, {r[0].performed_by for r in rows} | {r[0].assigned_doctor_id for r in rows}
    )
    items = []
    for r in rows:
        e, p = r[0], r[1]
        items.append(
            {
                "id": e.id,
                "exam_no": e.exam_no,
                "patient": {
                    "id": p.id,
                    "mrn": p.mrn,
                    "full_name": full_name(p),
                    "age": calc_age(p.birth_date),
                    "gender": p.gender.value,
                },
                "status": e.status,
                "priority": e.priority,
                "examined_at": e.examined_at,
                "assigned_doctor": exam_service.person(um.get(e.assigned_doctor_id)),
                "performed_by": exam_service.person(um.get(e.performed_by)),
                "recording_count": r.rec_count,
                "ai": {
                    "pcg_class": r.ai_class.value,
                    "severity": r.ai_severity.value,
                    "confidence": float(r.ai_conf),
                }
                if r.ai_class
                else None,
                "conclusion_status": r.concl_status.value if r.concl_status else None,
            }
        )
    return {"items": items, "page": page}


@router.get("/{exam_id}", response_model=ExamDetail)
async def get_exam(exam_id: uuid.UUID, db: DB, user: CurrentUser):
    exam = await get_exam_for(db, user, exam_id)
    audit_service.log_event(
        db,
        AuditAction.read,
        user=user,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
    )
    detail = await exam_service.exam_detail(db, exam, user)
    return JSONResponse(
        content=orjson.loads(ExamDetail.model_validate(detail).model_dump_json()), headers=etag(exam.version)
    )


@router.patch(
    "/{exam_id}",
    response_model=ExamDetail,
    responses={409: {"description": "VERSION_CONFLICT / INVALID_STATE"}},
)
async def update_exam(exam_id: uuid.UUID, body: ExamUpdate, request: Request, db: DB, user: CurrentUser):
    exam = await get_exam_for(db, user, exam_id)
    check_if_match(request, exam.version)
    data = body.model_dump(exclude_unset=True)
    if user.role == UserRole.nurse and not (
        exam.performed_by == user.id and exam.status in (ExamStatus.draft, ExamStatus.uploaded)
    ):
        await deny(user, "exam:update", f"examination:{exam.id}")
    if exam.status in (ExamStatus.completed, ExamStatus.cancelled):
        raise invalid_state(exam.status.value, [])
    if exam.status in (ExamStatus.processing, ExamStatus.queued) and CLINICAL_FIELDS & data.keys():
        raise invalid_state(exam.status.value, [], "Tahlil jarayonida klinik maydonlar o'zgarmaydi")
    new_doctor = data.pop("assigned_doctor_id", None) if "assigned_doctor_id" in data else None
    before = {k: getattr(exam, k) for k in data}
    for k, v in data.items():
        setattr(exam, k, v)
    if new_doctor and new_doctor != exam.assigned_doctor_id:
        await exam_service.assign_doctor(db, exam, new_doctor, user)
    exam.version += 1
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
        changes=audit_service.diff(before, data),
    )
    await db.flush()
    return await exam_service.exam_detail(db, exam, user)


@router.post("/{exam_id}/assign", response_model=ExamDetail)
async def assign(exam_id: uuid.UUID, body: AssignIn, db: DB, user: User = Perm(Permission.exam_assign)):
    exam = await get_exam_for(db, user, exam_id)
    if user.role == UserRole.doctor and body.doctor_id != user.id:
        await deny(user, "exam:assign", f"examination:{exam.id}")
    if exam.status in (ExamStatus.completed, ExamStatus.cancelled):
        raise invalid_state(exam.status.value, [])
    prev = exam.assigned_doctor_id
    await exam_service.assign_doctor(db, exam, body.doctor_id, user)
    audit_service.log_event(
        db,
        AuditAction.assign,
        user=user,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
        changes={
            "before": {"assigned_doctor_id": str(prev) if prev else None},
            "after": {"assigned_doctor_id": str(body.doctor_id)},
        },
    )
    await db.flush()
    return await exam_service.exam_detail(db, exam, user)


@router.post("/{exam_id}/cancel", response_model=ExamDetail)
async def cancel(exam_id: uuid.UUID, body: CancelIn, db: DB, user: User = Perm(Permission.exam_cancel)):
    exam = await get_exam_for(db, user, exam_id)
    if user.role == UserRole.nurse and not (
        exam.performed_by == user.id and exam.status in (ExamStatus.draft, ExamStatus.uploaded)
    ):
        if exam.status not in (ExamStatus.draft, ExamStatus.uploaded):
            raise invalid_state(exam.status.value, allowed_targets(exam.status, "nurse"))
        await deny(user, "exam:cancel", f"examination:{exam.id}")
    await analysis_service.cancel_job_if_active(db, exam)
    exam = await transition(db, exam, ExamStatus.cancelled, user, body.reason)
    await db.flush()
    return await exam_service.exam_detail(db, exam, user)


@router.delete("/{exam_id}", status_code=204)
async def delete_exam(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.exam_delete)):
    exam = await load_exam(db, exam_id)
    if exam.status not in (ExamStatus.draft, ExamStatus.cancelled, ExamStatus.failed):
        raise invalid_state(exam.status.value, ["draft", "cancelled", "failed"])
    from app.db.base import utcnow

    exam.deleted_at = utcnow()
    audit_service.log_event(
        db,
        AuditAction.delete,
        user=user,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
    )
    return Response(status_code=204)


@router.post(
    "/{exam_id}/analyze",
    status_code=202,
    response_model=AnalyzeAccepted,
    responses={
        409: {"description": "INVALID_STATE"},
        422: {"description": "NO_AUDIO_RECORDINGS / RECORDINGS_NOT_VALIDATED"},
    },
)
async def analyze(
    exam_id: uuid.UUID,
    request: Request,
    db: DB,
    user: User = Perm(Permission.analysis_start),
    body: AnalyzeIn | None = None,
):
    body = body or AnalyzeIn()
    endpoint = f"analyze:{exam_id}"
    if (rep := await idempotency.replay(db, request, user.id, endpoint)) is not None:
        return rep
    exam = await get_exam_for(db, user, exam_id)
    await rate_limit.hit("ai", str(user.id), get_settings().rate_limit_ai_user)
    if body.force_rerun and not has_permission(user.role, Permission.analysis_rerun):
        await deny(user, Permission.analysis_rerun, f"examination:{exam.id}")
    job = await analysis_service.enqueue(
        db,
        exam,
        user,
        AnalysisOptions(llm=body.llm, drug_suggestions=body.drug_suggestions),
        rerun=body.force_rerun,
    )
    out = {
        "job_id": str(job.id),
        "status": "pending",
        "exam_status": "queued",
        "events": f"/api/v1/examinations/{exam.id}/events",
    }
    await idempotency.store(db, request, user.id, endpoint, 202, out)
    return JSONResponse(out, status_code=202)


@router.post("/{exam_id}/reanalyze", status_code=202, response_model=AnalyzeAccepted)
async def reanalyze(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.analysis_rerun)):
    exam = await get_exam_for(db, user, exam_id)
    await rate_limit.hit("ai", str(user.id), get_settings().rate_limit_ai_user)
    job = await analysis_service.enqueue(db, exam, user, rerun=True)
    return JSONResponse(
        {
            "job_id": str(job.id),
            "status": "pending",
            "exam_status": "queued",
            "events": f"/api/v1/examinations/{exam.id}/events",
        },
        status_code=202,
    )


@router.get("/{exam_id}/status", response_model=StatusOut)
async def exam_status(exam_id: uuid.UUID, db: DB, user: CurrentUser):
    exam = await get_exam_for(db, user, exam_id)
    job = await db.get(AnalysisJob, exam.current_job_id) if exam.current_job_id else None
    hist = (
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
    return {
        "status": exam.status,
        "job": job,
        "history": [
            {
                "from": h.from_status.value if h.from_status else None,
                "to": h.to_status.value,
                "at": h.created_at,
                "by": str(h.changed_by) if h.changed_by else None,
            }
            for h in hist
        ],
    }


# ------------------------------------------------------------------------------------------- SSE
def _sse(env: dict) -> str:
    return f"event: {env['type']}\nid: {env['id']}\ndata: {orjson.dumps(env).decode()}\n\n"


async def sse_generator(
    exam_id: str, last_event_id: str | None, heartbeat: float = 15.0
) -> AsyncIterator[str]:
    sub = bus.subscribe([f"exam:{exam_id}"])
    try:
        for env in await bus.history(exam_id, last_event_id):
            yield _sse(env)
        while True:
            try:
                env = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield _sse(env)
    finally:
        bus.unsubscribe(sub)


@router.get("/{exam_id}/events")
async def exam_events(exam_id: uuid.UUID, request: Request, db: DB, user: CurrentUser):
    """SSE fallback for one examination (Bearer header; supports Last-Event-ID replay, 15 s heartbeat)."""
    exam = await get_exam_for(db, user, exam_id)
    return StreamingResponse(
        sse_generator(str(exam.id), request.headers.get("last-event-id")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_ = (AppError, notification_service, json_response)

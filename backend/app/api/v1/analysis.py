"""Analysis results, segments and AI report endpoints (doc 01 section 3.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.config import get_settings
from app.core import rate_limit
from app.core.deps import DB, CurrentUser, Perm
from app.core.errors import not_found
from app.core.permissions import Permission
from app.core.route import TxRoute
from app.models.analysis import AnalysisResult, PcgSegment
from app.models.clinical import AiReport
from app.models.enums import AuditAction, ExamStatus, UserRole
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES, json_response
from app.schemas.exams import AiReportOut, AiReportOutNurse, AnalysisOut, SegmentOut
from app.services import analysis_service, audit_service, exam_service
from app.services.exam_service import current_analysis, current_report, get_exam_for

router = APIRouter(prefix="/examinations", tags=["analysis"], route_class=TxRoute, responses=ERROR_RESPONSES)


@router.get("/{exam_id}/analysis", response_model=AnalysisOut)
async def get_analysis(exam_id: uuid.UUID, db: DB, user: CurrentUser):
    exam = await get_exam_for(db, user, exam_id)
    res = await current_analysis(db, exam.id)
    if res is None:
        raise not_found("Tahlil natijasi")
    return await exam_service.analysis_dict(db, res)


@router.get("/{exam_id}/analysis/history", response_model=list[AnalysisOut])
async def analysis_history(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.report_read_full)):
    exam = await get_exam_for(db, user, exam_id)
    rows = (
        (
            await db.execute(
                select(AnalysisResult)
                .where(AnalysisResult.examination_id == exam.id)
                .order_by(AnalysisResult.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await exam_service.analysis_dict(db, r) for r in rows]


@router.get("/{exam_id}/segments")
async def get_segments(
    exam_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    recording_id: uuid.UUID | None = None,
    type: str | None = Query(default=None, max_length=12),
):
    exam = await get_exam_for(db, user, exam_id)
    res = await current_analysis(db, exam.id)
    if res is None:
        return {"items": []}
    q = select(PcgSegment).where(PcgSegment.analysis_result_id == res.id)
    if recording_id:
        q = q.where(PcgSegment.recording_id == recording_id)
    if type:
        q = q.where(PcgSegment.type == type)
    rows = (
        (await db.execute(q.order_by(PcgSegment.recording_id, PcgSegment.start_ms, PcgSegment.seq)))
        .scalars()
        .all()
    )
    return {"items": [SegmentOut.model_validate(r, from_attributes=True) for r in rows]}


@router.get("/{exam_id}/report", responses={200: {"model": AiReportOut}})
async def get_report(exam_id: uuid.UUID, db: DB, user: CurrentUser):
    """Full report for doctor/admin; restricted variant (no differential/patient text/drugs) for nurses."""
    exam = await get_exam_for(db, user, exam_id)
    rep = await current_report(db, exam.id)
    if rep is None:
        raise not_found("AI hisobot")
    if user.role == UserRole.nurse:
        return json_response(AiReportOutNurse.model_validate(exam_service.report_nurse(rep)))
    if user.role == UserRole.doctor and exam.status == ExamStatus.ai_ready:
        await exam_service.open_for_review(db, exam, user)
    audit_service.log_event(
        db,
        AuditAction.read,
        user=user,
        resource_type="ai_report",
        resource_id=rep.id,
        patient_id=exam.patient_id,
    )
    return json_response(AiReportOut.model_validate(exam_service.report_full(rep)))


@router.post("/{exam_id}/report/regenerate", status_code=200, response_model=AiReportOut)
async def regenerate(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.report_regenerate)):
    exam = await get_exam_for(db, user, exam_id)
    await rate_limit.hit("ai", str(user.id), get_settings().rate_limit_ai_user)
    from app.core.errors import invalid_state

    if exam.status not in (ExamStatus.ai_ready, ExamStatus.in_review):
        raise invalid_state(
            exam.status.value, ["ai_ready", "in_review"], "Qayta yaratish faqat tahlil tayyor bo'lganda"
        )
    rep = await analysis_service.regenerate_report(db, exam, user)
    await db.flush()
    return exam_service.report_full(rep)


@router.get("/{exam_id}/report/history", response_model=list[AiReportOut])
async def report_history(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.report_read_full)):
    exam = await get_exam_for(db, user, exam_id)
    rows = (
        (
            await db.execute(
                select(AiReport)
                .where(AiReport.examination_id == exam.id)
                .order_by(AiReport.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [exam_service.report_full(r) for r in rows]

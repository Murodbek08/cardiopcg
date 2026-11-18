from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.core import idempotency
from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.errors import not_found
from app.core.http import etag
from app.core.permissions import Permission
from app.core.route import TxRoute
from app.models.enums import AuditAction, ExamStatus, UserRole
from app.models.user import User
from app.schemas.clinical import AmendIn, ConclusionIn, ConclusionOut, SignOut
from app.schemas.common import ERROR_RESPONSES
from app.services import audit_service, conclusion_service, realtime
from app.services.exam_service import (
    conclusion_visible_to_nurse,
    current_conclusion,
    get_exam_for,
    open_for_review,
)

router = APIRouter(
    prefix="/examinations", tags=["conclusions"], route_class=TxRoute, responses=ERROR_RESPONSES
)


@router.get("/{exam_id}/conclusion", response_model=ConclusionOut)
async def get_conclusion(exam_id: uuid.UUID, db: DB, user: CurrentUser):
    exam = await get_exam_for(db, user, exam_id)
    c = await current_conclusion(db, exam.id)
    if user.role == UserRole.nurse:
        if not conclusion_visible_to_nurse(c):
            await deny(user, Permission.conclusion_read, f"conclusion:{exam.id}")
    else:
        if user.role == UserRole.doctor and exam.status == ExamStatus.ai_ready:
            await open_for_review(db, exam, user)  # first open: ai_ready -> in_review
        audit_service.log_event(
            db,
            AuditAction.read,
            user=user,
            resource_type="conclusion",
            resource_id=c.id if c else None,
            patient_id=exam.patient_id,
        )
    if c is None:
        await db.commit()  # keep the ai_ready -> in_review transition even though there is no draft yet
        await realtime.flush_events(db)
        raise not_found("Xulosa")
    return JSONResponse(ConclusionOut.model_validate(c).model_dump(mode="json"), headers=etag(c.version))


@router.put(
    "/{exam_id}/conclusion",
    response_model=ConclusionOut,
    responses={409: {"description": "VERSION_CONFLICT / INVALID_STATE"}},
)
async def put_conclusion(
    exam_id: uuid.UUID,
    body: ConclusionIn,
    request: Request,
    db: DB,
    user: User = Perm(Permission.conclusion_write),
):
    exam = await get_exam_for(db, user, exam_id)
    c = await conclusion_service.put_draft(db, request, exam, user, body)
    await db.flush()
    return JSONResponse(ConclusionOut.model_validate(c).model_dump(mode="json"), headers=etag(c.version))


@router.post(
    "/{exam_id}/conclusion/sign",
    response_model=SignOut,
    responses={
        409: {"description": "PRESCRIPTION_PENDING / INVALID_STATE"},
        422: {"description": "DISAGREEMENT_REASON_REQUIRED"},
    },
)
async def sign_conclusion(
    exam_id: uuid.UUID, request: Request, db: DB, user: User = Perm(Permission.conclusion_sign)
):
    endpoint = f"sign:{exam_id}"
    if (rep := await idempotency.replay(db, request, user.id, endpoint)) is not None:
        return rep
    exam = await get_exam_for(db, user, exam_id)
    c, exam = await conclusion_service.sign(db, exam, user)
    out = {
        "id": str(c.id),
        "status": c.status.value,
        "signed_at": c.signed_at.isoformat(),
        "signature_hash": c.signature_hash,
        "exam_status": exam.status.value,
    }
    await idempotency.store(db, request, user.id, endpoint, 200, out)
    return out


@router.post("/{exam_id}/conclusion/amend", response_model=ConclusionOut, status_code=201)
async def amend_conclusion(
    exam_id: uuid.UUID, body: AmendIn, db: DB, user: User = Perm(Permission.conclusion_sign)
):
    exam = await get_exam_for(db, user, exam_id)
    c = await conclusion_service.amend(db, exam, user, body)
    await db.flush()
    return c


@router.get("/{exam_id}/conclusion/history", response_model=list[ConclusionOut])
async def conclusion_history(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.conclusion_read)):
    exam = await get_exam_for(db, user, exam_id)
    return await conclusion_service.history(db, exam.id)


_ = Response

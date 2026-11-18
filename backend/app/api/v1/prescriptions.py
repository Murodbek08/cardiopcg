from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.config import get_settings
from app.core import rate_limit
from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.errors import AppError, not_found
from app.core.permissions import Permission, has_permission
from app.core.route import TxRoute
from app.models.enums import AuditAction, ConclusionStatus, ExamStatus, UserRole
from app.models.user import User
from app.schemas.clinical import (
    ApproveItemIn,
    PrescriptionItemIn,
    PrescriptionItemOut,
    PrescriptionItemPatch,
    PrescriptionOut,
    RejectItemIn,
)
from app.schemas.common import ERROR_RESPONSES
from app.services import analysis_service, audit_service
from app.services import prescription_service as ps
from app.services.exam_service import (
    DISCLAIMER_RX,
    conclusion_visible_to_nurse,
    current_conclusion,
    get_exam_for,
)

router = APIRouter(tags=["prescriptions"], route_class=TxRoute, responses=ERROR_RESPONSES)

_CONFLICTS = {409: {"description": "ALLERGY_OVERRIDE_REQUIRED / INVALID_STATE"}}


@router.get("/examinations/{exam_id}/prescription", response_model=PrescriptionOut)
async def get_prescription(exam_id: uuid.UUID, db: DB, user: CurrentUser):
    exam = await get_exam_for(db, user, exam_id)
    rx = await ps.get_prescription(db, exam.id)
    if user.role == UserRole.nurse:
        # nurses: only approved items, and only after the doctor signed the conclusion
        if not conclusion_visible_to_nurse(await current_conclusion(db, exam.id)):
            await deny(user, Permission.prescription_read, f"prescription:{exam.id}")
        if rx is None:
            raise not_found("Retsept")
        return await ps.prescription_out(db, rx, only_approved=True)
    if not has_permission(user.role, Permission.prescription_read):
        await deny(user, Permission.prescription_read)
    if rx is None:
        raise not_found("Retsept")
    audit_service.log_event(
        db,
        AuditAction.read,
        user=user,
        resource_type="prescription",
        resource_id=rx.id,
        patient_id=exam.patient_id,
    )
    return await ps.prescription_out(db, rx)


@router.post(
    "/examinations/{exam_id}/prescription/items",
    status_code=201,
    response_model=PrescriptionItemOut,
    responses=_CONFLICTS,
)
async def add_item(
    exam_id: uuid.UUID, body: PrescriptionItemIn, db: DB, user: User = Perm(Permission.prescription_write)
):
    exam = await get_exam_for(db, user, exam_id)
    it = await ps.add_item(db, exam, body.model_dump(), user)
    return ps._item_dict(it)


@router.patch("/prescription-items/{item_id}", response_model=PrescriptionItemOut, responses=_CONFLICTS)
async def patch_item(
    item_id: uuid.UUID, body: PrescriptionItemPatch, db: DB, user: User = Perm(Permission.prescription_write)
):
    it, rx, exam = await ps.item_for(db, item_id)
    await ps.assert_editable(db, exam)
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(it, k) for k in data}
    for k, v in data.items():
        setattr(it, k, v)
    # a doctor edit of an approved/rejected row puts it back to review; safety is recomputed
    if it.status != ps.PrescriptionStatus.suggested:
        it.status = ps.PrescriptionStatus.suggested
    it.safety_pending = True
    await db.flush()
    await ps.run_safety_check(db, rx)
    ps.refresh_status(rx, await ps.items_of(db, rx))
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="prescription_item",
        resource_id=it.id,
        patient_id=exam.patient_id,
        changes=audit_service.diff(before, data),
    )
    return ps._item_dict(it)


@router.delete("/prescription-items/{item_id}", status_code=204)
async def delete_item(item_id: uuid.UUID, db: DB, user: User = Perm(Permission.prescription_write)):
    it, rx, exam = await ps.item_for(db, item_id)
    await ps.assert_editable(db, exam)
    await db.delete(it)
    await db.flush()
    ps.refresh_status(rx, await ps.items_of(db, rx))
    await ps.run_safety_check(db, rx)
    audit_service.log_event(
        db,
        AuditAction.delete,
        user=user,
        resource_type="prescription_item",
        resource_id=item_id,
        patient_id=exam.patient_id,
    )
    return Response(status_code=204)


@router.post(
    "/prescription-items/{item_id}/approve", response_model=PrescriptionItemOut, responses=_CONFLICTS
)
async def approve_item(
    item_id: uuid.UUID,
    db: DB,
    user: User = Perm(Permission.prescription_approve),
    body: ApproveItemIn | None = None,
):
    it, rx, exam = await ps.item_for(db, item_id)
    await ps.approve_item(db, it, rx, exam, user, body.override_reason if body else None)
    return ps._item_dict(it)


@router.post("/prescription-items/{item_id}/reject", response_model=PrescriptionItemOut, responses=_CONFLICTS)
async def reject_item(
    item_id: uuid.UUID, body: RejectItemIn, db: DB, user: User = Perm(Permission.prescription_approve)
):
    it, rx, exam = await ps.item_for(db, item_id)
    await ps.reject_item(db, it, rx, exam, user, body.reason)
    return ps._item_dict(it)


@router.post("/examinations/{exam_id}/prescription/approve")
async def approve_all(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.prescription_approve)):
    exam = await get_exam_for(db, user, exam_id)
    return await ps.approve_all(db, exam, user)


@router.post("/examinations/{exam_id}/prescription/safety-check", response_model=PrescriptionOut)
async def safety_check(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.prescription_write)):
    exam = await get_exam_for(db, user, exam_id)
    rx = await ps.get_prescription(db, exam.id)
    if rx is None:
        raise not_found("Retsept")
    await ps.run_safety_check(db, rx)
    return await ps.prescription_out(db, rx)


@router.post("/examinations/{exam_id}/prescription/regenerate", response_model=PrescriptionOut)
async def regenerate(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.prescription_write)):
    exam = await get_exam_for(db, user, exam_id)
    await ps.assert_editable(db, exam)
    if exam.status not in (ExamStatus.ai_ready, ExamStatus.in_review):
        from app.core.errors import invalid_state

        raise invalid_state(exam.status.value, ["ai_ready", "in_review"])
    await rate_limit.hit("ai", str(user.id), get_settings().rate_limit_ai_user)
    await analysis_service.regenerate_report(db, exam, user, want_report=False, want_drugs=True)
    rx = await ps.get_prescription(db, exam.id)
    if rx is None:
        raise AppError(409, "NO_SUGGESTIONS", "AI dori taklifi qaytarmadi")
    return await ps.prescription_out(db, rx)


_ = (ConclusionStatus, DISCLAIMER_RX)

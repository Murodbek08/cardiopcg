from __future__ import annotations

import uuid

import orjson
from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from app.config import get_settings
from app.core import idempotency, rate_limit
from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.errors import AppError, invalid_state, not_found
from app.core.permissions import Permission, has_permission
from app.core.route import TxRoute
from app.models.enums import AuditAction, AuscultationSite, ExamStatus, RecordingKind, UserRole
from app.models.examination import Examination
from app.models.recording import Recording
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.exams import RecordingOut, RecordingPatch
from app.services import audit_service, recording_service
from app.services.exam_service import get_exam_for, recording_dict
from app.services.storage import get_storage

router = APIRouter(tags=["recordings"], route_class=TxRoute, responses=ERROR_RESPONSES)

_UPLOAD_ERRORS = {
    413: {"description": "FILE_TOO_LARGE"},
    415: {"description": "UNSUPPORTED_MEDIA_TYPE"},
    409: {"description": "DUPLICATE_RECORDING / SITE_ALREADY_RECORDED / INVALID_STATE"},
}


@router.post(
    "/examinations/{exam_id}/recordings",
    status_code=201,
    response_model=RecordingOut,
    responses=_UPLOAD_ERRORS,
)
async def upload_recording(
    exam_id: uuid.UUID,
    request: Request,
    db: DB,
    user: User = Perm(Permission.recording_upload),
    file: UploadFile = File(...),
    site: AuscultationSite | None = Form(default=None),
    kind: RecordingKind = Form(default=RecordingKind.audio),
    notes: str | None = Form(default=None, max_length=1000),
    replace: bool = Query(default=False),
):
    endpoint = f"upload:{exam_id}"
    if (rep := await idempotency.replay(db, request, user.id, endpoint)) is not None:
        return rep
    exam = await get_exam_for(db, user, exam_id)
    if user.role == UserRole.nurse and exam.status not in (
        ExamStatus.draft,
        ExamStatus.uploaded,
        ExamStatus.failed,
    ):
        raise invalid_state(exam.status.value, ["draft", "uploaded", "failed"])
    await rate_limit.hit("upload", str(user.id), get_settings().rate_limit_upload_user)
    try:
        rec = await recording_service.upload(
            db, user, exam, file, site=site, kind=kind, notes=notes, replace=replace
        )
    except AppError as exc:
        await recording_service.reject_audit(user, exam, exc)
        raise
    out = RecordingOut.model_validate(recording_dict(rec)).model_dump(mode="json")
    await idempotency.store(db, request, user.id, endpoint, 201, out)
    return JSONResponse(out, status_code=201)


@router.get("/examinations/{exam_id}/recordings", response_model=list[RecordingOut])
async def list_recordings(exam_id: uuid.UUID, db: DB, user: CurrentUser, include_derived: bool = True):
    exam = await get_exam_for(db, user, exam_id)
    q = select(Recording).where(Recording.examination_id == exam.id, Recording.deleted_at.is_(None))
    if not include_derived:
        q = q.where(Recording.kind.in_([RecordingKind.audio, RecordingKind.other_image]))
    rows = (await db.execute(q.order_by(Recording.created_at))).scalars().all()
    return [recording_dict(r) for r in rows]


async def _rec_and_exam(db, user: User, rid: uuid.UUID) -> tuple[Recording, Examination]:
    rec = await recording_service.load_recording(db, rid)
    exam = await get_exam_for(db, user, rec.examination_id)
    return rec, exam


@router.get("/recordings/{rid}", response_model=RecordingOut)
async def get_recording(rid: uuid.UUID, db: DB, user: CurrentUser):
    rec, _ = await _rec_and_exam(db, user, rid)
    return recording_dict(rec)


@router.get("/recordings/{rid}/file")
async def download_recording(rid: uuid.UUID, request: Request, db: DB, user: CurrentUser):
    """Stream the stored file (auth + audit); HTTP Range supported (206)."""
    rec, exam = await _rec_and_exam(db, user, rid)
    size = int(rec.size_bytes)
    rng = recording_service.parse_range(request.headers.get("range"), size)
    audit_service.log_event(
        db,
        AuditAction.download,
        user=user,
        resource_type="recording",
        resource_id=rec.id,
        patient_id=exam.patient_id,
        meta={"range": bool(rng)},
    )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{rec.original_filename}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if rng:
        start, end = rng
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            recording_service.stream_range(rec.storage_key, start, end),
            status_code=206,
            media_type=rec.mime_type,
            headers=headers,
        )
    headers["Content-Length"] = str(size)
    return StreamingResponse(
        recording_service.stream_range(rec.storage_key, 0, size - 1),
        media_type=rec.mime_type,
        headers=headers,
    )


@router.get("/recordings/{rid}/waveform")
async def recording_waveform(rid: uuid.UUID, db: DB, user: CurrentUser):
    rec, exam = await _rec_and_exam(db, user, rid)
    data = await recording_service.waveform_for(rec, exam.id)
    return Response(content=orjson.dumps(data), media_type="application/json")


@router.get("/recordings/{rid}/spectrogram")
async def recording_spectrogram(rid: uuid.UUID, db: DB, user: CurrentUser):
    rec, exam = await _rec_and_exam(db, user, rid)
    derived = (
        (
            await db.execute(
                select(Recording)
                .where(
                    Recording.derived_from_id == rec.id,
                    Recording.kind == RecordingKind.spectrogram,
                    Recording.deleted_at.is_(None),
                )
                .order_by(Recording.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if derived is None and rec.kind == RecordingKind.spectrogram:
        derived = rec
    if derived is None:
        raise not_found("Spektrogramma (tahlildan keyin hosil bo'ladi)")
    data = await get_storage().get_bytes(derived.storage_key)
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.patch("/recordings/{rid}", response_model=RecordingOut)
async def patch_recording(
    rid: uuid.UUID, body: RecordingPatch, db: DB, user: User = Perm(Permission.recording_upload)
):
    rec, exam = await _rec_and_exam(db, user, rid)
    if rec.kind != RecordingKind.audio:
        raise AppError(422, "VALIDATION_ERROR", "Faqat audio uchun site o'zgartiriladi")
    if exam.status not in (ExamStatus.draft, ExamStatus.uploaded, ExamStatus.failed):
        raise invalid_state(exam.status.value, ["draft", "uploaded", "failed"])
    if user.role == UserRole.nurse and exam.performed_by != user.id:
        await deny(user, "recording:update", f"recording:{rec.id}")
    clash = (
        await db.execute(
            select(Recording.id).where(
                Recording.examination_id == exam.id,
                Recording.kind == RecordingKind.audio,
                Recording.site == body.site,
                Recording.deleted_at.is_(None),
                Recording.id != rec.id,
            )
        )
    ).first()
    if clash:
        raise AppError(409, "SITE_ALREADY_RECORDED", "Bu nuqta uchun yozuv mavjud")
    before = rec.site.value if rec.site else None
    rec.site = body.site
    audit_service.log_event(
        db,
        AuditAction.update,
        user=user,
        resource_type="recording",
        resource_id=rec.id,
        patient_id=exam.patient_id,
        changes={"before": {"site": before}, "after": {"site": body.site.value}},
    )
    return recording_dict(rec)


@router.delete("/recordings/{rid}", status_code=204)
async def delete_recording(rid: uuid.UUID, db: DB, user: CurrentUser):
    rec, exam = await _rec_and_exam(db, user, rid)
    if not has_permission(user.role, Permission.recording_delete):
        await deny(user, Permission.recording_delete)
    from app.core.permissions import policy

    if not policy.can(user, Permission.recording_delete, exam):
        if user.role == UserRole.doctor:
            raise invalid_state(exam.status.value, [], "Yakunlangan tekshiruv yozuvlari o'chirilmaydi")
        await deny(user, Permission.recording_delete, f"recording:{rec.id}")
    if exam.status in (ExamStatus.queued, ExamStatus.processing):
        raise invalid_state(exam.status.value, [], "Tahlil jarayonida yozuv o'chirilmaydi")
    await recording_service.delete_recording(db, user, exam, rec)
    return Response(status_code=204)

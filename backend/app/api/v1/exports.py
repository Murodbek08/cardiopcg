from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from app.config import get_settings
from app.core import rate_limit
from app.core.deps import DB, CurrentUser, Perm, deny
from app.core.errors import AppError, forbidden, not_found
from app.core.permissions import Permission
from app.core.route import TxRoute
from app.models.clinical import DoctorConclusion
from app.models.enums import (
    AuditAction,
    ConclusionStatus,
    ExamStatus,
    JobStatus,
    PrescriptionStatus,
    RecordingKind,
    UserRole,
)
from app.models.examination import Examination
from app.models.recording import Recording
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.misc import CsvExportIn
from app.services import (
    audit_service,
    export_service,
    prescription_service,
    realtime,
    recording_service,
    report_pdf,
    settings_service,
)
from app.services.exam_service import (
    analysis_dict,
    conclusion_out,
    current_analysis,
    current_conclusion,
    current_report,
    get_exam_for,
    report_full,
)
from app.services.patient_service import calc_age, full_name
from app.services.storage import get_storage, sign_download, verify_download

router = APIRouter(tags=["export"], route_class=TxRoute, responses=ERROR_RESPONSES)


@router.get("/examinations/{exam_id}/export/pdf", responses={200: {"content": {"application/pdf": {}}}})
async def export_pdf(exam_id: uuid.UUID, db: DB, user: User = Perm(Permission.export_pdf)):
    exam = await get_exam_for(db, user, exam_id)
    await rate_limit.hit("export", str(user.id), get_settings().rate_limit_export_user, 3600)
    conclusion = await current_conclusion(db, exam.id)
    signed = conclusion is not None and conclusion.status in (
        ConclusionStatus.signed,
        ConclusionStatus.amended,
    )
    is_nurse = user.role == UserRole.nurse
    if is_nurse and not (exam.status == ExamStatus.completed and signed):
        await deny(user, Permission.export_pdf, f"examination:{exam.id}")
    draft = not (exam.status == ExamStatus.completed and signed)

    from app.models.patient import Patient

    patient = await db.get(Patient, exam.patient_id)
    analysis = await analysis_dict(db, await current_analysis(db, exam.id))
    recs = (
        (
            await db.execute(
                select(Recording)
                .where(
                    Recording.examination_id == exam.id,
                    Recording.kind == RecordingKind.audio,
                    Recording.deleted_at.is_(None),
                )
                .order_by(Recording.created_at)
            )
        )
        .scalars()
        .all()
    )
    rec_blocks: list[dict[str, Any]] = []
    storage = get_storage()
    for r in recs:
        try:
            peaks = await recording_service.waveform_for(r, exam.id)
        except Exception:
            peaks = None
        spect = (
            (
                await db.execute(
                    select(Recording)
                    .where(
                        Recording.derived_from_id == r.id,
                        Recording.kind == RecordingKind.spectrogram,
                        Recording.deleted_at.is_(None),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        png = None
        if spect:
            try:
                png = await storage.get_bytes(spect.storage_key)
            except Exception:
                png = None
        rec_blocks.append(
            {
                "site": r.site.value if r.site else "-",
                "duration_sec": float(r.duration_sec) if r.duration_sec else None,
                "snr_db": float(r.snr_db) if r.snr_db is not None else None,
                "peaks": peaks,
                "spectrogram_png": png,
            }
        )
    rep = await current_report(db, exam.id)
    report = report_full(rep) if rep and rep.status.value == "ready" else None
    if report and is_nurse:
        report = {**report, "differential_diagnoses": [], "recommended_tests": []}
    rx = await prescription_service.get_prescription(db, exam.id)
    drugs = []
    if rx and signed:
        drugs = [
            i for i in (await prescription_service.prescription_out(db, rx, only_approved=True))["items"]
        ]
    cfg = await settings_service.get_many(db, "clinic.name", "clinic.report_footer")
    doctor = await db.get(User, conclusion.doctor_id) if conclusion else None
    concl = conclusion_out(conclusion) if conclusion and (signed or not is_nurse) else None
    verify_url = None
    if signed and conclusion.signature_hash:
        verify_url = (
            f"{get_settings().public_url.rstrip('/')}/verify/{exam.exam_no}/{conclusion.signature_hash[:8]}"
        )
    pdf = report_pdf.build_pdf(
        clinic={"name": cfg["clinic.name"], "footer": cfg["clinic.report_footer"]},
        exam={
            "exam_no": exam.exam_no,
            "examined_at": exam.examined_at.strftime("%Y-%m-%d %H:%M"),
            "priority": exam.priority.value,
            "complaints": exam.complaints,
            "vitals": {
                "YUCh": exam.heart_rate_bpm,
                "AB": f"{exam.bp_systolic}/{exam.bp_diastolic}"
                if exam.bp_systolic and exam.bp_diastolic
                else None,
                "SpO2": exam.spo2_pct,
                "T": float(exam.temperature_c) if exam.temperature_c else None,
            },
        },
        patient={
            "full_name": full_name(patient),
            "mrn": patient.mrn,
            "age": calc_age(patient.birth_date),
            "gender": patient.gender.value,
            "birth_date": patient.birth_date.isoformat(),
        },
        analysis=analysis,
        recordings=rec_blocks,
        report=report,
        drugs=drugs,
        conclusion=concl,
        doctor={"full_name": doctor.full_name, "license_no": doctor.license_no} if doctor else None,
        verify_url=verify_url,
        draft=draft,
    )
    audit_service.log_event(
        db,
        AuditAction.export,
        user=user,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
        meta={"format": "pdf", "draft": draft, "bytes": len(pdf)},
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="CardioPCG_{exam.exam_no}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/export/csv", responses={202: {"description": "Large export queued"}})
async def export_csv(body: CsvExportIn, db: DB, user: User = Perm(Permission.export_csv)):
    await rate_limit.hit("export", str(user.id), get_settings().rate_limit_export_user, 3600)
    est = await export_service.count_estimate(db, body.kind)
    if est > get_settings().csv_sync_max_rows:
        job = await export_service.create_job(db, user, body.kind, body.model_dump(mode="json"))
        audit_service.log_event(
            db,
            AuditAction.export,
            user=user,
            resource_type="export_job",
            resource_id=job.id,
            meta={"kind": body.kind, "async": True},
        )
        realtime.after_commit(db, lambda: export_service.dispatch_export(job.id))
        return JSONResponse({"export_id": str(job.id)}, status_code=202)
    header, rows = await export_service.build_rows(
        db, user, body.kind, body.filters, body.columns, body.anonymize
    )
    data = export_service.to_csv_bytes(header, rows)
    audit_service.log_event(
        db,
        AuditAction.export,
        user=user,
        resource_type="csv",
        meta={"kind": body.kind, "rows": len(rows), "anonymize": body.anonymize},
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{body.kind}.csv"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/export/{export_id}")
async def export_status(export_id: uuid.UUID, db: DB, user: CurrentUser):
    from app.models.system import ExportJob

    job = await db.get(ExportJob, export_id)
    if job is None or job.user_id != user.id:
        raise not_found("Eksport")
    url = None
    if job.status == JobStatus.succeeded and job.file_key:
        url = "/api/v1/files/signed/" + sign_download(job.file_key, f"{job.kind}.csv", "text/csv", 900)
    return {
        "export_id": job.id,
        "status": job.status.value,
        "kind": job.kind,
        "file_url": url,
        "size_bytes": job.size_bytes,
        "error": job.error,
        "expires_at": job.expires_at,
    }


@router.get("/files/signed/{token}", include_in_schema=True)
async def signed_file(token: str):
    """Download an export through a short-lived HMAC-signed link (no Bearer needed)."""
    data = verify_download(token)
    storage = get_storage()
    size = await storage.size(data["k"])

    async def gen():
        async for chunk in storage.iter_range(data["k"], 0, size - 1):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type=data["t"],
        headers={
            "Content-Disposition": f'attachment; filename="{data["f"]}"',
            "Content-Length": str(size),
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/verify/{exam_no}/{hash8}")
async def verify_document(exam_no: str, hash8: str, db: DB):
    """Public document verification (QR target). Returns no PHI."""
    await rate_limit.hit("verify", "global", 120)
    if len(hash8) != 8 or not all(c in "0123456789abcdef" for c in hash8.lower()):
        raise AppError(422, "VALIDATION_ERROR", "hash noto'g'ri")
    row = (
        await db.execute(
            select(DoctorConclusion, Examination)
            .join(Examination, Examination.id == DoctorConclusion.examination_id)
            .where(
                Examination.exam_no == exam_no,
                DoctorConclusion.is_current,
                DoctorConclusion.status.in_([ConclusionStatus.signed, ConclusionStatus.amended]),
            )
        )
    ).first()
    if row is None or not row[0].signature_hash or not row[0].signature_hash.startswith(hash8.lower()):
        return {"valid": False}
    doc = await db.get(User, row[0].doctor_id)
    return {
        "valid": True,
        "exam_no": exam_no,
        "signed_at": row[0].signed_at,
        "doctor": doc.full_name if doc else None,
        "amended": row[0].status == ConclusionStatus.amended,
    }


_ = (forbidden, PrescriptionStatus)

"""Recording upload / delete / waveform / ranged download."""

from __future__ import annotations

import contextlib
import hashlib
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import soundfile as sf
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, conflict, invalid_state, not_found, unprocessable
from app.db.base import new_id, utcnow
from app.models.enums import (
    AuditAction,
    AuscultationSite,
    ExamStatus,
    NotificationType,
    RecordingKind,
    RecordingStatus,
)
from app.models.examination import Examination
from app.models.recording import Recording
from app.models.user import User
from app.services import (
    analysis_service,
    antivirus,
    audit_service,
    notification_service,
    realtime,
    settings_service,
    upload_validator,
)
from app.services.exam_state import transition
from app.services.storage import get_storage

UPLOADABLE = {ExamStatus.draft, ExamStatus.uploaded, ExamStatus.failed}
CHUNK = 1024 * 1024


async def load_recording(db: AsyncSession, rid: uuid.UUID) -> Recording:
    r = await db.get(Recording, rid)
    if r is None or r.deleted_at is not None:
        raise not_found("Yozuv")
    return r


async def _spool(file: UploadFile, max_bytes: int, dest: Path) -> tuple[int, str]:
    """Stream the upload to disk with a hard size cap while hashing (step 1 + 5 of the chain)."""
    h = hashlib.sha256()
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise AppError(
                    413, "FILE_TOO_LARGE", f"Fayl hajmi {max_bytes // (1024 * 1024)} MB dan oshmasligi kerak"
                )
            h.update(chunk)
            out.write(chunk)
    if size == 0:
        raise AppError(422, "AUDIO_CORRUPT", "Fayl bo'sh")
    return size, h.hexdigest()


async def upload(
    db: AsyncSession,
    user: User,
    exam: Examination,
    file: UploadFile,
    *,
    site: AuscultationSite | None,
    kind: RecordingKind,
    notes: str | None,
    replace: bool,
) -> Recording:
    if exam.status not in UPLOADABLE:
        raise invalid_state(exam.status.value, sorted(s.value for s in UPLOADABLE))
    cfg = await settings_service.get_many(
        db,
        "upload.max_audio_mb",
        "upload.max_image_mb",
        "upload.max_files_per_exam",
        "audio.min_duration_sec",
        "audio.max_duration_sec",
        "analysis.auto_start",
    )
    limits = upload_validator.Limits(
        cfg["upload.max_audio_mb"],
        cfg["upload.max_image_mb"],
        cfg["audio.min_duration_sec"],
        cfg["audio.max_duration_sec"],
    )
    # 2) filename + extension whitelist
    safe_name, ext = upload_validator.sanitize_filename(file.filename)
    is_audio_ext = ext in upload_validator.AUDIO_EXTS
    if kind == RecordingKind.audio and not is_audio_ext:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Audio yuklash uchun wav/mp3/flac kerak")
    if kind == RecordingKind.other_image and is_audio_ext:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Tasvir yuklash uchun png/jpg kerak")
    if kind not in (RecordingKind.audio, RecordingKind.other_image):
        raise AppError(422, "VALIDATION_ERROR", "kind faqat audio yoki other_image bo'lishi mumkin")
    if kind == RecordingKind.audio and site is None:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Audio uchun auscultation site majburiy",
            [{"field": "site", "msg": "required for audio", "type": "missing"}],
        )
    # file count (derived artifacts do not count)
    count = (
        await db.execute(
            select(func.count()).where(
                Recording.examination_id == exam.id,
                Recording.deleted_at.is_(None),
                Recording.kind.in_([RecordingKind.audio, RecordingKind.other_image]),
            )
        )
    ).scalar_one()
    existing_same_site = None
    if kind == RecordingKind.audio:
        existing_same_site = (
            (
                await db.execute(
                    select(Recording).where(
                        Recording.examination_id == exam.id,
                        Recording.kind == RecordingKind.audio,
                        Recording.site == site,
                        Recording.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing_same_site and not replace:
            raise conflict(
                "SITE_ALREADY_RECORDED",
                "Bu nuqta uchun yozuv mavjud (?replace=true bilan almashtiring)",
                {"recording_id": str(existing_same_site.id)},
            )
    effective_count = count - (1 if existing_same_site and replace else 0)
    if effective_count >= cfg["upload.max_files_per_exam"]:
        raise unprocessable(
            "TOO_MANY_FILES",
            f"Tekshiruvga ko'pi bilan {cfg['upload.max_files_per_exam']} ta fayl yuklash mumkin",
        )

    max_bytes = (limits.max_audio_mb if is_audio_ext else limits.max_image_mb) * 1024 * 1024
    storage = get_storage()
    rid = new_id()
    key = f"exams/{exam.id}/{rid}/original.{ext}"
    stored = False
    with tempfile.TemporaryDirectory(prefix="cpcg-up-") as tmp:
        tmpdir = Path(tmp)
        raw = tmpdir / "upload.bin"
        size, sha = await _spool(file, max_bytes, raw)
        # 3-4) content-based type detection
        mime = upload_validator.check_content_type(raw, ext)
        # 5) duplicate (same sha in the same exam)
        dup = (
            await db.execute(
                select(Recording.id).where(
                    Recording.examination_id == exam.id,
                    Recording.sha256 == sha,
                    Recording.deleted_at.is_(None),
                    Recording.kind.in_([RecordingKind.audio, RecordingKind.other_image]),
                )
            )
        ).first()
        if dup:
            raise conflict(
                "DUPLICATE_RECORDING",
                "Bu fayl ushbu tekshiruvga allaqachon yuklangan",
                {"recording_id": str(dup[0])},
            )
        meta: dict[str, Any] = {}
        warnings: list[str] = []
        final_path = raw
        if kind == RecordingKind.audio:
            # 6-7) decode + signal quality
            meta, warnings = upload_validator.analyze_audio(raw, limits)
        else:
            # 8) image re-encode (strips EXIF), image-bomb guard
            clean = tmpdir / "clean.bin"
            img = upload_validator.process_image(raw, ext, clean)
            final_path = clean
            size = clean.stat().st_size
            sha = upload_validator.sha256_file(clean)
            meta = img
        # 9) antivirus
        scan = await antivirus.scan_file(final_path)
        if scan == "infected":
            raise unprocessable("INFECTED_FILE", "Fayl zararli kod bilan zararlangan")
        if scan in ("skipped", "error"):
            warnings.append(f"AV_{scan.upper()}")

        # 10-11) store; compensating cleanup on failure
        if existing_same_site and replace:
            await _soft_delete(db, existing_same_site)
        rec = Recording(
            id=rid,
            examination_id=exam.id,
            kind=kind,
            status=RecordingStatus.uploading,
            site=site if kind == RecordingKind.audio else None,
            storage_key=key,
            original_filename=safe_name,
            mime_type=mime,
            ext="jpg" if ext == "jpeg" else ext,
            size_bytes=size,
            sha256=sha,
            duration_sec=meta.get("duration_sec"),
            sample_rate_hz=meta.get("sample_rate_hz"),
            channels=meta.get("channels"),
            bit_depth=meta.get("bit_depth"),
            codec=meta.get("codec"),
            width_px=meta.get("width_px"),
            height_px=meta.get("height_px"),
            snr_db=meta.get("snr_db"),
            quality_score=meta.get("quality_score"),
            validation_report={
                "warnings": warnings,
                **{k: v for k, v in meta.items() if k in ("rms_dbfs", "clip_ratio", "dc_offset")},
            },
            scan_status=scan if scan != "error" else "error",
            notes=notes,
            uploaded_by=user.id,
        )
        db.add(rec)
        await db.flush()
        try:
            await storage.put_file(key, final_path, mime)
            stored = True
            rec.status = RecordingStatus.validated
            await db.flush()
        except Exception:
            if stored:
                with contextlib.suppress(Exception):
                    await storage.delete(key)
            raise

    try:
        audit_service.log_event(
            db,
            AuditAction.upload,
            user=user,
            resource_type="recording",
            resource_id=rec.id,
            patient_id=exam.patient_id,
            meta={
                "examination_id": str(exam.id),
                "size_bytes": size,
                "kind": kind.value,
                "site": site.value if site else None,
            },
        )
        realtime.queue_event(
            db,
            "recording.uploaded",
            {
                "examination_id": str(exam.id),
                "recording_id": str(rec.id),
                "site": rec.site.value if rec.site else None,
                "status": rec.status.value,
            },
            [f"exam:{exam.id}"],
        )
        if kind == RecordingKind.audio and exam.status == ExamStatus.draft:
            await transition(db, exam, ExamStatus.uploaded, None, "first audio validated", system=True)
            if exam.assigned_doctor_id:
                await notification_service.notify(
                    db,
                    exam.assigned_doctor_id,
                    NotificationType.exam_uploaded,
                    f"Yangi yozuv: {exam.exam_no}",
                    None,
                    {"examination_id": str(exam.id), "patient_id": str(exam.patient_id)},
                )
            if cfg["analysis.auto_start"]:
                await analysis_service.enqueue(db, exam, user)
    except Exception:
        with contextlib.suppress(Exception):
            await storage.delete(key)
        raise
    return rec


async def reject_audit(user: User, exam: Examination, exc: AppError) -> None:
    """Failed uploads leave an audit trail + realtime event (the request transaction is rolled back)."""
    await audit_service.log_standalone(
        AuditAction.upload,
        user=user,
        resource_type="examination",
        resource_id=exam.id,
        patient_id=exam.patient_id,
        success=False,
        status_code=exc.status_code,
        meta={"error_code": exc.code},
    )
    await realtime.bus.publish(
        "recording.rejected",
        {"examination_id": str(exam.id), "code": exc.code, "message": exc.message},
        [f"user:{user.id}"],
    )


async def _soft_delete(db: AsyncSession, rec: Recording) -> None:
    now = utcnow()
    rec.deleted_at = now
    derived = (
        (
            await db.execute(
                select(Recording).where(Recording.derived_from_id == rec.id, Recording.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    for d in derived:
        d.deleted_at = now


async def delete_recording(db: AsyncSession, user: User, exam: Examination, rec: Recording) -> None:
    await _soft_delete(db, rec)
    await db.flush()
    audit_service.log_event(
        db,
        AuditAction.delete,
        user=user,
        resource_type="recording",
        resource_id=rec.id,
        patient_id=exam.patient_id,
        meta={"examination_id": str(exam.id)},
    )
    if rec.kind == RecordingKind.audio and exam.status == ExamStatus.uploaded:
        remaining = (
            await db.execute(
                select(func.count()).where(
                    Recording.examination_id == exam.id,
                    Recording.kind == RecordingKind.audio,
                    Recording.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        if remaining == 0:
            await transition(db, exam, ExamStatus.draft, None, "last audio deleted", system=True)


# ----------------------------------------------------------------------------------- reading
def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Single 'bytes=a-b' range. Returns None for no header; raises 416 for unsatisfiable."""
    if not header:
        return None
    if not header.startswith("bytes=") or "," in header:
        raise AppError(416, "RANGE_NOT_SATISFIABLE", "Range noto'g'ri")
    a, _, b = header[6:].partition("-")
    try:
        if a == "":
            n = int(b)
            if n <= 0:
                raise ValueError
            start, end = max(size - n, 0), size - 1
        else:
            start = int(a)
            end = int(b) if b else size - 1
            end = min(end, size - 1)
    except ValueError:
        raise AppError(416, "RANGE_NOT_SATISFIABLE", "Range noto'g'ri")
    if start >= size or start > end:
        raise AppError(
            416,
            "RANGE_NOT_SATISFIABLE",
            "Range fayl hajmidan tashqarida",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, end


async def stream_range(key: str, start: int, end: int) -> AsyncIterator[bytes]:
    async for chunk in get_storage().iter_range(key, start, end):
        yield chunk


async def waveform_for(rec: Recording, exam_id: uuid.UUID, points: int = 1500) -> dict[str, Any]:
    """Peaks JSON for wavesurfer: precomputed (analysis) or computed on demand from the stored audio."""
    storage = get_storage()
    cached_key = f"exams/{exam_id}/{rec.id}/waveform.json"
    if await storage.exists(cached_key):
        return orjson.loads(await storage.get_bytes(cached_key))
    if rec.kind != RecordingKind.audio:
        raise AppError(404, "NOT_FOUND", "Bu yozuv uchun to'lqin shakli yo'q")
    with tempfile.TemporaryDirectory(prefix="cpcg-wf-") as tmp:
        local = Path(tmp) / f"a.{rec.ext}"
        await storage.download_to(rec.storage_key, local)
        data, sr = sf.read(str(local), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    n = mono.shape[0]
    spp = max(n // points, 1)
    usable = (n // spp) * spp
    blocks = mono[:usable].reshape(-1, spp)
    mx, mn = blocks.max(axis=1), blocks.min(axis=1)
    peak = float(max(np.abs(mx).max(), np.abs(mn).max(), 1e-9))
    inter = np.empty(mx.shape[0] * 2, dtype=np.float32)
    inter[0::2], inter[1::2] = mn / peak, mx / peak
    result = {
        "version": 1,
        "format": "minmax-interleaved",
        "channels": 1,
        "sample_rate": int(sr),
        "samples_per_pixel": int(spp),
        "length": int(mx.shape[0]),
        "duration_sec": round(n / sr, 3),
        "data": [round(float(x), 4) for x in inter],
    }
    with contextlib.suppress(Exception):
        await storage.put_bytes(cached_key, orjson.dumps(result), "application/json")
    return result

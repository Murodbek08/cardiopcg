"""Analysis job orchestration: enqueue, run (worker side), persist results, notifications, maintenance.

The heavy lifting (signal processing + LLM) is delegated to an ``AnalysisService`` implementation
(``app.services.analysis_port``); this module owns persistence, state transitions and events.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import orjson
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, invalid_state, unprocessable
from app.core.kv import get_kv
from app.db.base import new_id, utcnow
from app.db.session import get_sessionmaker
from app.models.analysis import AnalysisJob, AnalysisResult, PcgSegment
from app.models.clinical import AiReport
from app.models.enums import (
    AuditAction,
    ExamStatus,
    JobStatus,
    MurmurTiming,
    NotificationType,
    PcgClass,
    RecordingKind,
    RecordingStatus,
    ReportStatus,
    SegmentType,
    Severity,
    UserRole,
)
from app.models.examination import Examination
from app.models.patient import Allergy, CurrentMedication, MedicalHistory, Patient
from app.models.recording import Recording
from app.models.user import User
from app.services import audit_service, notification_service, prescription_service, realtime, settings_service
from app.services.analysis_port import (
    AnalysisError,
    AnalysisOptions,
    AnalysisOutcome,
    AnalysisRequest,
    PatientContext,
    RecordingInput,
    ReportOutcome,
    ReportRequest,
    TransientAnalysisError,
    get_analysis_service,
)
from app.services.exam_service import DISCLAIMER_AI, TASHKENT, load_exam
from app.services.exam_state import lock_exam, transition
from app.services.patient_service import calc_age, calc_bmi
from app.services.storage import get_storage

log = structlog.get_logger()
_SEVERITY_ORDER = ["none", "mild", "moderate", "severe", "critical"]
_background: set[asyncio.Task] = set()


class JobCancelledError(Exception):
    pass


# ------------------------------------------------------------------------------------ dispatch
async def dispatch_job(job_id: uuid.UUID) -> None:
    runner = get_settings().job_runner
    if runner == "celery":
        from app.workers.celery_app import celery_app

        celery_app.send_task("analysis.analyze_examination", args=[str(job_id)], queue="analysis")
    elif runner == "inline":
        task = asyncio.create_task(run_job(job_id), name=f"analysis-{job_id}")
        _background.add(task)
        task.add_done_callback(_background.discard)
    # 'none': tests / external scheduler call run_job explicitly


async def enqueue(
    db: AsyncSession,
    exam: Examination,
    actor: User,
    options: AnalysisOptions | None = None,
    *,
    rerun: bool = False,
) -> AnalysisJob:
    """Create a pending job and move the exam to `queued`. Dispatch happens after commit."""
    exam = await lock_exam(db, exam.id)
    allowed_from = (
        {ExamStatus.uploaded} if not rerun else {ExamStatus.failed, ExamStatus.ai_ready, ExamStatus.in_review}
    )
    if exam.status not in allowed_from:
        raise invalid_state(exam.status.value, sorted(s.value for s in allowed_from))
    recs = (
        (
            await db.execute(
                select(Recording).where(
                    Recording.examination_id == exam.id,
                    Recording.kind == RecordingKind.audio,
                    Recording.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not recs:
        raise unprocessable("NO_AUDIO_RECORDINGS", "Tahlil uchun audio yozuv yo'q")
    if any(r.status != RecordingStatus.validated and r.status != RecordingStatus.processed for r in recs):
        raise unprocessable("RECORDINGS_NOT_VALIDATED", "Barcha audio yozuvlar tekshiruvdan o'tmagan")

    cfg = await settings_service.get_many(
        db, "analysis.model_version", "ai.llm_model", "ai.llm_enabled", "ai.drug_suggestions_enabled"
    )
    opts = options or AnalysisOptions()
    opts = opts.model_copy(
        update={
            "llm": opts.llm and bool(cfg["ai.llm_enabled"]),
            "drug_suggestions": opts.drug_suggestions and bool(cfg["ai.drug_suggestions_enabled"]),
            "llm_model": cfg["ai.llm_model"],
            "model_version": cfg["analysis.model_version"],
        }
    )
    job = AnalysisJob(
        id=new_id(),
        examination_id=exam.id,
        status=JobStatus.pending,
        stage="queued",
        progress_pct=0,
        requested_by=actor.id,
        model_version=opts.model_version,
        options=opts.model_dump(),
        max_attempts=max(len(get_settings().backoff_schedule), 1),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(job)
    await db.flush()
    exam.current_job_id = job.id
    exam.ai_requested_at = utcnow()
    await transition(db, exam, ExamStatus.queued, actor, "analysis requested")
    audit_service.log_event(
        db,
        AuditAction.create,
        user=actor,
        resource_type="analysis_job",
        resource_id=job.id,
        patient_id=exam.patient_id,
        meta={"examination_id": str(exam.id), "rerun": rerun},
    )
    realtime.queue_event(
        db,
        "analysis.progress",
        {"examination_id": str(exam.id), "job_id": str(job.id), "stage": "queued", "progress_pct": 0},
        [f"exam:{exam.id}"],
    )
    realtime.after_commit(db, lambda: dispatch_job(job.id))
    return job


async def cancel_job_if_active(db: AsyncSession, exam: Examination) -> None:
    if not exam.current_job_id:
        return
    job = await db.get(AnalysisJob, exam.current_job_id)
    if job and job.status in (JobStatus.pending, JobStatus.running):
        job.status = JobStatus.cancelled
        job.finished_at = utcnow()
        await get_kv().set(f"job:cancel:{job.id}", "1", 3600)


# -------------------------------------------------------------------------------- context builders
async def build_patient_context(db: AsyncSession, exam: Examination) -> PatientContext:
    """De-identified clinical context. NEVER includes name, phone, address, national id or MRN."""
    p = await db.get(Patient, exam.patient_id)
    allergies = (
        (await db.execute(select(Allergy).where(Allergy.patient_id == p.id, Allergy.is_active)))
        .scalars()
        .all()
    )
    meds = (
        (
            await db.execute(
                select(CurrentMedication).where(
                    CurrentMedication.patient_id == p.id, CurrentMedication.is_active
                )
            )
        )
        .scalars()
        .all()
    )
    hist = (
        (
            await db.execute(
                select(MedicalHistory).where(MedicalHistory.patient_id == p.id, MedicalHistory.is_active)
            )
        )
        .scalars()
        .all()
    )
    return PatientContext(
        age_years=calc_age(p.birth_date),
        gender=p.gender.value,
        height_cm=float(p.height_cm) if p.height_cm else None,
        weight_kg=float(exam.weight_kg_at_exam or p.weight_kg)
        if (exam.weight_kg_at_exam or p.weight_kg)
        else None,
        bmi=calc_bmi(p.height_cm, exam.weight_kg_at_exam or p.weight_kg),
        history=[{"kind": h.kind.value, "title": h.title, "icd10_code": h.icd10_code} for h in hist],
        allergies=[
            {
                "substance": a.substance,
                "substance_code": a.substance_code,
                "severity": a.severity.value,
                "reaction": a.reaction,
            }
            for a in allergies
        ],
        medications=[
            {"drug_name": m.drug_name, "inn_code": m.inn_code, "dose": m.dose, "frequency": m.frequency}
            for m in meds
        ],
        vitals={
            k: v
            for k, v in {
                "heart_rate_bpm": exam.heart_rate_bpm,
                "bp_systolic": exam.bp_systolic,
                "bp_diastolic": exam.bp_diastolic,
                "spo2_pct": exam.spo2_pct,
                "temperature_c": float(exam.temperature_c) if exam.temperature_c is not None else None,
            }.items()
            if v is not None
        },
        complaints=exam.complaints,
        symptoms=list(exam.symptoms or []),
        patient_position=exam.patient_position.value if exam.patient_position else None,
        priority=exam.priority.value,
        ai_consent=bool(p.ai_consent),
    )


def _signal_dict(res: AnalysisResult) -> dict[str, Any]:
    f = lambda v: float(v) if v is not None else None  # noqa: E731
    return {
        "model_version": res.model_version,
        "pcg_class": res.pcg_class.value,
        "class_probs": res.class_probs,
        "confidence": float(res.confidence),
        "severity": res.severity.value,
        "murmur_timing": res.murmur_timing.value,
        "murmur_grade": res.murmur_grade,
        "murmur_shape": res.murmur_shape,
        "heart_rate_bpm": f(res.heart_rate_bpm),
        "hr_variability_ms": f(res.hr_variability_ms),
        "s1_count": res.s1_count,
        "s2_count": res.s2_count,
        "mean_s1_s2_ms": f(res.mean_s1_s2_ms),
        "mean_s2_s1_ms": f(res.mean_s2_s1_ms),
        "systole_ms": f(res.systole_ms),
        "diastole_ms": f(res.diastole_ms),
        "dominant_freq_hz": f(res.dominant_freq_hz),
        "features": res.features,
        "quality_ok": res.quality_ok,
        "quality_notes": res.quality_notes,
    }


# ------------------------------------------------------------------------------------- persistence
async def persist_report(
    db: AsyncSession,
    exam: Examination,
    result: AnalysisResult,
    outcome: ReportOutcome,
    actor: User | None,
    opts: AnalysisOptions,
) -> AiReport | None:
    """Store the LLM report (or a failed placeholder) + drug suggestions; audit the AI call."""
    await db.execute(
        update(AiReport)
        .where(AiReport.examination_id == exam.id, AiReport.is_current)
        .values(is_current=False, status=ReportStatus.superseded)
    )
    await db.flush()
    rep: AiReport | None = None
    if outcome.report is not None:
        r = outcome.report
        rep = AiReport(
            examination_id=exam.id,
            analysis_result_id=result.id,
            status=ReportStatus.ready,
            is_current=True,
            llm_provider=r.llm_provider,
            llm_model=r.llm_model[:40],
            prompt_version=r.prompt_version[:20],
            summary=r.summary,
            findings=r.findings,
            differential_diagnoses=r.differential_diagnoses,
            recommended_tests=r.recommended_tests,
            red_flags=r.red_flags,
            patient_friendly_text=r.patient_friendly_text,
            disclaimer=r.disclaimer or DISCLAIMER_AI,
            input_snapshot=r.input_snapshot,
            raw_response=r.raw_response,
            prompt_tokens=r.prompt_tokens,
            completion_tokens=r.completion_tokens,
            latency_ms=r.latency_ms,
            cost_usd=r.cost_usd,
            created_at=utcnow(),
        )
    else:
        rep = AiReport(
            examination_id=exam.id,
            analysis_result_id=result.id,
            status=ReportStatus.failed,
            is_current=True,
            llm_model=opts.llm_model[:40],
            prompt_version="n/a",
            summary="",
            findings={},
            differential_diagnoses=[],
            disclaimer=DISCLAIMER_AI,
            input_snapshot={},
            error_message=(outcome.error or "AI izohi yaratilmadi")[:2000],
            created_at=utcnow(),
        )
    db.add(rep)
    await db.flush()
    audit_service.log_event(
        db,
        AuditAction.ai_call,
        user=actor,
        resource_type="ai_report",
        resource_id=rep.id,
        patient_id=exam.patient_id,
        success=rep.status == ReportStatus.ready,
        meta={
            "examination_id": str(exam.id),
            "model": rep.llm_model,
            "prompt_tokens": rep.prompt_tokens,
            "completion_tokens": rep.completion_tokens,
            "latency_ms": rep.latency_ms,
            "error": rep.error_message,
        },
    )
    if outcome.drug_suggestions:
        await prescription_service.add_ai_suggestions(db, exam, outcome.drug_suggestions, rep.id)
    realtime.queue_event(
        db,
        "analysis.report_ready",
        {"examination_id": str(exam.id), "ai_report_id": str(rep.id), "status": rep.status.value},
        [f"exam:{exam.id}"],
    )
    return rep


async def persist_signal(
    db: AsyncSession,
    exam: Examination,
    job: AnalysisJob,
    outcome: AnalysisOutcome,
    valid_recs: dict[str, Recording],
    elapsed_ms: int,
) -> AnalysisResult:
    sig = outcome.signal
    await db.execute(
        update(AnalysisResult)
        .where(AnalysisResult.examination_id == exam.id, AnalysisResult.is_current)
        .values(is_current=False)
    )
    await db.flush()
    try:
        pcg = PcgClass(sig.pcg_class)
    except ValueError:
        pcg = PcgClass.undetermined
    sev = Severity(sig.severity) if sig.severity in _SEVERITY_ORDER else Severity.none
    timing = (
        MurmurTiming(sig.murmur_timing)
        if sig.murmur_timing in {m.value for m in MurmurTiming}
        else MurmurTiming.none
    )
    per_rec: dict[str, Any] = {}
    for ra in sig.recordings:
        per_rec[ra.recording_id] = {"pcg_class": ra.pcg_class, "confidence": ra.confidence, **ra.extra}
    features = dict(sig.features)
    features["per_recording"] = per_rec
    features.setdefault("aggregation", "worst_site")
    res = AnalysisResult(
        examination_id=exam.id,
        job_id=job.id,
        is_current=True,
        model_version=sig.model_version[:40],
        pcg_class=pcg,
        class_probs=sig.class_probs,
        confidence=min(max(sig.confidence, 0.0), 1.0),
        severity=sev,
        murmur_timing=timing,
        murmur_grade=sig.murmur_grade,
        murmur_shape=sig.murmur_shape,
        heart_rate_bpm=sig.heart_rate_bpm,
        hr_variability_ms=sig.hr_variability_ms,
        s1_count=sig.s1_count,
        s2_count=sig.s2_count,
        mean_s1_s2_ms=sig.mean_s1_s2_ms,
        mean_s2_s1_ms=sig.mean_s2_s1_ms,
        systole_ms=sig.systole_ms,
        diastole_ms=sig.diastole_ms,
        dominant_freq_hz=sig.dominant_freq_hz,
        features=features,
        quality_ok=sig.quality_ok,
        quality_notes=sig.quality_notes,
        processing_ms=sig.processing_ms if sig.processing_ms is not None else elapsed_ms,
        created_at=utcnow(),
    )
    db.add(res)
    await db.flush()

    storage = get_storage()
    first_spect: uuid.UUID | None = None
    for ra in sig.recordings:
        rec = valid_recs.get(ra.recording_id)
        if rec is None:
            continue
        if ra.snr_db is not None:
            rec.snr_db = ra.snr_db
        if ra.quality_score is not None:
            rec.quality_score = ra.quality_score
        rec.status = RecordingStatus.processed
        if ra.waveform_peaks is not None:
            key = f"exams/{exam.id}/{rec.id}/waveform.json"
            await storage.put_bytes(key, orjson.dumps(ra.waveform_peaks), "application/json")
            res.waveform_key = res.waveform_key or key
        if ra.spectrogram_png:
            rid = new_id()
            key = f"exams/{exam.id}/{rid}/spectrogram.png"
            await storage.put_bytes(key, ra.spectrogram_png, "image/png")
            db.add(
                Recording(
                    id=rid,
                    examination_id=exam.id,
                    kind=RecordingKind.spectrogram,
                    status=RecordingStatus.processed,
                    storage_key=key,
                    derived_from_id=rec.id,
                    original_filename="spectrogram.png",
                    mime_type="image/png",
                    ext="png",
                    size_bytes=len(ra.spectrogram_png),
                    sha256=hashlib.sha256(ra.spectrogram_png).hexdigest(),
                    scan_status="skipped",
                    uploaded_by=job.requested_by,
                )
            )
            first_spect = first_spect or rid
    if first_spect:
        await db.flush()
        res.spectrogram_recording_id = first_spect
    seq = 0
    for sg in sig.segments:
        if sg.recording_id not in valid_recs or sg.end_ms <= sg.start_ms:
            continue
        try:
            stype = SegmentType(sg.type)
        except ValueError:
            continue
        seq += 1
        db.add(
            PcgSegment(
                analysis_result_id=res.id,
                recording_id=uuid.UUID(sg.recording_id),
                seq=seq,
                type=stype,
                start_ms=sg.start_ms,
                end_ms=sg.end_ms,
                cycle_no=sg.cycle_no,
                peak_amplitude=sg.peak_amplitude,
                energy=sg.energy,
                dominant_freq_hz=sg.dominant_freq_hz,
                confidence=sg.confidence,
                meta=sg.meta,
            )
        )
    await db.flush()
    realtime.queue_event(
        db,
        "analysis.signal_done",
        {
            "examination_id": str(exam.id),
            "analysis_result_id": str(res.id),
            "pcg_class": pcg.value,
            "confidence": float(res.confidence),
            "severity": sev.value,
        },
        [f"exam:{exam.id}"],
    )
    return res


def is_critical(res: AnalysisResult, report: AiReport | None, threshold: float) -> bool:
    if _SEVERITY_ORDER.index(res.severity.value) >= _SEVERITY_ORDER.index("severe"):
        return True
    return bool(
        res.pcg_class == PcgClass.murmur
        and float(res.confidence) >= threshold
        and report is not None
        and report.status == ReportStatus.ready
        and report.red_flags
    )


# ----------------------------------------------------------------------------------------- runner
async def _set_progress(job_id: uuid.UUID, exam_id: uuid.UUID, stage: str, pct: int) -> None:
    if await get_kv().get(f"job:cancel:{job_id}"):
        raise JobCancelledError()
    async with get_sessionmaker()() as s:
        job = await s.get(AnalysisJob, job_id)
        if job is None or job.status == JobStatus.cancelled:
            raise JobCancelledError()
        job.stage, job.progress_pct, job.updated_at = stage, max(0, min(pct, 100)), utcnow()
        await s.commit()
    await realtime.bus.publish(
        "analysis.progress",
        {"examination_id": str(exam_id), "job_id": str(job_id), "stage": stage, "progress_pct": pct},
        [f"exam:{exam_id}"],
    )


async def run_job(job_id: uuid.UUID | str) -> str:
    """Execute an analysis job end-to-end. Idempotent: returns immediately unless the job is `pending`."""
    job_id = uuid.UUID(str(job_id))
    sm = get_sessionmaker()
    started = time.perf_counter()

    # 1) claim (FOR UPDATE SKIP LOCKED) + queued -> processing
    async with sm() as s:
        job = (
            await s.execute(
                select(AnalysisJob)
                .where(AnalysisJob.id == job_id, AnalysisJob.status == JobStatus.pending)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None:
            return "skipped"
        exam = await lock_exam(s, job.examination_id)
        if exam.status != ExamStatus.queued:
            job.status = JobStatus.cancelled
            job.finished_at = utcnow()
            await s.commit()
            return "skipped"
        job.status, job.started_at, job.stage, job.progress_pct, job.updated_at = (
            JobStatus.running,
            utcnow(),
            "validating",
            5,
            utcnow(),
        )
        await transition(s, exam, ExamStatus.processing, None, None, worker=True)
        exam_id, options = exam.id, AnalysisOptions(**job.options)
        max_attempts = job.max_attempts
        await s.commit()
        await realtime.flush_events(s)

    workdir = Path(tempfile.mkdtemp(prefix="cpcg-an-"))
    try:
        # 2) build request (local audio + de-identified context)
        async with sm() as s:
            exam = await s.get(Examination, exam_id)
            recs = (
                (
                    await s.execute(
                        select(Recording)
                        .where(
                            Recording.examination_id == exam_id,
                            Recording.kind == RecordingKind.audio,
                            Recording.deleted_at.is_(None),
                        )
                        .order_by(Recording.created_at)
                    )
                )
                .scalars()
                .all()
            )
            storage = get_storage()
            inputs: list[RecordingInput] = []
            for r in recs:
                local = workdir / f"{r.id}.{r.ext}"
                await storage.download_to(r.storage_key, local)
                inputs.append(
                    RecordingInput(
                        recording_id=str(r.id),
                        site=r.site.value,
                        local_path=str(local),
                        ext=r.ext,
                        duration_sec=float(r.duration_sec) if r.duration_sec is not None else None,
                        sample_rate_hz=r.sample_rate_hz,
                        snr_db=float(r.snr_db) if r.snr_db is not None else None,
                    )
                )
            request = AnalysisRequest(
                examination_id=str(exam_id),
                job_id=str(job_id),
                exam_no=exam.exam_no,
                recordings=inputs,
                user_ref=str(job.requested_by),
                patient=await build_patient_context(s, exam),
                options=options,
            )

        # 3) run with retry on transient errors
        svc = get_analysis_service()

        async def progress(stage: str, pct: int) -> None:
            await _set_progress(job_id, exam_id, stage, pct)

        outcome: AnalysisOutcome | None = None
        err: AnalysisError | None = None
        schedule = get_settings().backoff_schedule or [0]
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    async with sm() as s:
                        j = await s.get(AnalysisJob, job_id)
                        j.attempt = attempt
                        await s.commit()
                outcome = await svc.analyze(request, progress)
                err = None
                break
            except JobCancelledError:
                return "cancelled"
            except TransientAnalysisError as exc:
                err = exc
                log.warning("analysis_transient_error", attempt=attempt, code=exc.code)
                if attempt < max_attempts:
                    await asyncio.sleep(schedule[min(attempt - 1, len(schedule) - 1)])
            except AnalysisError as exc:
                err = exc
                break
            except Exception as exc:
                err = AnalysisError("ANALYSIS_INTERNAL_ERROR", f"{type(exc).__name__}")
                log.error("analysis_unexpected_error", exc_info=exc)
                break

        if outcome is None:
            await _fail_job(job_id, exam_id, err or AnalysisError("ANALYSIS_FAILED"))
            return "failed"

        # 4) persist + finalize
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        async with sm() as s:
            job = await s.get(AnalysisJob, job_id)
            if job.status == JobStatus.cancelled:
                return "cancelled"
            exam = await lock_exam(s, exam_id)
            if exam.status != ExamStatus.processing:
                return "cancelled"
            valid = {
                str(r.id): r
                for r in (
                    await s.execute(
                        select(Recording).where(
                            Recording.examination_id == exam_id, Recording.kind == RecordingKind.audio
                        )
                    )
                ).scalars()
            }
            res = await persist_signal(s, exam, job, outcome, valid, elapsed_ms)
            report: AiReport | None = None
            if outcome.report is not None:
                requester = await s.get(User, job.requested_by)
                report = await persist_report(s, exam, res, outcome.report, requester, options)
            exam.ai_completed_at = utcnow()
            job.status, job.stage, job.progress_pct, job.finished_at, job.updated_at = (
                JobStatus.succeeded,
                "finalizing",
                100,
                utcnow(),
                utcnow(),
            )
            await transition(s, exam, ExamStatus.ai_ready, None, None, worker=True)
            await _notify_done(s, exam, res, report)
            await s.commit()
            await realtime.flush_events(s)
        await realtime.bus.publish(
            "analysis.progress",
            {
                "examination_id": str(exam_id),
                "job_id": str(job_id),
                "stage": "finalizing",
                "progress_pct": 100,
            },
            [f"exam:{exam_id}"],
        )
        return "succeeded"
    except JobCancelledError:
        return "cancelled"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _notify_done(
    s: AsyncSession, exam: Examination, res: AnalysisResult, report: AiReport | None
) -> None:
    patient = await s.get(Patient, exam.patient_id)
    short = f"{patient.last_name} {patient.first_name[:1]}." if patient else ""
    title = f"Tahlil tayyor: {exam.exam_no}"
    body = f"{short} - {res.pcg_class.value} ({res.severity.value})"
    payload = {
        "examination_id": str(exam.id),
        "patient_id": str(exam.patient_id),
        "severity": res.severity.value,
    }
    if exam.assigned_doctor_id:
        await notification_service.notify(
            s, exam.assigned_doctor_id, NotificationType.analysis_done, title, body, payload
        )
    else:
        await notification_service.notify_role(
            s, UserRole.doctor, NotificationType.analysis_done, title, body, payload
        )
    realtime.queue_event(
        s,
        "analysis.completed",
        {"examination_id": str(exam.id), "status": "ai_ready"},
        [f"exam:{exam.id}", f"user:{exam.performed_by}"]
        + ([f"user:{exam.assigned_doctor_id}"] if exam.assigned_doctor_id else []),
    )
    thr = await settings_service.get_value(s, "ai.critical_probability_threshold")
    if is_critical(res, report, float(thr)):
        flags = list(report.red_flags) if report else []
        ctitle = f"Kritik topilma: {exam.exam_no}"
        cpayload = {**payload, "red_flags": flags}
        if exam.assigned_doctor_id:
            await notification_service.notify(
                s, exam.assigned_doctor_id, NotificationType.critical_finding, ctitle, body, cpayload
            )
        else:
            await notification_service.notify_role(
                s, UserRole.doctor, NotificationType.critical_finding, ctitle, body, cpayload
            )
        await notification_service.notify_role(
            s, UserRole.admin, NotificationType.critical_finding, ctitle, body, cpayload
        )
        chans = ["role:doctor", "role:admin"] + (
            [f"user:{exam.assigned_doctor_id}"] if exam.assigned_doctor_id else []
        )
        realtime.queue_event(
            s,
            "finding.critical",
            {"examination_id": str(exam.id), "severity": res.severity.value, "red_flags": flags},
            chans,
        )


async def _fail_job(job_id: uuid.UUID, exam_id: uuid.UUID, err: AnalysisError) -> None:
    async with get_sessionmaker()() as s:
        job = await s.get(AnalysisJob, job_id)
        if job is None or job.status == JobStatus.cancelled:
            return
        exam = await lock_exam(s, exam_id)
        job.status, job.error_code, job.error_message = JobStatus.failed, err.code[:40], err.message[:2000]
        job.finished_at, job.updated_at = utcnow(), utcnow()
        if exam.status == ExamStatus.processing:
            await transition(
                s, exam, ExamStatus.failed, None, f"{err.code}: {err.message}"[:500], worker=True
            )
        await notification_service.notify(
            s,
            exam.performed_by,
            NotificationType.analysis_failed,
            f"Tahlil xatosi: {exam.exam_no}",
            err.message[:300],
            {"examination_id": str(exam.id), "error_code": err.code},
        )
        await notification_service.notify_role(
            s,
            UserRole.admin,
            NotificationType.analysis_failed,
            f"Tahlil xatosi: {exam.exam_no}",
            err.code,
            {"examination_id": str(exam.id)},
        )
        realtime.queue_event(
            s,
            "analysis.failed",
            {
                "examination_id": str(exam.id),
                "job_id": str(job_id),
                "error_code": err.code,
                "message": err.message,
                "can_retry": True,
            },
            [f"exam:{exam.id}", f"user:{exam.performed_by}", "role:admin"],
        )
        await s.commit()
        await realtime.flush_events(s)


# -------------------------------------------------------------------------- LLM-only regeneration
async def regenerate_report(
    db: AsyncSession, exam: Examination, actor: User, *, want_report: bool = True, want_drugs: bool = True
) -> AiReport:
    res = (
        await db.execute(
            select(AnalysisResult).where(AnalysisResult.examination_id == exam.id, AnalysisResult.is_current)
        )
    ).scalar_one_or_none()
    if res is None:
        raise unprocessable("NO_ANALYSIS", "Signal tahlili natijasi yo'q")
    cfg = await settings_service.get_many(
        db, "ai.llm_model", "ai.llm_enabled", "ai.drug_suggestions_enabled", "analysis.model_version"
    )
    if not cfg["ai.llm_enabled"]:
        raise AppError(409, "LLM_DISABLED", "LLM izohi sozlamalarda o'chirilgan")
    opts = AnalysisOptions(
        llm=True,
        drug_suggestions=bool(cfg["ai.drug_suggestions_enabled"]) and want_drugs,
        llm_model=cfg["ai.llm_model"],
        model_version=cfg["analysis.model_version"],
    )
    req = ReportRequest(
        examination_id=str(exam.id),
        exam_no=exam.exam_no,
        patient=await build_patient_context(db, exam),
        signal=_signal_dict(res),
        user_ref=str(actor.id),
        options=opts,
        want_report=want_report,
        want_drugs=opts.drug_suggestions,
    )
    outcome = await get_analysis_service().generate_report(req)
    rep = await persist_report(db, exam, res, outcome, actor, opts)
    return rep


# ------------------------------------------------------------------------------------ maintenance
async def reap_stuck_jobs(stuck_minutes: int = 15) -> int:
    """Running jobs without progress for > N minutes: fail them and re-queue when attempts remain."""
    sm = get_sessionmaker()
    cutoff = utcnow() - timedelta(minutes=stuck_minutes)
    n = 0
    async with sm() as s:
        requeue: list[uuid.UUID] = []
        jobs = (
            (
                await s.execute(
                    select(AnalysisJob)
                    .where(AnalysisJob.status == JobStatus.running, AnalysisJob.updated_at < cutoff)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for job in jobs:
            exam = await lock_exam(s, job.examination_id)
            job.finished_at = utcnow()
            if job.attempt < job.max_attempts and exam.status == ExamStatus.processing:
                job.status = JobStatus.failed
                job.error_code = "STUCK_REAPED"
                await transition(s, exam, ExamStatus.failed, None, "worker timeout", worker=True)
                new = AnalysisJob(
                    id=new_id(),
                    examination_id=exam.id,
                    status=JobStatus.pending,
                    stage="queued",
                    progress_pct=0,
                    attempt=job.attempt + 1,
                    max_attempts=job.max_attempts,
                    requested_by=job.requested_by,
                    model_version=job.model_version,
                    options=job.options,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                s.add(new)
                await s.flush()
                exam.current_job_id = new.id
                await transition(s, exam, ExamStatus.queued, None, "re-queued by reaper", worker=True)
                requeue.append(new.id)
            else:
                job.status = JobStatus.failed
                job.error_code = "STUCK_REAPED"
                job.error_message = "Worker javob bermadi"
                if exam.status == ExamStatus.processing:
                    await transition(s, exam, ExamStatus.failed, None, "worker timeout", worker=True)
            n += 1
        await s.commit()
        await realtime.flush_events(s)
    for jid in requeue:
        await dispatch_job(jid)
    return n


_ = (TASHKENT, load_exam)

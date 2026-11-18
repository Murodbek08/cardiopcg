"""CSV exports (sync for small results, background job for large ones)."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import hmac_hash
from app.core.errors import AppError, unprocessable
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.models.enums import ExportFormat, JobStatus, UserRole
from app.models.system import ExportJob
from app.models.user import User
from app.services import analytics_service as an
from app.services.exam_service import TASHKENT
from app.services.storage import get_storage

COLUMNS: dict[str, list[str]] = {
    "examinations": [
        "exam_no",
        "mrn",
        "patient_name",
        "age",
        "gender",
        "examined_at",
        "status",
        "priority",
        "ai_class",
        "ai_confidence",
        "ai_severity",
        "final_class",
        "final_severity",
        "agreement",
        "doctor",
    ],
    "patients": [
        "mrn",
        "patient_name",
        "birth_year",
        "age",
        "gender",
        "blood_group",
        "phone",
        "created_at",
        "exam_count",
    ],
    "conclusions": [
        "exam_no",
        "mrn",
        "signed_at",
        "doctor",
        "final_class",
        "final_severity",
        "agreement",
        "icd10",
        "follow_up_date",
    ],
    "analytics_timeseries": ["t", "value"],
}
PII_COLUMNS = {"patient_name", "phone"}
DEFAULT_COLUMNS = {
    "examinations": [
        "exam_no",
        "mrn",
        "age",
        "gender",
        "examined_at",
        "ai_class",
        "ai_confidence",
        "final_class",
        "agreement",
        "doctor",
    ],
    "patients": ["mrn", "age", "gender", "created_at", "exam_count"],
    "conclusions": ["exam_no", "mrn", "signed_at", "doctor", "final_class", "final_severity", "agreement"],
    "analytics_timeseries": ["t", "value"],
}


def _dt(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=TASHKENT)


def csv_safe(v: Any) -> str:
    """Excel formula-injection guard: prefix cells starting with = + - @ with an apostrophe."""
    s = "" if v is None else (v.isoformat() if isinstance(v, datetime | date) else str(v))
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _date(v: Any, name: str) -> date | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise AppError(422, "VALIDATION_ERROR", f"filters.{name} sana formati noto'g'ri (YYYY-MM-DD)")


def _norm(
    kind: str, filters: dict[str, Any], columns: list[str] | None, anonymize: bool, user: User
) -> tuple[list[str], bool]:
    allowed = COLUMNS[kind]
    cols = columns or DEFAULT_COLUMNS[kind]
    bad = [c for c in cols if c not in allowed]
    if bad:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            f"Noma'lum ustunlar: {bad}",
            [{"field": "columns", "msg": f"allowed: {allowed}", "type": "value_error"}],
        )
    if user.role == UserRole.nurse:
        raise AppError(403, "FORBIDDEN", "CSV eksport ruxsat etilmagan")
    if not anonymize:
        if user.role != UserRole.admin and any(c in PII_COLUMNS for c in cols):
            pass  # allowed for doctors only within own scope (enforced in the query)
    else:
        cols = [c for c in cols if c not in PII_COLUMNS]
    return cols, anonymize


async def build_rows(
    db: AsyncSession,
    user: User,
    kind: str,
    filters: dict[str, Any],
    columns: list[str] | None,
    anonymize: bool,
) -> tuple[list[str], list[list[Any]]]:
    cols, anonymize = _norm(kind, filters, columns, anonymize, user)
    P: dict[str, Any] = {}
    cap = 200_000
    if kind == "examinations":
        cond = ["e.deleted_at IS NULL"]
        if d := _date(filters.get("examined_from"), "examined_from"):
            cond.append("e.examined_at >= :ef")
            P["ef"] = _dt(d)
        if d := _date(filters.get("examined_to"), "examined_to"):
            cond.append("e.examined_at < :et")
            P["et"] = _dt(d + timedelta(days=1))
        sts = filters.get("status")
        if sts:
            if not isinstance(sts, list) or any(
                s
                not in {
                    "draft",
                    "uploaded",
                    "queued",
                    "processing",
                    "ai_ready",
                    "in_review",
                    "completed",
                    "failed",
                    "cancelled",
                }
                for s in sts
            ):
                raise AppError(422, "VALIDATION_ERROR", "filters.status noto'g'ri")
            cond.append("e.status::text = ANY(:sts)")
            P["sts"] = sts
        if filters.get("assigned_doctor_id"):
            cond.append("e.assigned_doctor_id = :adoc")
            P["adoc"] = uuid.UUID(str(filters["assigned_doctor_id"]))
        if user.role == UserRole.doctor:
            cond.append("e.assigned_doctor_id = :me")
            P["me"] = user.id
        sql = f"""SELECT e.exam_no, pt.mrn, pt.last_name || ' ' || pt.first_name AS patient_name,
                    date_part('year', age(e.examined_at::date, pt.birth_date))::int AS age, pt.gender::text AS gender,
                    e.examined_at, e.status::text AS status, e.priority::text AS priority,
                    r.pcg_class::text AS ai_class, r.confidence AS ai_confidence, r.severity::text AS ai_severity,
                    c.final_pcg_class::text AS final_class, c.final_severity::text AS final_severity, c.agreement_with_ai::text AS agreement,
                    u.full_name AS doctor
                  FROM examinations e JOIN patients pt ON pt.id=e.patient_id
                  LEFT JOIN analysis_results r ON r.examination_id=e.id AND r.is_current
                  LEFT JOIN doctor_conclusions c ON c.examination_id=e.id AND c.is_current AND c.status::text IN ('signed','amended')
                  LEFT JOIN users u ON u.id=e.assigned_doctor_id
                  WHERE {" AND ".join(cond)} ORDER BY e.examined_at DESC, e.id LIMIT {cap}"""
    elif kind == "patients":
        cond = ["pt.deleted_at IS NULL"]
        if d := _date(filters.get("created_from"), "created_from"):
            cond.append("pt.created_at >= :cf")
            P["cf"] = _dt(d)
        if d := _date(filters.get("created_to"), "created_to"):
            cond.append("pt.created_at < :ct")
            P["ct"] = _dt(d + timedelta(days=1))
        if filters.get("gender") in ("male", "female"):
            cond.append("pt.gender::text = :g")
            P["g"] = filters["gender"]
        if user.role == UserRole.doctor:
            cond.append(
                "EXISTS (SELECT 1 FROM examinations x WHERE x.patient_id=pt.id AND x.assigned_doctor_id=:me AND x.deleted_at IS NULL)"
            )
            P["me"] = user.id
        sql = f"""SELECT pt.mrn, pt.last_name || ' ' || pt.first_name AS patient_name, extract(year FROM pt.birth_date)::int AS birth_year,
                    date_part('year', age(pt.birth_date))::int AS age, pt.gender::text AS gender, pt.blood_group::text AS blood_group,
                    pt.phone, pt.created_at,
                    (SELECT count(*) FROM examinations x WHERE x.patient_id=pt.id AND x.deleted_at IS NULL) AS exam_count
                  FROM patients pt WHERE {" AND ".join(cond)} ORDER BY pt.created_at DESC, pt.id LIMIT {cap}"""
    elif kind == "conclusions":
        cond = ["c.is_current", "c.status::text IN ('signed','amended')", "e.deleted_at IS NULL"]
        if d := _date(filters.get("signed_from"), "signed_from"):
            cond.append("c.signed_at >= :sf")
            P["sf"] = _dt(d)
        if d := _date(filters.get("signed_to"), "signed_to"):
            cond.append("c.signed_at < :st")
            P["st"] = _dt(d + timedelta(days=1))
        if user.role == UserRole.doctor:
            cond.append("c.doctor_id = :me")
            P["me"] = user.id
        sql = f"""SELECT e.exam_no, pt.mrn, c.signed_at, u.full_name AS doctor, c.final_pcg_class::text AS final_class,
                    c.final_severity::text AS final_severity, c.agreement_with_ai::text AS agreement,
                    array_to_string(c.icd10_codes, ';') AS icd10, c.follow_up_date
                  FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id JOIN patients pt ON pt.id=e.patient_id
                  JOIN users u ON u.id=c.doctor_id WHERE {" AND ".join(cond)} ORDER BY c.signed_at DESC, c.id LIMIT {cap}"""
    else:  # analytics_timeseries
        if user.role == UserRole.doctor:
            raise AppError(403, "FORBIDDEN", "Bu eksport faqat administrator uchun")
        period = an.parse_period(
            _date(filters.get("from"), "from"),
            _date(filters.get("to"), "to"),
            filters.get("tz", "Asia/Tashkent"),
        )
        ts = await an.admin_timeseries(
            db, period, filters.get("metric", "examinations"), filters.get("granularity", "day"), None
        )
        return ["t", "value"], [[s["t"], s["value"]] for s in ts["series"]]

    data = (await db.execute(text(sql), P)).mappings().all()
    out: list[list[Any]] = []
    for r in data:
        row = dict(r)
        if anonymize and "mrn" in row:
            row["mrn"] = "H-" + hmac_hash(row["mrn"])[:10]
        out.append([row.get(c) for c in cols])
    return cols, out


def to_csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM for Excel
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([csv_safe(x) for x in r])
    return buf.getvalue().encode("utf-8")


async def count_estimate(db: AsyncSession, kind: str) -> int:
    table = {"examinations": "examinations", "patients": "patients", "conclusions": "doctor_conclusions"}.get(
        kind
    )
    if not table:
        return 0
    return (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608


async def create_job(db: AsyncSession, user: User, kind: str, body: dict[str, Any]) -> ExportJob:
    job = ExportJob(
        user_id=user.id,
        kind=kind,
        params=body,
        format=ExportFormat.csv,
        status=JobStatus.pending,
        expires_at=utcnow() + timedelta(hours=24),
    )
    db.add(job)
    await db.flush()
    return job


async def run_export_job(job_id: uuid.UUID | str) -> str:
    job_id = uuid.UUID(str(job_id))
    async with get_sessionmaker()() as s:
        job = await s.get(ExportJob, job_id)
        if job is None or job.status != JobStatus.pending:
            return "skipped"
        job.status = JobStatus.running
        user = await s.get(User, job.user_id)
        await s.commit()
        try:
            p = job.params
            header, rows = await build_rows(
                s, user, job.kind, p.get("filters", {}), p.get("columns"), p.get("anonymize", True)
            )
            data = to_csv_bytes(header, rows)
            key = f"exports/{job.id}.csv"
            await get_storage().put_bytes(key, data, "text/csv")
            job.file_key, job.size_bytes, job.status, job.finished_at = (
                key,
                len(data),
                JobStatus.succeeded,
                utcnow(),
            )
        except Exception as exc:
            job.status, job.error, job.finished_at = (
                JobStatus.failed,
                f"{type(exc).__name__}: {exc}"[:500],
                utcnow(),
            )
        await s.commit()
        return job.status.value


async def dispatch_export(job_id: uuid.UUID) -> None:
    runner = get_settings().job_runner
    if runner == "celery":
        from app.workers.celery_app import celery_app

        celery_app.send_task("exports.run_export", args=[str(job_id)], queue="exports")
    elif runner == "inline":
        asyncio.create_task(run_export_job(job_id))  # noqa: RUF006


async def purge_expired_exports() -> int:
    n = 0
    async with get_sessionmaker()() as s:
        rows = (
            (
                await s.execute(
                    select(ExportJob).where(ExportJob.expires_at < utcnow(), ExportJob.file_key.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        for j in rows:
            await get_storage().delete(j.file_key)
            j.file_key = None
            n += 1
        await s.commit()
    return n


_ = (unprocessable, hashlib)

"""Analytics: SQL aggregates over real data (doc 01 sections 3.12-3.13). Raw SQL with bound parameters."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.core.kv import get_kv
from app.core.middleware import LATENCIES

ABNORMAL = "('murmur','extra_heart_sound')"
SIGNED = "('signed','amended')"
CONFUSION_LABELS = ["normal", "murmur", "extra_heart_sound", "artifact"]
AGE_GROUP_SQL = """CASE WHEN a.age < 18 THEN '0-17' WHEN a.age < 40 THEN '18-39' WHEN a.age < 60 THEN '40-59'
 WHEN a.age < 75 THEN '60-74' ELSE '75+' END"""


@dataclass
class Period:
    start: datetime
    end: datetime
    prev_start: datetime
    prev_end: datetime
    tz: str
    d_from: date
    d_to: date

    def params(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "pstart": self.prev_start,
            "pend": self.prev_end,
            "tz": self.tz,
        }


def parse_period(d_from: date | None, d_to: date | None, tz: str = "Asia/Tashkent") -> Period:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "tz noto'g'ri",
            [{"field": "tz", "msg": "unknown timezone", "type": "value_error"}],
        )
    today = datetime.now(zone).date()
    d_to = d_to or today
    d_from = d_from or (d_to - timedelta(days=29))
    if d_from > d_to:
        raise AppError(422, "VALIDATION_ERROR", "from to'dan keyin bo'lishi mumkin emas")
    if (d_to - d_from).days > 1830:
        raise AppError(422, "VALIDATION_ERROR", "Davr 5 yildan oshmasligi kerak")
    start = datetime.combine(d_from, datetime.min.time(), tzinfo=zone)
    end = datetime.combine(d_to + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    span = end - start
    return Period(start, end, start - span, start, tz, d_from, d_to)


def pct_delta(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def kpi(value: float | int | None, prev: float | int | None = None, ndigits: int = 1) -> dict[str, Any]:
    v = round(value, ndigits) if isinstance(value, float) else value
    return {
        "value": v,
        "delta_pct": pct_delta(
            float(value) if value is not None else None, float(prev) if prev is not None else None
        ),
    }


async def rows(db: AsyncSession, sql: str, **p: Any) -> list[dict[str, Any]]:
    res = await db.execute(text(sql), p)
    return [dict(r) for r in res.mappings().all()]


async def scalar(db: AsyncSession, sql: str, **p: Any) -> Any:
    return (await db.execute(text(sql), p)).scalar()


# ----------------------------------------------------------------------------------- caching
async def cached(endpoint: str, user_id: uuid.UUID, params: dict[str, Any], compute) -> dict[str, Any]:
    ttl = get_settings().analytics_cache_ttl
    if ttl <= 0:
        return await compute()
    digest = hashlib.sha256(
        orjson.dumps({"p": params, "u": str(user_id)}, default=str, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()[:20]
    key = f"analytics:{endpoint}:{digest}"
    kv = get_kv()
    hit = await kv.get(key)
    if hit:
        return orjson.loads(hit)
    out = await compute()
    await kv.set(key, orjson.dumps(out, default=str).decode(), ttl)
    return out


async def invalidate() -> None:
    await get_kv().delete_prefix("analytics:")


# -------------------------------------------------------------------------------- admin
async def admin_kpis(db: AsyncSession, p: Period) -> dict[str, Any]:
    P = p.params()

    async def exams(a: str, b: str) -> int:
        return await scalar(
            db,
            "SELECT count(*) FROM examinations WHERE deleted_at IS NULL AND examined_at >= :a AND examined_at < :b",
            a=P[a],
            b=P[b],
        )

    async def completed(a: str, b: str) -> int:
        return await scalar(
            db,
            "SELECT count(*) FROM examinations WHERE deleted_at IS NULL AND completed_at >= :a AND completed_at < :b",
            a=P[a],
            b=P[b],
        )

    async def new_patients(a: str, b: str) -> int:
        return await scalar(
            db,
            "SELECT count(*) FROM patients WHERE deleted_at IS NULL AND created_at >= :a AND created_at < :b",
            a=P[a],
            b=P[b],
        )

    async def failed(a: str, b: str) -> int:
        return await scalar(
            db,
            "SELECT count(*) FROM analysis_jobs WHERE status='failed' AND finished_at >= :a AND finished_at < :b",
            a=P[a],
            b=P[b],
        )

    async def abnormal(a: str, b: str) -> float | None:
        return await scalar(
            db,
            f"""SELECT 100.0 * count(*) FILTER (WHERE r.pcg_class::text IN {ABNORMAL}) / NULLIF(count(*),0)
                FROM analysis_results r JOIN examinations e ON e.id=r.examination_id
                WHERE r.is_current AND e.deleted_at IS NULL AND e.examined_at >= :a AND e.examined_at < :b""",
            a=P[a],
            b=P[b],
        )

    async def critical(a: str, b: str) -> int:
        return await scalar(
            db,
            """SELECT count(*) FROM analysis_results r JOIN examinations e ON e.id=r.examination_id
               WHERE r.is_current AND e.deleted_at IS NULL AND r.severity::text IN ('severe','critical')
               AND e.examined_at >= :a AND e.examined_at < :b""",
            a=P[a],
            b=P[b],
        )

    async def proc(a: str, b: str) -> float | None:
        v = await scalar(
            db,
            "SELECT avg(processing_ms) FROM analysis_results WHERE created_at >= :a AND created_at < :b",
            a=P[a],
            b=P[b],
        )
        return float(v) / 1000 if v is not None else None

    async def ttc(a: str, b: str) -> float | None:
        v = await scalar(
            db,
            f"""SELECT avg(extract(epoch FROM (c.signed_at - e.ai_completed_at)))/60 FROM doctor_conclusions c
                JOIN examinations e ON e.id=c.examination_id
                WHERE c.is_current AND c.status::text IN {SIGNED} AND e.ai_completed_at IS NOT NULL
                AND c.signed_at >= :a AND c.signed_at < :b""",
            a=P[a],
            b=P[b],
        )
        return float(v) if v is not None else None

    async def agree(a: str, b: str) -> float | None:
        v = await scalar(
            db,
            f"""SELECT 100.0 * count(*) FILTER (WHERE agreement_with_ai='agree') / NULLIF(count(*),0)
                FROM doctor_conclusions WHERE is_current AND status::text IN {SIGNED} AND signed_at >= :a AND signed_at < :b""",
            a=P[a],
            b=P[b],
        )
        return float(v) if v is not None else None

    async def active(a: str, b: str) -> int:
        return await scalar(
            db,
            "SELECT count(DISTINCT user_id) FROM audit_logs WHERE user_id IS NOT NULL AND success AND ts >= :a AND ts < :b",
            a=P[a],
            b=P[b],
        )

    async def cost(a: str, b: str) -> float:
        return float(
            await scalar(
                db,
                "SELECT coalesce(sum(cost_usd),0) FROM ai_reports WHERE created_at >= :a AND created_at < :b",
                a=P[a],
                b=P[b],
            )
        )

    total_patients = await scalar(
        db, "SELECT count(*) FROM patients WHERE deleted_at IS NULL AND created_at < :b", b=P["end"]
    )
    total_patients_prev = await scalar(
        db, "SELECT count(*) FROM patients WHERE deleted_at IS NULL AND created_at < :b", b=P["start"]
    )
    pending = await scalar(
        db,
        "SELECT count(*) FROM examinations WHERE deleted_at IS NULL AND status::text IN ('ai_ready','in_review')",
    )
    storage = await scalar(db, "SELECT coalesce(sum(size_bytes),0) FROM recordings WHERE deleted_at IS NULL")
    kpis = {
        "total_patients": kpi(total_patients, total_patients_prev),
        "new_patients": kpi(await new_patients("start", "end"), await new_patients("pstart", "pend")),
        "examinations_total": kpi(await exams("start", "end"), await exams("pstart", "pend")),
        "examinations_completed": kpi(await completed("start", "end"), await completed("pstart", "pend")),
        "pending_review": {"value": pending, "delta_pct": None},
        "failed_analyses": kpi(await failed("start", "end"), await failed("pstart", "pend")),
        "abnormal_rate_pct": kpi(await abnormal("start", "end"), await abnormal("pstart", "pend")),
        "critical_findings": kpi(await critical("start", "end"), await critical("pstart", "pend")),
        "avg_ai_processing_sec": kpi(await proc("start", "end"), await proc("pstart", "pend")),
        "avg_time_to_conclusion_min": kpi(await ttc("start", "end"), await ttc("pstart", "pend")),
        "ai_doctor_agreement_pct": kpi(await agree("start", "end"), await agree("pstart", "pend")),
        "active_users": kpi(await active("start", "end"), await active("pstart", "pend")),
        "storage_used_gb": {"value": round(float(storage) / 1e9, 3), "delta_pct": None},
        "llm_cost_usd": kpi(await cost("start", "end"), await cost("pstart", "pend"), 5),
    }
    return {"period": {"from": p.d_from.isoformat(), "to": p.d_to.isoformat()}, "kpis": kpis}


GRAN = {"day": "day", "week": "week", "month": "month"}


def _buckets(p: Period, gran: str) -> list[date]:
    out: list[date] = []
    d = p.d_from
    if gran == "week":
        d = d - timedelta(days=d.weekday())
    elif gran == "month":
        d = d.replace(day=1)
    while d <= p.d_to:
        out.append(d)
        if gran == "day":
            d += timedelta(days=1)
        elif gran == "week":
            d += timedelta(days=7)
        else:
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _metric_sql(metric: str) -> tuple[str, str, str]:
    """returns (from/join clause, timestamp expr, value expr)"""
    table = {
        "examinations": ("examinations e", "e.examined_at", "count(*)", "e.deleted_at IS NULL"),
        "completed": (
            "examinations e",
            "e.completed_at",
            "count(*)",
            "e.deleted_at IS NULL AND e.completed_at IS NOT NULL",
        ),
        "abnormal": (
            "analysis_results r JOIN examinations e ON e.id=r.examination_id",
            "e.examined_at",
            "count(*)",
            f"e.deleted_at IS NULL AND r.is_current AND r.pcg_class::text IN {ABNORMAL}",
        ),
        "new_patients": ("patients e", "e.created_at", "count(*)", "e.deleted_at IS NULL"),
        "failed": ("analysis_jobs e", "e.finished_at", "count(*)", "e.status = 'failed'"),
        "llm_tokens": (
            "ai_reports e",
            "e.created_at",
            "coalesce(sum(coalesce(e.prompt_tokens,0)+coalesce(e.completion_tokens,0)),0)",
            "true",
        ),
    }
    if metric not in table:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            f"Noma'lum metric: {metric}",
            [{"field": "metric", "msg": f"allowed: {', '.join(table)}", "type": "value_error"}],
        )
    f, ts, val, where = table[metric]
    return f, ts, val, where  # type: ignore[return-value]


async def admin_timeseries(
    db: AsyncSession, p: Period, metric: str, gran: str, group_by: str | None
) -> dict[str, Any]:
    if gran not in GRAN:
        raise AppError(422, "VALIDATION_ERROR", "granularity: day|week|month")
    frm, ts, val, where = _metric_sql(metric)
    buckets = _buckets(p, gran)
    P = {"start": p.start, "end": p.end, "tz": p.tz}
    bucket_expr = f"date_trunc('{GRAN[gran]}', {ts} AT TIME ZONE :tz)::date"
    if not group_by:
        data = await rows(
            db,
            f"SELECT {bucket_expr} AS t, {val} AS v FROM {frm} WHERE {where} AND {ts} >= :start AND {ts} < :end GROUP BY 1",
            **P,
        )
        m = {r["t"]: float(r["v"]) for r in data}
        series = [
            {
                "t": b.isoformat(),
                "value": int(m.get(b, 0)) if float(m.get(b, 0)).is_integer() else m.get(b, 0),
            }
            for b in buckets
        ]
        return {"metric": metric, "granularity": gran, "series": series, "series_by": None}
    group_sql = {
        "pcg_class": (
            "r.pcg_class::text",
            "analysis_results r JOIN examinations e ON e.id=r.examination_id",
            "r.is_current",
        ),
        "status": ("e.status::text", "examinations e", "true"),
        "priority": ("e.priority::text", "examinations e", "true"),
        "doctor": (
            "coalesce(u.full_name,'unassigned')",
            "examinations e LEFT JOIN users u ON u.id=e.assigned_doctor_id",
            "true",
        ),
    }
    if metric not in ("examinations", "abnormal", "completed") or group_by not in group_sql:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "group_by faqat examinations/completed/abnormal uchun: pcg_class|status|priority|doctor",
        )
    g_expr, g_from, g_where = group_sql[group_by]
    ts_col = "e.examined_at" if metric != "completed" else "e.completed_at"
    extra = "" if metric != "abnormal" else f" AND r.pcg_class::text IN {ABNORMAL}"
    if metric == "abnormal" and group_by != "pcg_class":
        g_from = "analysis_results r JOIN examinations e ON e.id=r.examination_id" + (
            " LEFT JOIN users u ON u.id=e.assigned_doctor_id" if group_by == "doctor" else ""
        )
        g_where = "r.is_current"
    if metric == "completed":
        extra += " AND e.completed_at IS NOT NULL"
    data = await rows(
        db,
        f"""SELECT date_trunc('{GRAN[gran]}', {ts_col} AT TIME ZONE :tz)::date AS t, {g_expr} AS g, count(*) AS v
            FROM {g_from} WHERE e.deleted_at IS NULL AND {g_where}{extra} AND {ts_col} >= :start AND {ts_col} < :end GROUP BY 1,2""",
        **P,
    )
    keys = sorted({r["g"] for r in data})
    by = {k: {r["t"]: r["v"] for r in data if r["g"] == k} for k in keys}
    return {
        "metric": metric,
        "granularity": gran,
        "series": None,
        "series_by": {
            k: [{"t": b.isoformat(), "value": int(by[k].get(b, 0))} for b in buckets] for k in keys
        },
    }


async def distribution_rows(
    db: AsyncSession, p: Period, dimension: str, doctor_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    P: dict[str, Any] = {"start": p.start, "end": p.end}
    doc_filter = ""
    if doctor_id:
        P["doc"] = doctor_id
    age_cte = """WITH a AS (SELECT e.id AS eid, date_part('year', age(e.examined_at::date, pt.birth_date))::int AS age
                 FROM examinations e JOIN patients pt ON pt.id=e.patient_id WHERE e.deleted_at IS NULL
                 AND e.examined_at >= :start AND e.examined_at < :end)"""
    q = {
        "pcg_class": "SELECT r.pcg_class::text AS k, count(*) AS c FROM analysis_results r JOIN examinations e ON e.id=r.examination_id WHERE r.is_current AND e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end {doc_e} GROUP BY 1",
        "severity": "SELECT r.severity::text AS k, count(*) AS c FROM analysis_results r JOIN examinations e ON e.id=r.examination_id WHERE r.is_current AND e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end {doc_e} GROUP BY 1",
        "status": "SELECT e.status::text AS k, count(*) AS c FROM examinations e WHERE e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end {doc_e} GROUP BY 1",
        "priority": "SELECT e.priority::text AS k, count(*) AS c FROM examinations e WHERE e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end {doc_e} GROUP BY 1",
        "gender": "SELECT pt.gender::text AS k, count(*) AS c FROM examinations e JOIN patients pt ON pt.id=e.patient_id WHERE e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end {doc_e} GROUP BY 1",
        "age_group": age_cte
        + f" SELECT {AGE_GROUP_SQL} AS k, count(*) AS c FROM a JOIN examinations e ON e.id=a.eid WHERE true {{doc_e}} GROUP BY 1",
        "site": "SELECT rc.site::text AS k, count(*) AS c FROM recordings rc JOIN examinations e ON e.id=rc.examination_id WHERE rc.kind='audio' AND rc.deleted_at IS NULL AND e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end {doc_e} GROUP BY 1",
        "icd10": f"SELECT code AS k, count(*) AS c FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id CROSS JOIN LATERAL unnest(c.icd10_codes) AS code WHERE c.is_current AND c.status::text IN {SIGNED} AND e.deleted_at IS NULL AND c.signed_at >= :start AND c.signed_at < :end {{doc_c}} GROUP BY 1",
        "final_pcg_class": f"SELECT c.final_pcg_class::text AS k, count(*) AS c FROM doctor_conclusions c WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {{doc_c}} GROUP BY 1",
        "final_severity": f"SELECT c.final_severity::text AS k, count(*) AS c FROM doctor_conclusions c WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {{doc_c}} GROUP BY 1",
    }
    if dimension not in q:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            f"Noma'lum dimension: {dimension}",
            [{"field": "dimension", "msg": f"allowed: {', '.join(q)}", "type": "value_error"}],
        )
    if doctor_id:
        doc_filter = "AND e.assigned_doctor_id = :doc"
    sql = q[dimension].format(doc_e=doc_filter, doc_c="AND c.doctor_id = :doc" if doctor_id else "")
    if dimension in ("icd10",) and doctor_id:
        sql = sql.replace("AND c.doctor_id = :doc", "AND c.doctor_id = :doc")
    data = await rows(db, sql, **P)
    order = {"age_group": ["0-17", "18-39", "40-59", "60-74", "75+"]}.get(dimension)
    data.sort(key=lambda r: order.index(r["k"]) if order and r["k"] in order else -r["c"])
    return data


def to_distribution(dimension: str, data: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(r["c"] for r in data)
    return {
        "dimension": dimension,
        "total": total,
        "items": [
            {"key": r["k"], "count": r["c"], "pct": round(100.0 * r["c"] / total, 1) if total else 0.0}
            for r in data
        ],
    }


async def admin_workload(db: AsyncSession, p: Period) -> dict[str, Any]:
    P = {"start": p.start, "end": p.end}
    doctors = await rows(
        db,
        f"""SELECT u.id AS user_id, u.full_name,
              (SELECT count(*) FROM examinations e WHERE e.assigned_doctor_id=u.id AND e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end) AS assigned,
              (SELECT count(*) FROM doctor_conclusions c WHERE c.doctor_id=u.id AND c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end) AS completed,
              (SELECT count(*) FROM examinations e WHERE e.assigned_doctor_id=u.id AND e.deleted_at IS NULL AND e.status::text IN ('ai_ready','in_review')) AS pending,
              (SELECT avg(extract(epoch FROM (c.signed_at - e.ai_completed_at)))/60 FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id
                 WHERE c.doctor_id=u.id AND c.is_current AND c.status::text IN {SIGNED} AND e.ai_completed_at IS NOT NULL AND c.signed_at >= :start AND c.signed_at < :end) AS avg_ttc,
              (SELECT 100.0*count(*) FILTER (WHERE c.agreement_with_ai='agree')/NULLIF(count(*),0) FROM doctor_conclusions c
                 WHERE c.doctor_id=u.id AND c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end) AS agr
            FROM users u WHERE u.role='doctor' AND u.deleted_at IS NULL ORDER BY u.full_name""",
        **P,
    )
    nurses = await rows(
        db,
        """SELECT u.id AS user_id, u.full_name,
              (SELECT count(*) FROM examinations e WHERE e.performed_by=u.id AND e.deleted_at IS NULL AND e.created_at >= :start AND e.created_at < :end) AS exams_created,
              (SELECT count(*) FROM recordings r WHERE r.uploaded_by=u.id AND r.kind='audio' AND r.created_at >= :start AND r.created_at < :end) AS recs,
              (SELECT count(*) FROM audit_logs a WHERE a.user_id=u.id AND a.action='upload' AND NOT a.success AND a.ts >= :start AND a.ts < :end) AS rejected
            FROM users u WHERE u.role='nurse' AND u.deleted_at IS NULL ORDER BY u.full_name""",
        **P,
    )
    queue_rows = await rows(
        db,
        "SELECT status::text AS s, count(*) AS c FROM examinations WHERE deleted_at IS NULL AND status::text IN ('queued','processing','ai_ready','in_review') GROUP BY 1",
    )
    qm = {r["s"]: r["c"] for r in queue_rows}
    oldest = await scalar(
        db,
        "SELECT extract(epoch FROM (now() - min(coalesce(ai_completed_at, created_at))))/60 FROM examinations WHERE deleted_at IS NULL AND status::text IN ('ai_ready','in_review')",
    )
    return {
        "doctors": [
            {
                "user_id": d["user_id"],
                "full_name": d["full_name"],
                "assigned": d["assigned"],
                "completed": d["completed"],
                "pending": d["pending"],
                "avg_time_to_conclusion_min": round(float(d["avg_ttc"]), 1)
                if d["avg_ttc"] is not None
                else None,
                "agreement_pct": round(float(d["agr"]), 1) if d["agr"] is not None else None,
            }
            for d in doctors
        ],
        "nurses": [
            {
                "user_id": n["user_id"],
                "full_name": n["full_name"],
                "exams_created": n["exams_created"],
                "recordings_uploaded": n["recs"],
                "rejected_recordings": n["rejected"],
                "avg_recordings_per_exam": round(n["recs"] / n["exams_created"], 1)
                if n["exams_created"]
                else 0.0,
            }
            for n in nurses
        ],
        "queue": {k: qm.get(k, 0) for k in ("queued", "processing", "ai_ready", "in_review")}
        | {"oldest_pending_min": int(oldest) if oldest is not None else None},
    }


async def admin_heatmap(db: AsyncSession, p: Period, metric: str) -> dict[str, Any]:
    if metric != "examinations":
        raise AppError(422, "VALIDATION_ERROR", "metric faqat examinations")
    data = await rows(
        db,
        """SELECT extract(isodow FROM e.examined_at AT TIME ZONE :tz)::int AS dow, extract(hour FROM e.examined_at AT TIME ZONE :tz)::int AS hour, count(*) AS v
           FROM examinations e WHERE e.deleted_at IS NULL AND e.examined_at >= :start AND e.examined_at < :end GROUP BY 1,2 ORDER BY 1,2""",
        start=p.start,
        end=p.end,
        tz=p.tz,
    )
    return {"metric": metric, "items": [{"dow": r["dow"], "hour": r["hour"], "value": r["v"]} for r in data]}


async def confusion(
    db: AsyncSession, p: Period, doctor_id: uuid.UUID | None = None, model_version: str | None = None
) -> dict[str, Any]:
    P: dict[str, Any] = {"start": p.start, "end": p.end}
    cond = ""
    if doctor_id:
        cond += " AND c.doctor_id = :doc"
        P["doc"] = doctor_id
    if model_version:
        cond += " AND r.model_version = :mv"
        P["mv"] = model_version
    data = await rows(
        db,
        f"""SELECT c.final_pcg_class::text AS fin, r.pcg_class::text AS ai, count(*) AS n
            FROM doctor_conclusions c JOIN analysis_results r ON r.examination_id=c.examination_id AND r.is_current
            WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {cond} GROUP BY 1,2""",
        **P,
    )
    idx = {k: i for i, k in enumerate(CONFUSION_LABELS)}
    matrix = [[0] * len(CONFUSION_LABELS) for _ in CONFUSION_LABELS]
    for r in data:
        if r["fin"] in idx and r["ai"] in idx:
            matrix[idx[r["fin"]]][idx[r["ai"]]] += r["n"]
    return {"labels": CONFUSION_LABELS, "matrix": matrix}


async def ai_performance(db: AsyncSession, p: Period) -> dict[str, Any]:
    P = {"start": p.start, "end": p.end}
    versions = await rows(
        db,
        f"""SELECT r.model_version AS v, count(*) AS n,
              count(*) FILTER (WHERE c.agreement_with_ai='agree') AS agree,
              count(*) FILTER (WHERE c.agreement_with_ai='partial') AS partial,
              count(*) FILTER (WHERE c.agreement_with_ai='disagree') AS disagree,
              avg(r.confidence) AS avg_conf
            FROM doctor_conclusions c JOIN analysis_results r ON r.examination_id=c.examination_id AND r.is_current
            WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end GROUP BY 1 ORDER BY 1""",
        **P,
    )
    out = []
    for v in versions:
        calib = await rows(
            db,
            f"""SELECT least(floor(r.confidence*10),9)::int AS b, count(*) AS n, avg(r.confidence) AS mc,
                  avg(CASE WHEN r.pcg_class=c.final_pcg_class THEN 1.0 ELSE 0.0 END) AS acc
                FROM doctor_conclusions c JOIN analysis_results r ON r.examination_id=c.examination_id AND r.is_current
                WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end AND r.model_version=:mv GROUP BY 1 ORDER BY 1""",
            mv=v["v"],
            **P,
        )
        n = v["n"]
        out.append(
            {
                "version": v["v"],
                "n": n,
                "agreement_pct": round(100.0 * v["agree"] / n, 1),
                "partial_pct": round(100.0 * v["partial"] / n, 1),
                "disagree_pct": round(100.0 * v["disagree"] / n, 1),
                "avg_confidence": round(float(v["avg_conf"]), 3),
                "confusion_matrix": await confusion(db, p, model_version=v["v"]),
                "calibration": [
                    {
                        "bin": f"{c['b'] / 10:.1f}-{(c['b'] + 1) / 10:.1f}",
                        "mean_conf": round(float(c["mc"]), 3),
                        "accuracy": round(float(c["acc"]), 3),
                        "n": c["n"],
                    }
                    for c in calib
                ],
            }
        )
    llm = (
        await rows(
            db,
            """SELECT avg(latency_ms) AS lat, coalesce(sum(coalesce(prompt_tokens,0)+coalesce(completion_tokens,0)),0) AS tok,
                 coalesce(sum(cost_usd),0) AS cost, count(*) AS n, count(*) FILTER (WHERE status::text IN ('failed')) AS failed
               FROM ai_reports WHERE created_at >= :start AND created_at < :end""",
            **P,
        )
    )[0]
    return {
        "model_versions": out,
        "llm": {
            "avg_latency_ms": round(float(llm["lat"])) if llm["lat"] is not None else None,
            "total_tokens": int(llm["tok"]),
            "cost_usd": round(float(llm["cost"]), 5),
            "error_rate_pct": round(100.0 * llm["failed"] / llm["n"], 1) if llm["n"] else 0.0,
        },
    }


def _percentile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[min(int(q * len(s)), len(s) - 1)]


async def admin_system(db: AsyncSession) -> dict[str, Any]:
    lat = list(LATENCIES)
    jobs = await rows(
        db,
        "SELECT status::text AS s, count(*) AS c FROM analysis_jobs WHERE status::text IN ('pending','running') GROUP BY 1",
    )
    errors = await scalar(
        db,
        "SELECT count(*) FROM analysis_jobs WHERE status='failed' AND finished_at >= now() - interval '24 hours'",
    )
    storage = get_settings().storage_local_dir
    disk = None
    try:
        du = shutil.disk_usage(storage)
        disk = {
            "total_gb": round(du.total / 1e9, 1),
            "used_gb": round(du.used / 1e9, 1),
            "free_gb": round(du.free / 1e9, 1),
        }
    except OSError:
        pass
    return {
        "api_latency_ms": {
            "p50": round(_percentile(lat, 0.5) * 1000, 1) if lat else None,
            "p95": round(_percentile(lat, 0.95) * 1000, 1) if lat else None,
            "samples": len(lat),
        },
        "jobs": {r["s"]: r["c"] for r in jobs},
        "failed_jobs_24h": errors,
        "disk": disk,
    }


# --------------------------------------------------------------------------------------- doctor
async def doctor_kpis(db: AsyncSession, p: Period, doctor_id: uuid.UUID | None, tz: str) -> dict[str, Any]:
    P: dict[str, Any] = {"start": p.start, "end": p.end, "tz": tz}
    dc = ""
    de = ""
    if doctor_id:
        P["doc"] = doctor_id
        dc, de = "AND c.doctor_id = :doc", "AND e.assigned_doctor_id = :doc"
    pending = await scalar(
        db,
        f"SELECT count(*) FROM examinations e WHERE e.deleted_at IS NULL AND e.status::text IN ('ai_ready','in_review') {de}",
        **P,
    )
    urgent = await scalar(
        db,
        f"SELECT count(*) FROM examinations e WHERE e.deleted_at IS NULL AND e.status::text IN ('ai_ready','in_review') AND e.priority::text IN ('urgent','emergency') {de}",
        **P,
    )
    today = await scalar(
        db,
        f"""SELECT count(*) FROM doctor_conclusions c WHERE c.is_current AND c.status::text IN {SIGNED}
            AND (c.signed_at AT TIME ZONE :tz)::date = (now() AT TIME ZONE :tz)::date {dc}""",
        **P,
    )
    period_row = (
        await rows(
            db,
            f"""SELECT count(*) AS n, 100.0*count(*) FILTER (WHERE c.agreement_with_ai='agree')/NULLIF(count(*),0) AS agr,
                  count(*) FILTER (WHERE c.agreement_with_ai <> 'agree') AS overrides,
                  avg(extract(epoch FROM (c.signed_at - e.ai_completed_at)))/60 AS ttc
                FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id
                WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {dc}""",
            **P,
        )
    )[0]
    seen = await scalar(
        db,
        f"""SELECT count(DISTINCT e.patient_id) FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id
            WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {dc}""",
        **P,
    )
    fu = await scalar(
        db,
        f"""SELECT count(*) FROM doctor_conclusions c WHERE c.is_current AND c.status::text IN {SIGNED}
            AND c.follow_up_date BETWEEN (now() AT TIME ZONE :tz)::date AND (now() AT TIME ZONE :tz)::date + 7 {dc}""",
        **P,
    )
    f = lambda v, nd=1: round(float(v), nd) if v is not None else None  # noqa: E731
    return {
        "period": {"from": p.d_from.isoformat(), "to": p.d_to.isoformat()},
        "kpis": {
            "my_pending": {"value": pending},
            "my_completed_today": {"value": today},
            "my_completed_period": {"value": period_row["n"]},
            "avg_time_to_conclusion_min": {"value": f(period_row["ttc"])},
            "urgent_waiting": {"value": urgent},
            "ai_agreement_pct": {"value": f(period_row["agr"])},
            "overrides_count": {"value": period_row["overrides"]},
            "patients_seen": {"value": seen},
            "follow_ups_due_7d": {"value": fu},
        },
    }


async def doctor_queue(db: AsyncSession, doctor_id: uuid.UUID | None, limit: int = 50) -> dict[str, Any]:
    P: dict[str, Any] = {"lim": limit}
    cond = ""
    if doctor_id:
        P["doc"] = doctor_id
        cond = "AND (e.assigned_doctor_id = :doc OR e.assigned_doctor_id IS NULL)"
    data = await rows(
        db,
        f"""SELECT e.id AS exam_id, e.exam_no, e.priority::text AS priority, pt.id AS pid, pt.mrn, pt.last_name, pt.first_name, pt.gender::text AS gender,
              date_part('year', age(pt.birth_date))::int AS age, r.severity::text AS severity, r.pcg_class::text AS ai_class,
              (extract(epoch FROM (now() - coalesce(e.ai_completed_at, e.created_at)))/60)::int AS waiting_min
            FROM examinations e JOIN patients pt ON pt.id=e.patient_id LEFT JOIN analysis_results r ON r.examination_id=e.id AND r.is_current
            WHERE e.deleted_at IS NULL AND e.status::text IN ('ai_ready','in_review') {cond}
            ORDER BY CASE e.priority::text WHEN 'emergency' THEN 3 WHEN 'urgent' THEN 2 ELSE 1 END DESC, e.ai_completed_at NULLS LAST, e.id LIMIT :lim""",
        **P,
    )
    return {
        "items": [
            {
                "exam_id": r["exam_id"],
                "exam_no": r["exam_no"],
                "priority": r["priority"],
                "patient": {
                    "id": r["pid"],
                    "mrn": r["mrn"],
                    "full_name": f"{r['last_name']} {r['first_name']}",
                    "age": r["age"],
                    "gender": r["gender"],
                },
                "severity": r["severity"],
                "ai_class": r["ai_class"],
                "waiting_min": r["waiting_min"],
            }
            for r in data
        ]
    }


async def doctor_timeseries(
    db: AsyncSession, p: Period, doctor_id: uuid.UUID | None, metric: str, gran: str
) -> dict[str, Any]:
    if gran not in GRAN or metric not in ("completed", "agreement", "avg_time"):
        raise AppError(
            422, "VALIDATION_ERROR", "metric: completed|agreement|avg_time; granularity: day|week|month"
        )
    P: dict[str, Any] = {"start": p.start, "end": p.end, "tz": p.tz}
    dc = ""
    if doctor_id:
        P["doc"] = doctor_id
        dc = "AND c.doctor_id = :doc"
    val = {
        "completed": "count(*)",
        "agreement": "100.0*count(*) FILTER (WHERE c.agreement_with_ai='agree')/NULLIF(count(*),0)",
        "avg_time": "avg(extract(epoch FROM (c.signed_at - e.ai_completed_at)))/60",
    }[metric]
    data = await rows(
        db,
        f"""SELECT date_trunc('{GRAN[gran]}', c.signed_at AT TIME ZONE :tz)::date AS t, {val} AS v
            FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id
            WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {dc} GROUP BY 1""",
        **P,
    )
    m = {r["t"]: r["v"] for r in data}
    series = []
    for b in _buckets(p, gran):
        v = m.get(b)
        series.append(
            {
                "t": b.isoformat(),
                "value": (
                    int(v)
                    if metric == "completed" and v is not None
                    else round(float(v), 1)
                    if v is not None
                    else (0 if metric == "completed" else None)
                ),
            }
        )
    return {"metric": metric, "granularity": gran, "series": series}


async def ai_vs_doctor(db: AsyncSession, p: Period, doctor_id: uuid.UUID | None) -> dict[str, Any]:
    P: dict[str, Any] = {"start": p.start, "end": p.end}
    dc = ""
    if doctor_id:
        P["doc"] = doctor_id
        dc = "AND c.doctor_id = :doc"
    tot = (
        await rows(
            db,
            f"""SELECT count(*) AS n, count(*) FILTER (WHERE agreement_with_ai='agree') AS a, count(*) FILTER (WHERE agreement_with_ai='partial') AS pa,
                  count(*) FILTER (WHERE agreement_with_ai='disagree') AS d FROM doctor_conclusions c
                WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {dc}""",
            **P,
        )
    )[0]
    dis = await rows(
        db,
        f"""SELECT c.examination_id AS exam_id, r.pcg_class::text AS ai_class, c.final_pcg_class::text AS final_class, c.disagreement_reason AS reason, c.signed_at
            FROM doctor_conclusions c JOIN analysis_results r ON r.examination_id=c.examination_id AND r.is_current
            WHERE c.is_current AND c.status::text IN {SIGNED} AND c.agreement_with_ai <> 'agree' AND c.signed_at >= :start AND c.signed_at < :end {dc}
            ORDER BY c.signed_at DESC LIMIT 50""",
        **P,
    )
    trend = await rows(
        db,
        f"""SELECT to_char(date_trunc('week', c.signed_at), 'IYYY-"W"IW') AS t, 100.0*count(*) FILTER (WHERE c.agreement_with_ai='agree')/count(*) AS agr
            FROM doctor_conclusions c WHERE c.is_current AND c.status::text IN {SIGNED} AND c.signed_at >= :start AND c.signed_at < :end {dc} GROUP BY 1 ORDER BY 1""",
        **P,
    )
    n = tot["n"]
    return {
        "total": n,
        "agree": tot["a"],
        "partial": tot["pa"],
        "disagree": tot["d"],
        "agreement_pct": round(100.0 * tot["a"] / n, 1) if n else None,
        "weighted_agreement_pct": round(100.0 * (tot["a"] + 0.5 * tot["pa"]) / n, 1) if n else None,
        "confusion_matrix": await confusion(db, p, doctor_id=doctor_id),
        "disagreements": dis,
        "trend": [{"t": r["t"], "agreement_pct": round(float(r["agr"]), 1)} for r in trend],
    }


async def doctor_follow_ups(db: AsyncSession, doctor_id: uuid.UUID | None, days: int = 30) -> dict[str, Any]:
    P: dict[str, Any] = {"days": days}
    dc = ""
    if doctor_id:
        P["doc"] = doctor_id
        dc = "AND c.doctor_id = :doc"
    data = await rows(
        db,
        f"""SELECT c.examination_id AS exam_id, e.exam_no, c.follow_up_date, c.follow_up_notes, pt.id AS pid, pt.mrn, pt.last_name, pt.first_name
            FROM doctor_conclusions c JOIN examinations e ON e.id=c.examination_id JOIN patients pt ON pt.id=e.patient_id
            WHERE c.is_current AND c.status::text IN {SIGNED} AND c.follow_up_date IS NOT NULL
              AND c.follow_up_date BETWEEN current_date AND current_date + :days {dc} ORDER BY c.follow_up_date, e.id""",
        **P,
    )
    return {
        "items": [
            {
                "exam_id": r["exam_id"],
                "exam_no": r["exam_no"],
                "follow_up_date": r["follow_up_date"].isoformat(),
                "notes": r["follow_up_notes"],
                "patient": {
                    "id": r["pid"],
                    "mrn": r["mrn"],
                    "full_name": f"{r['last_name']} {r['first_name']}",
                },
            }
            for r in data
        ]
    }


# ---------------------------------------------------------------------------------------- nurse
async def nurse_kpis(db: AsyncSession, p: Period, nurse_id: uuid.UUID | None, tz: str) -> dict[str, Any]:
    P: dict[str, Any] = {"start": p.start, "end": p.end, "tz": tz}
    ne = nr = na = ""
    if nurse_id:
        P["nid"] = nurse_id
        ne, nr, na = "AND e.performed_by = :nid", "AND r.uploaded_by = :nid", "AND a.user_id = :nid"
    today = await scalar(
        db,
        f"SELECT count(*) FROM examinations e WHERE e.deleted_at IS NULL AND (e.created_at AT TIME ZONE :tz)::date = (now() AT TIME ZONE :tz)::date {ne}",
        **P,
    )
    period = await scalar(
        db,
        f"SELECT count(*) FROM examinations e WHERE e.deleted_at IS NULL AND e.created_at >= :start AND e.created_at < :end {ne}",
        **P,
    )
    recs = (
        await rows(
            db,
            f"SELECT count(*) AS n, avg(r.quality_score) AS q FROM recordings r WHERE r.kind='audio' AND r.deleted_at IS NULL AND r.created_at >= :start AND r.created_at < :end {nr}",
            **P,
        )
    )[0]
    rejected = await scalar(
        db,
        f"SELECT count(*) FROM audit_logs a WHERE a.action='upload' AND NOT a.success AND a.ts >= :start AND a.ts < :end {na}",
        **P,
    )
    awaiting = await scalar(
        db,
        f"SELECT count(*) FROM examinations e WHERE e.deleted_at IS NULL AND e.status::text IN ('queued','processing') {ne}",
        **P,
    )
    return {
        "exams_created_today": today,
        "exams_created_period": period,
        "recordings_uploaded": recs["n"],
        "rejected_recordings": rejected,
        "avg_recording_quality": round(float(recs["q"]), 2) if recs["q"] is not None else None,
        "awaiting_ai": awaiting,
    }

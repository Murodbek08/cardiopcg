"""Adapter: real engine (app.ml + app.services.ai) -> backend ``AnalysisService`` port.

The engine analyses ONE recording at a time and takes a de-identified context dict. This adapter:
  1. runs the signal pipeline per recording (AI stages OFF),
  2. aggregates sites by the worst abnormal probability (``worst_site``),
  3. runs the AI stages (DeepSeek assessment + KB-grounded drug proposals) ONCE on the worst site,
     with ``options.ai_consent`` taken from ``patients.ai_consent``,
  4. maps everything into the backend DTOs (SignalAnalysis / AiReportData / DrugSuggestion).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.ml import AudioError
from app.ml.schemas import PcgAnalysisResult
from app.services.ai import AnalysisOptions as EngineOptions
from app.services.ai import AnalysisOutput
from app.services.ai import get_analysis_service as get_engine
from app.services.analysis_port import (
    AiReportData,
    AnalysisError,
    AnalysisOutcome,
    AnalysisRequest,
    DrugSuggestion,
    PatientContext,
    ProgressCallback,
    RecordingArtifacts,
    ReportOutcome,
    ReportRequest,
    SegmentOut,
    SignalAnalysis,
    TransientAnalysisError,
)

log = structlog.get_logger()
_GRADE = {"1-2": 2, "3": 3, ">=4": 4}
_ROUTE = {"po": "oral", "iv": "iv", "im": "im", "sc": "sc"}


def engine_context(p: PatientContext) -> dict[str, Any]:
    """PatientContext (already de-identified) -> engine context dict (engine re-validates via allow-list)."""
    v = p.vitals
    ctx: dict[str, Any] = {
        "age_years": p.age_years,
        "sex": p.gender,
        "height_cm": p.height_cm,
        "weight_kg": p.weight_kg,
        "bmi": p.bmi,
        "symptoms": [*p.symptoms, *([p.complaints] if p.complaints else [])],
        "history": [h["title"] for h in p.history if h.get("title")],
        "known_conditions_icd10": [h["icd10_code"] for h in p.history if h.get("icd10_code")],
        "vitals": {
            k: v[src]
            for k, src in (
                ("bp_sys", "bp_systolic"),
                ("bp_dia", "bp_diastolic"),
                ("spo2", "spo2_pct"),
                ("temp_c", "temperature_c"),
                ("hr_bpm", "heart_rate_bpm"),
            )
            if src in v
        },
        "allergies": [a["substance"] for a in p.allergies if a.get("substance")],
        "current_medications": [
            {
                "inn": m.get("inn_code") or m["drug_name"],
                **({"freq": m["frequency"]} if m.get("frequency") else {}),
            }
            for m in p.medications
            if m.get("drug_name")
        ],
    }
    return {k: val for k, val in ctx.items() if val not in (None, [], {})}


def _classify(pcg: PcgAnalysisResult) -> tuple[str, float, dict[str, float]]:
    if pcg.status == "rejected_low_quality" or (pcg.quality and pcg.quality.level == "unusable"):
        return "artifact", 0.0, {"normal": 0.0, "murmur": 0.0, "extra_heart_sound": 0.0, "artifact": 1.0}
    cls = pcg.classification
    p_ab = cls.probability_abnormal if cls and cls.probability_abnormal is not None else None
    if cls is None or cls.outcome == "undetermined" or p_ab is None:
        return "undetermined", 0.0, {"normal": 0.0, "murmur": 0.0, "extra_heart_sound": 0.0, "artifact": 0.0}
    extra = any(e.present for e in pcg.extra_sounds if e.type in ("s3", "s4"))
    murmur = bool(pcg.murmur and pcg.murmur.present)
    probs = {"normal": round(1 - p_ab, 4), "murmur": 0.0, "extra_heart_sound": 0.0, "artifact": 0.0}
    if cls.outcome == "abnormal":
        key = "murmur" if murmur or not extra else "extra_heart_sound"
        probs[key] = round(p_ab, 4)
        return key, max(p_ab, 1 - p_ab), probs
    return "normal", max(p_ab, 1 - p_ab), probs


def _severity(pcg: PcgAnalysisResult, pcg_class: str) -> str:
    if pcg_class in ("normal", "undetermined", "artifact"):
        return "none"
    m = pcg.murmur
    grades = [
        g
        for g in (
            m.systolic.grade_est if m and m.systolic else None,
            m.diastolic.grade_est if m and m.diastolic else None,
        )
        if g
    ]
    if ">=4" in grades:
        return "severe"
    if "3" in grades:
        return "moderate"
    return "mild"


def _timing(pcg: PcgAnalysisResult) -> str:
    m = pcg.murmur
    s = bool(m and m.systolic and m.systolic.present)
    d = bool(m and m.diastolic and m.diastolic.present)
    return "continuous" if s and d else "systolic" if s else "diastolic" if d else "none"


def _abn(pcg: PcgAnalysisResult) -> float:
    c = pcg.classification
    return (c.probability_abnormal or 0.0) if c else 0.0


def map_signal(
    per_rec: list[tuple[Any, PcgAnalysisResult, dict[str, bytes]]],
    worst: int,
    model_version: str,
    processing_ms: int | None,
) -> SignalAnalysis:
    rinp, pcg, _ = per_rec[worst]
    pcg_class, conf, probs = _classify(pcg)
    m = pcg.murmur
    sysm = m.systolic if m else None
    dia = m.diastolic if m else None
    shape_src = sysm if sysm and sysm.present else dia
    rr_ms = 60000 / pcg.rhythm.hr_bpm if pcg.rhythm and pcg.rhythm.hr_bpm else None
    seg_rows: list[SegmentOut] = []
    recs: list[RecordingArtifacts] = []
    for r, p, arts in per_rec:
        for row in p.to_segment_rows():
            seg_rows.append(
                SegmentOut(
                    recording_id=r.recording_id,
                    type=row["type"],
                    start_ms=row["start_ms"],
                    end_ms=row["end_ms"],
                    cycle_no=row.get("cycle_no"),
                    confidence=row.get("confidence"),
                )
            )
        c, cf, _ = _classify(p)
        peaks = None
        if "wave_peaks.json" in arts:
            raw = json.loads(arts["wave_peaks.json"])
            n = len(raw["peaks"]) // 2
            peaks = {
                "format": "minmax-interleaved",
                "channels": 1,
                "sample_rate": raw["sample_rate"],
                "samples_per_pixel": max(int(raw["duration_s"] * raw["sample_rate"] / max(n, 1)), 1),
                "length": n,
                "duration_sec": raw["duration_s"],
                "data": raw["peaks"],
                "peaks": raw["peaks"],
            }
        recs.append(
            RecordingArtifacts(
                recording_id=r.recording_id,
                pcg_class=c,
                confidence=round(cf, 3),
                snr_db=round(p.quality.components.snr_db, 2) if p.quality else None,
                quality_score=round(min(max(p.quality.sqi, 0.0), 1.0), 3) if p.quality else None,
                spectrogram_png=arts.get("spectrogram.png"),
                waveform_peaks=peaks,
                extra={
                    "site": r.site,
                    "sqi": p.quality.sqi if p.quality else None,
                    "status": p.status,
                    "abnormal_probability": _abn(p),
                },
            )
        )
    q = pcg.quality
    feats: dict[str, Any] = {k: v for k, v in pcg.features.items() if v is not None}
    feats["pcg_result"] = json.loads(
        pcg.model_dump_json()
    )  # worst-site engine result (used by report regeneration)
    feats["worst_site_recording_id"] = rinp.recording_id
    seg = pcg.segmentation
    return SignalAnalysis(
        model_version=model_version,
        pcg_class=pcg_class,
        class_probs=probs,
        confidence=round(conf, 3),
        severity=_severity(pcg, pcg_class),
        murmur_timing=_timing(pcg),
        murmur_grade=_GRADE.get(
            (sysm.grade_est if sysm and sysm.present else None) or (dia.grade_est if dia else None) or ""
        ),
        murmur_shape=(shape_src.shape if shape_src and shape_src.shape != "none" else None),
        heart_rate_bpm=pcg.rhythm.hr_bpm if pcg.rhythm else None,
        hr_variability_ms=round(pcg.rhythm.cycle_cv * rr_ms, 2)
        if pcg.rhythm and pcg.rhythm.cycle_cv is not None and rr_ms
        else None,
        s1_count=seg.n_cycles_valid if seg else None,
        s2_count=sum(1 for c_ in seg.cycles if c_.s2_start_s is not None) if seg else None,
        mean_s1_s2_ms=pcg.intervals.systole_ms if pcg.intervals else None,
        mean_s2_s1_ms=pcg.intervals.diastole_ms if pcg.intervals else None,
        systole_ms=pcg.intervals.systole_ms if pcg.intervals else None,
        diastole_ms=pcg.intervals.diastole_ms if pcg.intervals else None,
        dominant_freq_hz=(sysm.f_peak_hz if sysm and sysm.f_peak_hz else (dia.f_peak_hz if dia else None)),
        features=feats,
        quality_ok=bool(q and q.level in ("good", "acceptable") and pcg.status == "ok"),
        quality_notes="; ".join(q.warnings) if q and q.warnings else None,
        processing_ms=processing_ms,
        segments=seg_rows,
        recordings=recs,
    )


def map_ai(out: AnalysisOutput, llm_model: str) -> ReportOutcome:
    ai, drugs = out.ai, out.drugs
    report: AiReportData | None = None
    error: str | None = None
    if ai.assessment is not None and ai.status == "ok":
        a = ai.assessment
        calls = out.ai_calls
        report = AiReportData(
            llm_provider="deepseek" if ai.source == "llm" else "rule_template",
            llm_model=(ai.model or llm_model or "rule_template")[:40],
            prompt_version=(ai.prompt_version or out.prompt_version or "n/a")[:20],
            summary=a.summary_uz,
            findings={
                "signal_interpretation": a.signal_interpretation_uz,
                "risk": a.risk.model_dump(),
                "confidence": a.confidence.model_dump(),
                "missing_information": a.missing_information_uz,
                "source": ai.source,
                "numeric_verified": ai.numeric_verified,
                "low_confidence_mode": ai.low_confidence_mode,
            },
            differential_diagnoses=[
                {
                    "name": d.name_uz,
                    "icd10": None,
                    "condition_code": d.condition_code,
                    "likelihood": "high"
                    if d.probability >= 0.5
                    else "medium"
                    if d.probability >= 0.2
                    else "low",
                    "probability": d.probability,
                    "rationale": "; ".join(d.supporting_findings),
                    "against": d.against_findings,
                }
                for d in a.differential
            ],
            recommended_tests=[t.name_uz for t in a.recommended_tests],
            red_flags=list(a.risk.red_flags),
            patient_friendly_text=None,
            disclaimer=" ".join(out.disclaimers) or a.disclaimer_uz,
            input_snapshot=(
                next(
                    (
                        c.input_payload
                        for c in calls
                        if c.call_type == "clinical_assessment" and c.input_payload
                    ),
                    None,
                )
                or (out.deid.model_dump() if out.deid else {})
            ),
            raw_response=None,
            prompt_tokens=sum(c.tokens_in or 0 for c in calls) or None,
            completion_tokens=sum(c.tokens_out or 0 for c in calls) or None,
            latency_ms=sum(c.latency_ms or 0 for c in calls) or None,
            cost_usd=sum(c.cost_usd or 0 for c in calls) or None,
        )
    else:
        error = ai.message_uz or f"AI holati: {ai.status}"
    sugg: list[DrugSuggestion] = []
    for p in drugs.proposals:
        d = p.dose
        dose = f"{d.min:g} {d.unit}" if d.min == d.max else f"{d.min:g}-{d.max:g} {d.unit}"
        sugg.append(
            DrugSuggestion(
                drug_name=(p.inn_uz or p.inn)[:160],
                inn_code=p.inn,
                atc_code=p.atc_code,
                dose=dose,
                route=_ROUTE.get(d.route, d.route),
                frequency=d.frequency or "-",
                instructions=" ".join(x for x in [d.duration_uz, *p.monitoring_uz] if x) or None,
                rationale=p.indication_uz,
                contraindications=[c.item for c in p.contraindications_checked if c.status != "clear"],
                side_effects=p.adverse_effects_uz,
            )
        )
    return ReportOutcome(report=report, drug_suggestions=sugg, error=error)


class EngineAnalysisService:
    """Backend ``AnalysisService`` implementation backed by app.ml + app.services.ai."""

    def __init__(self, engine: Any | None = None, kb_from_db: bool = True) -> None:
        self.engine = engine or get_engine()
        self.kb_from_db = kb_from_db
        self._kb_stamp: str | None = None
        self._kb_checked = 0.0

    async def _sync_kb(self) -> None:
        """Use the admin-managed DB KB (published => reviewed). Falls back to the engine's YAML KB when the DB is empty."""
        if not self.kb_from_db:
            return
        import time

        if time.monotonic() - self._kb_checked < 15:
            return
        self._kb_checked = time.monotonic()
        try:
            from sqlalchemy import func, select

            from app.db.session import get_sessionmaker
            from app.models.kb import KbDrug
            from app.services import kb_service

            async with get_sessionmaker()() as s:
                if not (await s.execute(select(func.count()).select_from(KbDrug))).scalar_one():
                    return
                kb, stamp = await kb_service.build_engine_kb(s)
            if stamp != self._kb_stamp:
                self.engine.kb = kb
                self._kb_stamp = stamp
                log.info("kb_reloaded_from_db", drugs=len(kb.drugs), version=kb.version)
        except Exception as exc:  # the engine keeps its previous KB
            log.warning("kb_sync_failed", error=str(exc))

    async def analyze(
        self, request: AnalysisRequest, progress: ProgressCallback | None = None
    ) -> AnalysisOutcome:
        async def tick(stage: str, pct: int) -> None:
            if progress:
                await progress(stage, pct)

        await self._sync_kb()
        ctx = engine_context(request.patient)
        per_rec: list[tuple[Any, PcgAnalysisResult, dict[str, bytes]]] = []
        n = max(len(request.recordings), 1)
        await tick("preprocessing", 15)
        for i, r in enumerate(request.recordings):
            opts = EngineOptions(
                source="audio",
                site=r.site if r.site != "other" else "other",
                run_ai=False,
                ai_consent=request.patient.ai_consent,
                user_id=request.user_ref,
                recording_id=r.recording_id,
                analysis_id=request.job_id,
                patient_position=request.patient.patient_position,
            )
            try:
                out = await self.engine.analyze(r.local_path, ctx, opts)
            except AudioError as exc:
                raise AnalysisError(exc.code, exc.message) from exc
            except (OSError, TimeoutError) as exc:
                raise TransientAnalysisError("IO_ERROR", str(exc)) from exc
            per_rec.append((r, out.pcg, out.artifacts))
            await tick("classifying", 15 + int(55 * (i + 1) / n))
        worst = max(range(len(per_rec)), key=lambda i: (per_rec[i][1].status == "ok", _abn(per_rec[i][1])))
        # worst_site = most abnormal among usable recordings; fall back to first when none usable
        if not any(p.status == "ok" for _, p, _ in per_rec):
            worst = 0
        total_ms = sum((p.pipeline.processing_ms or 0) for _, p, _ in per_rec) or None
        await tick("spectrogram", 75)
        signal = map_signal(per_rec, worst, request.options.model_version, total_ms)
        report: ReportOutcome | None = None
        if request.options.llm:
            await tick("llm_report", 85)
            eo = EngineOptions(
                source="audio",
                run_ai=True,
                ai_consent=request.patient.ai_consent,
                user_id=request.user_ref,
                analysis_id=request.job_id,
            )
            ai_out = await self.engine.regenerate_ai(per_rec[worst][1], ctx, eo)
            report = map_ai(ai_out, request.options.llm_model)
            if not request.options.drug_suggestions:
                report.drug_suggestions = []
        return AnalysisOutcome(signal=signal, report=report)

    async def generate_report(self, request: ReportRequest) -> ReportOutcome:
        await self._sync_kb()
        raw = (request.signal.get("features") or {}).get("pcg_result")
        if not raw:
            return ReportOutcome(error="Signal natijasi (pcg_result) saqlanmagan: qayta tahlil qiling")
        pcg = PcgAnalysisResult.model_validate(raw)
        eo = EngineOptions(
            source="audio", run_ai=True, ai_consent=request.patient.ai_consent, user_id=request.user_ref
        )
        out = await self.engine.regenerate_ai(pcg, engine_context(request.patient), eo)
        res = map_ai(out, request.options.llm_model)
        if not request.want_drugs:
            res.drug_suggestions = []
        return res


def build() -> EngineAnalysisService:
    return EngineAnalysisService()

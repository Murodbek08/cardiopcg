"""Guards and deterministic fallback for the clinical assessment (doc 02 sections 12.5, 16)."""

from __future__ import annotations

import re
from typing import Any

from app.ml.schemas import PcgAnalysisResult

from .deidentify import DeidFlags, _mask_pii, scan_pii
from .prompts import ASSESSMENT_DISCLAIMER_UZ
from .schemas import ClinicalAssessment, ConfidenceInfo, DifferentialItem, RecommendedTest, RiskInfo

_HR_RX = re.compile(r"(\d{2,3}(?:[.,]\d+)?)\s*(?:bpm|ur/daq|urish/daq|marta/daq)", re.I)
_MS_RX = re.compile(r"(\d{2,4}(?:[.,]\d+)?)\s*(?:ms|millisekund)", re.I)
NUMERIC_TOL = 0.05


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _walk_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _mask_obj(obj: Any, flags: DeidFlags) -> Any:
    if isinstance(obj, str):
        return _mask_pii(obj, flags)
    if isinstance(obj, dict):
        return {k: _mask_obj(v, flags) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_obj(v, flags) for v in obj]
    return obj


def numeric_mismatches(a: ClinicalAssessment, pcg: PcgAnalysisResult) -> list[str]:
    """Numbers the LLM quotes (HR / ms intervals) must match the input within 5%."""
    out: list[str] = []
    text = f"{a.summary_uz} {a.signal_interpretation_uz} {a.reasoning_uz}"
    hr = pcg.rhythm.hr_bpm if pcg.rhythm else None
    known_ms = (
        [
            v
            for v in (
                pcg.intervals.systole_ms,
                pcg.intervals.diastole_ms,
                pcg.intervals.s1_dur_ms,
                pcg.intervals.s2_dur_ms,
                pcg.intervals.systole_corr_ms,
            )
            if v is not None
        ]
        if pcg.intervals
        else []
    )
    for m in _HR_RX.finditer(text):
        v = _f(m.group(1))
        if hr is None or abs(v - hr) > max(NUMERIC_TOL * hr, 3.0):
            out.append(f"numeric_mismatch:hr={v:g}")
    for m in _MS_RX.finditer(text):
        v = _f(m.group(1))
        if not known_ms or all(abs(v - k) > NUMERIC_TOL * k for k in known_ms):
            out.append(f"numeric_mismatch:ms={v:g}")
    return out


def guard_assessment(
    a: ClinicalAssessment, pcg: PcgAnalysisResult, *, low_confidence: bool
) -> tuple[ClinicalAssessment, list[str], bool]:
    """Returns (assessment, guard_events, numeric_verified)."""
    events: list[str] = []
    # PII echoed by the LLM -> mask
    if any(scan_pii(s) for s in _walk_strings(a.model_dump())):
        events.append("pii_in_output_masked")
        a = ClinicalAssessment.model_validate(_mask_obj(a.model_dump(), DeidFlags()))
    mism = numeric_mismatches(a, pcg)
    verified = not mism
    if mism:
        events.extend(mism)
        lf = list(a.confidence.limiting_factors)
        lf.append("AI matnidagi raqamlar kirish qiymatlariga mos kelmadi (tekshirilmagan)")
        a = a.model_copy(update={"confidence": a.confidence.model_copy(update={"limiting_factors": lf[:12]})})
    if low_confidence and a.confidence.overall > 0.7:
        events.append("confidence_capped")
        a = a.model_copy(update={"confidence": a.confidence.model_copy(update={"overall": 0.7})})
    if ASSESSMENT_DISCLAIMER_UZ not in a.disclaimer_uz:
        a = a.model_copy(
            update={"disclaimer_uz": (a.disclaimer_uz + " " + ASSESSMENT_DISCLAIMER_UZ).strip()[:800]}
        )
    return a, events, verified


def template_assessment(pcg: PcgAnalysisResult) -> ClinicalAssessment:
    """Deterministic rule-template text (source = rule_template). No differential guesses, no drugs."""
    parts: list[str] = []
    tests: list[RecommendedTest] = []
    m = pcg.murmur
    r = pcg.rhythm
    if r and r.hr_bpm is not None:
        parts.append(f"Yurak urish chastotasi taxminan {r.hr_bpm:.0f} bpm ({r.category}).")
    if m and m.present:
        kinds = []
        if m.systolic and m.systolic.present:
            kinds.append(f"sistolik ({m.systolic.timing})")
        if m.diastolic and m.diastolic.present:
            kinds.append(f"diastolik ({m.diastolic.timing})")
        parts.append(f"{' va '.join(kinds)} shovqin aniqlandi; ekokardiografiya tavsiya etiladi.")
        tests.append(
            RecommendedTest(
                test="echo",
                priority="high",
                name_uz="Transtorakal ekokardiografiya",
                reason_uz="Signalda shovqin belgisi aniqlandi",
                labs=[],
            )
        )
    elif m and m.present is False:
        parts.append("Aniq shovqin belgisi aniqlanmadi (qoidaga asoslangan baholash).")
    if r and (r.rhythm_irregular or r.category == "irregular"):
        parts.append("Ritm notekis (taxminan); EKG tavsiya etiladi.")
        tests.append(
            RecommendedTest(
                test="ecg",
                priority="high",
                name_uz="12 ulanishli EKG",
                reason_uz="Ritm notekisligi belgisi",
                labs=[],
            )
        )
    if not parts:
        parts.append("Signaldan yetarli xulosa chiqarib bo'lmadi.")
    if not tests:
        tests.append(
            RecommendedTest(
                test="repeat_pcg",
                priority="routine",
                name_uz="PCG ni qayta yozish",
                reason_uz="Natijani tasdiqlash uchun",
                labs=[],
            )
        )
    level = "moderate" if (m and m.present) else "low"
    return ClinicalAssessment(
        summary_uz=" ".join(parts),
        signal_interpretation_uz="Bu matn AI xizmati ishlamaganda signal xususiyatlaridan qoidalar asosida avtomatik tuzilgan shablon.",
        differential=[
            DifferentialItem(
                condition_code="other_undetermined",
                name_uz="Aniqlanmagan (shablon, tashxis emas)",
                probability=1.0,
                supporting_findings=[],
                against_findings=[],
            )
        ],
        risk=RiskInfo(
            level=level,
            rationale_uz="Klinik kontekst baholanmagan; faqat signal xususiyatlari asosida.",
            red_flags=[],
        ),
        recommended_tests=tests,
        missing_information_uz=["AI klinik izohi mavjud emas: keyinroq qayta urinib ko'ring"],
        confidence=ConfidenceInfo(overall=0.2, limiting_factors=["rule_template", "AI xizmati ishlamadi"]),
        reasoning_uz="Deterministik shablon: signal xususiyatlari qoidalarga solishtirildi. Differensial tashxis va dori taklifi berilmadi.",
        disclaimer_uz=ASSESSMENT_DISCLAIMER_UZ,
    )

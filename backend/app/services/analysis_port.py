"""Port (interface) between the backend core and the signal-processing / AI implementation.

The backend core (jobs, API, persistence, events) only talks to ``AnalysisService``. The concrete
implementation lives in ``app/ml`` + ``app/services/ai`` (built by another team) and is loaded by dotted
path from ``ANALYSIS_SERVICE_IMPL`` (``"package.module:factory"``; ``factory()`` returns an
``AnalysisService``). A fake implementation exists only in ``tests/``.

Contract highlights
-------------------
* The service receives LOCAL audio paths (the core downloads them from storage) and a **de-identified**
  patient context. No name/phone/address/national id is ever part of ``AnalysisRequest``.
* ``analyze`` must call ``progress(stage, pct)`` between stages (stage names: validating, preprocessing,
  segmenting, features, classifying, spectrogram, llm_report, finalizing).
* Deterministic failures (corrupt audio ...) -> raise ``AnalysisError(code, message)``;
  transient ones (network, timeouts) -> raise ``TransientAnalysisError`` (core retries with backoff).
* LLM problems must NOT raise: return ``AnalysisOutcome.report=None`` and ``report_error``.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings

PROGRESS_STAGES = (
    "validating",
    "preprocessing",
    "segmenting",
    "features",
    "classifying",
    "spectrogram",
    "llm_report",
    "finalizing",
)

ProgressCallback = Callable[[str, int], Awaitable[None]]


class AnalysisError(Exception):
    """Deterministic failure: job goes straight to `failed` (no retry)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class TransientAnalysisError(AnalysisError):
    """Retryable failure (backoff, up to max_attempts)."""

    def __init__(self, code: str = "TRANSIENT", message: str = "") -> None:
        super().__init__(code, message)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------- inputs
class PatientContext(_M):
    """De-identified clinical context (the ONLY patient data that may reach the AI layer)."""

    age_years: int | None = None
    gender: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    bmi: float | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)  # {kind,title,icd10_code,is_active}
    allergies: list[dict[str, Any]] = Field(
        default_factory=list
    )  # {substance,substance_code,severity,reaction}
    medications: list[dict[str, Any]] = Field(default_factory=list)  # {drug_name,inn_code,dose,frequency}
    vitals: dict[str, Any] = Field(default_factory=dict)
    complaints: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    patient_position: str | None = None
    priority: str | None = None
    ai_consent: bool = False  # patients.ai_consent: no external AI call without it


class RecordingInput(_M):
    recording_id: str
    site: str
    local_path: str
    ext: str
    duration_sec: float | None = None
    sample_rate_hz: int | None = None
    snr_db: float | None = None


class AnalysisOptions(_M):
    llm: bool = True
    drug_suggestions: bool = True
    llm_model: str = "deepseek-chat"
    model_version: str = "pcg-cnn-1.0.0"


class AnalysisRequest(_M):
    examination_id: str
    job_id: str
    exam_no: str
    recordings: list[RecordingInput]
    user_ref: str | None = None  # opaque id (rate limiting only)
    patient: PatientContext
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    def local_paths(self) -> list[Path]:
        return [Path(r.local_path) for r in self.recordings]


# -------------------------------------------------------------------------------------- outputs
class SegmentOut(_M):
    recording_id: str
    type: str  # S1,S2,S3,S4,systole,diastole,murmur,click,noise
    start_ms: int
    end_ms: int
    cycle_no: int | None = None
    peak_amplitude: float | None = None
    energy: float | None = None
    dominant_freq_hz: float | None = None
    confidence: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RecordingArtifacts(_M):
    recording_id: str
    pcg_class: str | None = None
    confidence: float | None = None
    snr_db: float | None = None
    quality_score: float | None = None
    spectrogram_png: bytes | None = None
    waveform_peaks: dict[str, Any] | None = None  # {"sample_rate":..,"samples_per_pixel":..,"data":[..]}
    extra: dict[str, Any] = Field(default_factory=dict)


class SignalAnalysis(_M):
    model_version: str
    pcg_class: str  # normal|murmur|extra_heart_sound|artifact|undetermined
    class_probs: dict[str, float]
    confidence: float
    severity: str = "none"
    murmur_timing: str = "none"
    murmur_grade: int | None = None
    murmur_shape: str | None = None
    heart_rate_bpm: float | None = None
    hr_variability_ms: float | None = None
    s1_count: int | None = None
    s2_count: int | None = None
    mean_s1_s2_ms: float | None = None
    mean_s2_s1_ms: float | None = None
    systole_ms: float | None = None
    diastole_ms: float | None = None
    dominant_freq_hz: float | None = None
    features: dict[str, Any] = Field(default_factory=dict)
    quality_ok: bool = True
    quality_notes: str | None = None
    processing_ms: int | None = None
    segments: list[SegmentOut] = Field(default_factory=list)
    recordings: list[RecordingArtifacts] = Field(default_factory=list)


class AiReportData(_M):
    llm_provider: str = "deepseek"
    llm_model: str
    prompt_version: str
    summary: str
    findings: dict[str, Any] = Field(default_factory=dict)
    differential_diagnoses: list[dict[str, Any]] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    patient_friendly_text: str | None = None
    disclaimer: str
    input_snapshot: dict[str, Any] = Field(default_factory=dict)  # de-identified LLM input
    raw_response: dict[str, Any] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None


class DrugSuggestion(_M):
    drug_name: str
    inn_code: str | None = None
    atc_code: str | None = None
    dose: str
    route: str = "oral"
    frequency: str
    duration_days: int | None = None
    instructions: str | None = None
    rationale: str | None = None
    contraindications: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)


class ReportOutcome(_M):
    report: AiReportData | None = None
    drug_suggestions: list[DrugSuggestion] = Field(default_factory=list)
    error: str | None = None


class AnalysisOutcome(_M):
    signal: SignalAnalysis
    report: ReportOutcome | None = None  # None when LLM disabled


class ReportRequest(_M):
    """Regenerate only the LLM part (report + drug suggestions) from a stored signal analysis."""

    examination_id: str
    exam_no: str
    patient: PatientContext
    signal: dict[str, Any]  # serialized current analysis_results row (+ per-recording features)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    user_ref: str | None = None
    want_report: bool = True
    want_drugs: bool = True


@runtime_checkable
class AnalysisService(Protocol):
    async def analyze(
        self, request: AnalysisRequest, progress: ProgressCallback | None = None
    ) -> AnalysisOutcome: ...

    async def generate_report(self, request: ReportRequest) -> ReportOutcome: ...


class UnavailableAnalysisService:
    """Default when no implementation is configured: jobs fail with a clear error code."""

    async def analyze(
        self, request: AnalysisRequest, progress: ProgressCallback | None = None
    ) -> AnalysisOutcome:
        raise AnalysisError("ANALYSIS_NOT_CONFIGURED", "Tahlil xizmati sozlanmagan (ANALYSIS_SERVICE_IMPL)")

    async def generate_report(self, request: ReportRequest) -> ReportOutcome:
        return ReportOutcome(error="Tahlil xizmati sozlanmagan (ANALYSIS_SERVICE_IMPL)")


_override: AnalysisService | None = None
_cached: AnalysisService | None = None


def set_analysis_service(svc: AnalysisService | None) -> None:
    """Dependency-injection hook (tests / embedding)."""
    global _override
    _override = svc


def get_analysis_service() -> AnalysisService:
    global _cached
    if _override is not None:
        return _override
    if _cached is None:
        path = get_settings().analysis_service_impl
        if not path:
            _cached = UnavailableAnalysisService()
        else:
            module_name, _, attr = path.partition(":")
            factory = getattr(importlib.import_module(module_name), attr or "build")
            _cached = factory()
    return _cached

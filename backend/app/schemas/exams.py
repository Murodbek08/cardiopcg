from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.models.enums import (
    AuscultationSite,
    ExamPriority,
    ExamStatus,
    PatientPosition,
    RecordingKind,
    RecordingStatus,
)
from app.schemas.common import Out, Strict
from app.schemas.patients import DoctorBrief

KNOWN_SYMPTOMS = {
    "dyspnea",
    "chest_pain",
    "palpitations",
    "syncope",
    "edema",
    "fatigue",
    "dizziness",
    "cough",
    "fever",
    "orthopnea",
    "other",
}


class _Vitals(Strict):
    heart_rate_bpm: int | None = Field(default=None, ge=20, le=300)
    bp_systolic: int | None = Field(default=None, ge=40, le=300)
    bp_diastolic: int | None = Field(default=None, ge=20, le=200)
    spo2_pct: int | None = Field(default=None, ge=50, le=100)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    weight_kg_at_exam: float | None = Field(default=None, ge=1, le=400)

    @model_validator(mode="after")
    def _bp(self):
        if (
            self.bp_systolic is not None
            and self.bp_diastolic is not None
            and self.bp_systolic <= self.bp_diastolic
        ):
            raise ValueError("Sistolik bosim diastolikdan yuqori bo'lishi kerak")
        return self


class ExamCreate(_Vitals):
    patient_id: UUID
    priority: ExamPriority = ExamPriority.routine
    complaints: str | None = Field(default=None, max_length=5000)
    symptoms: list[str] = Field(default_factory=list, max_length=20)
    patient_position: PatientPosition | None = None
    assigned_doctor_id: UUID | None = None

    @model_validator(mode="after")
    def _sym(self):
        bad = [s for s in self.symptoms if s not in KNOWN_SYMPTOMS]
        if bad:
            raise ValueError(f"Noma'lum simptomlar: {bad}")
        return self


class ExamUpdate(_Vitals):
    priority: ExamPriority | None = None
    complaints: str | None = Field(default=None, max_length=5000)
    symptoms: list[str] | None = Field(default=None, max_length=20)
    patient_position: PatientPosition | None = None
    assigned_doctor_id: UUID | None = None


class AssignIn(Strict):
    doctor_id: UUID


class CancelIn(Strict):
    reason: str = Field(min_length=1, max_length=1000)


class AnalyzeIn(Strict):
    force_rerun: bool = False
    llm: bool = True
    drug_suggestions: bool = True


class ExamListItem(Out):
    id: UUID
    exam_no: str
    patient: dict[str, Any]
    status: ExamStatus
    priority: ExamPriority
    examined_at: datetime
    assigned_doctor: DoctorBrief | None = None
    performed_by: DoctorBrief
    recording_count: int
    ai: dict[str, Any] | None = None
    conclusion_status: str | None = None


class RecordingOut(Out):
    id: UUID
    examination_id: UUID
    kind: RecordingKind
    site: AuscultationSite | None = None
    status: RecordingStatus
    original_filename: str
    mime_type: str
    ext: str
    size_bytes: int
    sha256: str
    duration_sec: float | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    codec: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    snr_db: float | None = None
    quality_score: float | None = None
    validation_report: dict[str, Any] = {}
    scan_status: str
    notes: str | None = None
    derived_from_id: UUID | None = None
    url: str
    created_at: datetime


class RecordingPatch(Strict):
    site: AuscultationSite


class AnalysisOut(Out):
    id: UUID
    model_version: str
    pcg_class: str
    class_probs: dict[str, float]
    confidence: float
    severity: str
    murmur_timing: str
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
    quality_ok: bool
    quality_notes: str | None = None
    processing_ms: int | None = None
    is_current: bool = True
    recordings: list[dict[str, Any]] = []
    created_at: datetime


class SegmentOut(Out):
    id: UUID
    recording_id: UUID
    seq: int
    type: str
    start_ms: int
    end_ms: int
    cycle_no: int | None = None
    peak_amplitude: float | None = None
    energy: float | None = None
    dominant_freq_hz: float | None = None
    confidence: float | None = None


class AiReportOut(Out):
    id: UUID
    status: str
    llm_model: str
    prompt_version: str
    summary: str
    findings: dict[str, Any]
    differential_diagnoses: list[dict[str, Any]]
    recommended_tests: list[str]
    red_flags: list[str]
    patient_friendly_text: str | None = None
    disclaimer: str
    error_message: str | None = None
    created_at: datetime


class AiReportOutNurse(Out):
    """Nurse view: no differential, no patient text, no drugs; red flags visible."""

    id: UUID
    status: str
    summary: str
    findings: dict[str, Any]
    red_flags: list[str]
    disclaimer: str
    created_at: datetime


class JobOut(Out):
    id: UUID
    status: str
    stage: str
    progress_pct: int
    attempt: int
    started_at: datetime | None = None
    error_code: str | None = None


class StatusOut(Out):
    status: ExamStatus
    job: JobOut | None = None
    history: list[dict[str, Any]]


class AnalyzeAccepted(Out):
    job_id: UUID
    status: str
    exam_status: str
    events: str


class ExamDetail(Out):
    id: UUID
    exam_no: str
    status: ExamStatus
    priority: ExamPriority
    patient: dict[str, Any]
    performed_by: DoctorBrief
    assigned_doctor: DoctorBrief | None = None
    examined_at: datetime
    complaints: str | None = None
    symptoms: list[str] = []
    patient_position: PatientPosition | None = None
    heart_rate_bpm: int | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    spo2_pct: int | None = None
    temperature_c: float | None = None
    weight_kg_at_exam: float | None = None
    ai_requested_at: datetime | None = None
    ai_completed_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_reason: str | None = None
    failure_reason: str | None = None
    version: int
    recordings: list[RecordingOut] = []
    analysis: AnalysisOut | None = None
    report: dict[str, Any] | None = None
    prescription: dict[str, Any] | None = None
    conclusion: dict[str, Any] | None = None
    status_history: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime


class ExamDetailNurse(ExamDetail):
    """Same shape; ``prescription`` is always null and ``report`` is the restricted variant."""

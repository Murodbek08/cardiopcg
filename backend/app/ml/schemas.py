"""Pydantic result schema `pcg-analysis/1.0` (doc 02, section 11).

Defined here (not in app/schemas) because this package owns the pipeline; the backend may
re-export it. All enums are strict `Literal`s.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import SCHEMA_VERSION

Status = Literal["ok", "low_quality_partial", "rejected_low_quality", "error"]
QualityLevel = Literal["good", "acceptable", "poor", "unusable"]
Source = Literal["audio", "image"]
RhythmCategory = Literal["normal", "bradycardia", "tachycardia", "irregular", "undetermined"]
MurmurTiming = Literal[
    "none",
    "early_sys",
    "mid_sys",
    "late_sys",
    "holosystolic",
    "early_dia",
    "mid_dia",
    "late_dia",
    "holodiastolic",
    "continuous",
]
MurmurShape = Literal["none", "crescendo", "decrescendo", "crescendo_decrescendo", "plateau"]
Outcome = Literal["normal", "abnormal", "undetermined"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MlModelRef(_M):
    name: str
    version: str
    sha256: str | None = None


class PipelineInfo(_M):
    preprocess_version: str
    segmentation_method: str
    ml_models: list[MlModelRef] = Field(default_factory=list)
    ml_available: bool = False
    duration_s: float
    sample_rate_hz: int
    sample_rate_orig_hz: int | None = None
    rule_version: str = "murmur_rule_v1"
    window_start_s: float = 0.0
    processing_ms: int | None = None


class QualityComponents(_M):
    snr_db: float
    q_snr: float
    q_period: float
    q_cycles: float
    q_art: float
    q_clip: float
    q_spec: float
    artifact_ratio: float
    clip_ratio: float


class Quality(_M):
    sqi: float
    level: QualityLevel
    components: QualityComponents
    warnings: list[str] = Field(default_factory=list)


class Rhythm(_M):
    hr_bpm: float | None = None
    hr_std: float | None = None
    hr_min: float | None = None
    hr_max: float | None = None
    rhythm_irregular: bool = False
    cycle_cv: float | None = None
    category: RhythmCategory = "undetermined"


class CycleOut(_M):
    idx: int
    s1_start_s: float
    s1_end_s: float
    s2_start_s: float | None = None
    s2_end_s: float | None = None
    next_s1_start_s: float | None = None
    valid: bool


class SegmentationOut(_M):
    method: str
    n_cycles_detected: int
    n_cycles_valid: int
    confidence: float
    cycles: list[CycleOut] = Field(default_factory=list)


class Intervals(_M):
    systole_ms: float | None = None
    diastole_ms: float | None = None
    sd_ratio: float | None = None
    sys_frac: float | None = None
    systole_corr_ms: float | None = None
    s1_dur_ms: float | None = None
    s2_dur_ms: float | None = None


class ExtraSound(_M):
    type: Literal["s3", "s4", "s2_split_candidate", "click"]
    present: bool
    confidence: float


class SystolicMurmur(_M):
    present: bool
    timing: MurmurTiming = "none"
    grade_est: Literal["1-2", "3", ">=4"] | None = None
    grade_confidence: float | None = None
    shape: MurmurShape = "none"
    frequency_class: Literal["low", "medium", "high"] | None = None
    f_peak_hz: float | None = None
    f_centroid_hz: float | None = None
    R_sys: float | None = None


class DiastolicMurmur(_M):
    present: bool
    timing: MurmurTiming = "none"
    grade_est: Literal["1-2", "3", ">=4"] | None = None
    shape: MurmurShape = "none"
    frequency_class: Literal["low", "medium", "high"] | None = None
    f_peak_hz: float | None = None
    f_centroid_hz: float | None = None
    R_dia: float | None = None


class LocationHint(_M):
    site: str
    hypothesis: str
    support: float
    evidence: list[str] = Field(default_factory=list)


class Murmur(_M):
    present: bool | None = None  # None = not assessable (blocked by quality / too few cycles)
    probability: float | None = None
    calibrated: bool = False
    systolic: SystolicMurmur | None = None
    diastolic: DiastolicMurmur | None = None
    location_hints: list[LocationHint] = Field(default_factory=list)


class PerModel(_M):
    rule: float | None = None
    gbm: float | None = None
    cnn: float | None = None


class Classification(_M):
    outcome: Outcome = "undetermined"
    probability_abnormal: float | None = None
    uncertainty: float | None = None
    ood_score: float | None = None
    per_model: PerModel = Field(default_factory=PerModel)
    models_disagree: bool = False


class Artifacts(_M):
    waveform_png: str | None = None
    spectrogram_png: str | None = None
    scalogram_png: str | None = None
    envelope_json: str | None = None
    downsampled_wave_json: str | None = None


class PcgAnalysisResult(_M):
    schema_version: str = SCHEMA_VERSION
    analysis_id: str | None = None
    recording_id: str | None = None
    source: Source = "audio"
    status: Status = "ok"
    pipeline: PipelineInfo
    quality: Quality | None = None
    rhythm: Rhythm | None = None
    segmentation: SegmentationOut | None = None
    intervals: Intervals | None = None
    extra_sounds: list[ExtraSound] = Field(default_factory=list)
    murmur: Murmur | None = None
    classification: Classification | None = None
    features: dict[str, float | None] = Field(default_factory=dict)
    feature_flags: dict[str, Any] = Field(default_factory=dict)
    artifacts: Artifacts = Field(default_factory=Artifacts)
    limitations: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # convenience for the backend (`pcg_segments` rows, doc 01 section 1.10)
    def to_segment_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.segmentation:
            return rows
        seq = 0
        for c in self.segmentation.cycles:
            rows.append(
                {
                    "seq": seq,
                    "type": "S1",
                    "start_ms": int(c.s1_start_s * 1000),
                    "end_ms": max(int(c.s1_end_s * 1000), int(c.s1_start_s * 1000) + 1),
                    "cycle_no": c.idx,
                    "confidence": 1.0 if c.valid else 0.4,
                }
            )
            seq += 1
            if c.s2_start_s is not None and c.s2_end_s is not None:
                rows.append(
                    {
                        "seq": seq,
                        "type": "S2",
                        "start_ms": int(c.s2_start_s * 1000),
                        "end_ms": max(int(c.s2_end_s * 1000), int(c.s2_start_s * 1000) + 1),
                        "cycle_no": c.idx,
                        "confidence": 1.0 if c.valid else 0.4,
                    }
                )
                seq += 1
        return rows

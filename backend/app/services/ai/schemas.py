"""Pydantic schemas for the AI layer: LLM I/O (strict, `extra=forbid`) and service output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ml.schemas import PcgAnalysisResult

CONDITION_CODES = (
    "normal_variant",
    "innocent_flow_murmur",
    "aortic_stenosis",
    "aortic_regurgitation",
    "mitral_regurgitation",
    "mitral_stenosis",
    "mitral_valve_prolapse",
    "tricuspid_regurgitation",
    "pulmonic_stenosis",
    "ventricular_septal_defect",
    "atrial_septal_defect",
    "patent_ductus_arteriosus",
    "hypertrophic_cardiomyopathy",
    "heart_failure",
    "infective_endocarditis",
    "rheumatic_heart_disease",
    "pericarditis",
    "arrhythmia_suspected",
    "congenital_heart_disease_other",
    "other_undetermined",
)
ConditionCode = Literal[
    "normal_variant",
    "innocent_flow_murmur",
    "aortic_stenosis",
    "aortic_regurgitation",
    "mitral_regurgitation",
    "mitral_stenosis",
    "mitral_valve_prolapse",
    "tricuspid_regurgitation",
    "pulmonic_stenosis",
    "ventricular_septal_defect",
    "atrial_septal_defect",
    "patent_ductus_arteriosus",
    "hypertrophic_cardiomyopathy",
    "heart_failure",
    "infective_endocarditis",
    "rheumatic_heart_disease",
    "pericarditis",
    "arrhythmia_suspected",
    "congenital_heart_disease_other",
    "other_undetermined",
]
TestCode = Literal[
    "ecg", "echo", "holter", "chest_xray", "lab", "stress_test", "cardiology_referral", "repeat_pcg", "other"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ Call A (clinical assessment)


class DifferentialItem(_Strict):
    condition_code: ConditionCode
    name_uz: str = Field(min_length=1, max_length=200)
    probability: float = Field(ge=0.0, le=1.0)
    supporting_findings: list[str] = Field(default_factory=list, max_length=12)
    against_findings: list[str] = Field(default_factory=list, max_length=12)


class RiskInfo(_Strict):
    level: Literal["low", "moderate", "high", "urgent"]
    rationale_uz: str = Field(max_length=1200)
    red_flags: list[str] = Field(default_factory=list, max_length=12)


class RecommendedTest(_Strict):
    test: TestCode
    priority: Literal["urgent", "high", "routine"]
    name_uz: str = Field(max_length=200)
    reason_uz: str = Field(max_length=600)
    labs: list[str] = Field(default_factory=list, max_length=20)


class ConfidenceInfo(_Strict):
    overall: float = Field(ge=0.0, le=1.0)
    limiting_factors: list[str] = Field(default_factory=list, max_length=12)


class ClinicalAssessment(_Strict):
    summary_uz: str = Field(min_length=1, max_length=1500)
    signal_interpretation_uz: str = Field(max_length=2500)
    differential: list[DifferentialItem] = Field(min_length=1, max_length=12)
    risk: RiskInfo
    recommended_tests: list[RecommendedTest] = Field(default_factory=list, max_length=12)
    missing_information_uz: list[str] = Field(default_factory=list, max_length=12)
    confidence: ConfidenceInfo
    reasoning_uz: str = Field(max_length=4000)
    disclaimer_uz: str = Field(max_length=800)

    @field_validator("differential")
    @classmethod
    def _norm_probs(cls, v: list[DifferentialItem]) -> list[DifferentialItem]:
        """doc 12.4: renormalise to sum 1.0 and sort descending."""
        total = sum(d.probability for d in v)
        if total <= 0:
            raise ValueError("differential probabilities sum to 0")
        out = [d.model_copy(update={"probability": round(d.probability / total, 4)}) for d in v]
        return sorted(out, key=lambda d: d.probability, reverse=True)


# ------------------------------------------------------------------ Call B (drug proposals)


class DoseOut(_Strict):
    min: float = Field(ge=0)
    max: float = Field(ge=0)
    unit: str = Field(max_length=20)
    frequency: str = Field(max_length=120)
    route: Literal["po", "iv", "im", "sc"]
    duration_uz: str = Field(default="", max_length=200)
    adjustment_applied_uz: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _order(self) -> DoseOut:
        if self.max < self.min:
            raise ValueError("dose.max < dose.min")
        return self


class ContraCheck(_Strict):
    item: str = Field(max_length=200)
    status: Literal["clear", "caution", "blocked"]


class InteractionCheck(_Strict):
    with_: str = Field(alias="with", max_length=200)
    severity: Literal["none", "minor", "moderate", "major", "contraindicated"]
    note_uz: str = Field(default="", max_length=400)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AllergyCheck(_Strict):
    status: Literal["clear", "cross_reactivity_possible", "blocked"]
    note_uz: str = Field(default="", max_length=400)


class LLMDrugProposal(_Strict):
    drug_id: str = Field(max_length=80)
    inn: str = Field(max_length=120)
    class_: str = Field(alias="class", max_length=80)
    indication_uz: str = Field(max_length=600)
    linked_condition_codes: list[str] = Field(default_factory=list, max_length=8)
    dose: DoseOut
    contraindications_checked: list[ContraCheck] = Field(default_factory=list, max_length=20)
    interactions_checked: list[InteractionCheck] = Field(default_factory=list, max_length=20)
    allergy_check: AllergyCheck
    monitoring_uz: list[str] = Field(default_factory=list, max_length=12)
    adverse_effects_uz: list[str] = Field(default_factory=list, max_length=12)
    evidence_level: Literal["guideline", "expert", "limited"]
    confidence: float = Field(ge=0.0, le=1.0)
    requires_doctor_approval: bool = True

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ExcludedDrug(_Strict):
    drug_id: str = Field(max_length=80)
    reason_uz: str = Field(max_length=500)


class LLMDrugProposals(_Strict):
    proposals: list[LLMDrugProposal] = Field(default_factory=list, max_length=8)
    excluded: list[ExcludedDrug] = Field(default_factory=list, max_length=30)
    non_drug_measures_uz: list[str] = Field(default_factory=list, max_length=12)
    disclaimer_uz: str = Field(default="", max_length=800)


# ------------------------------------------------------------------ service output

AiStatus = Literal[
    "ok",
    "unavailable",
    "skipped",
    "blocked_low_quality",
    "consent_missing",
    "rate_limited",
    "budget_exceeded",
]


class AiCallRecord(BaseModel):
    """One AI call, shaped for `ai_audit_log` (doc 17). No key, no raw PII."""

    call_type: Literal["clinical_assessment", "drug_proposals", "repair"]
    provider: str = "deepseek"
    model: str
    prompt_version: str
    kb_version: int | None = None
    input_hash: str
    input_fields: list[str] = Field(default_factory=list)
    output_hash: str | None = None
    cache_hit: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    status: Literal["ok", "schema_error", "timeout", "rate_limited", "budget", "fallback", "error"]
    validation: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    # encrypted by the backend before persisting (doc 17); plain here because it is already de-identified
    input_payload: dict[str, Any] | None = None
    output_raw: str | None = None


class AiAssessmentResult(BaseModel):
    status: AiStatus
    source: Literal["llm", "rule_template", "none"] = "none"
    assessment: ClinicalAssessment | None = None
    model: str | None = None
    prompt_version: str | None = None
    numeric_verified: bool | None = None
    guard_events: list[str] = Field(default_factory=list)
    low_confidence_mode: bool = False
    cache_hit: bool = False
    message_uz: str | None = None


class DrugProposal(BaseModel):
    """Validated, KB-grounded proposal. ALWAYS draft until a doctor approves (doc 15.5)."""

    status: Literal["draft"] = "draft"
    drug_id: str
    inn: str
    inn_uz: str | None = None
    atc_code: str | None = None
    drug_class: str
    class_group: str | None = None
    indication_uz: str
    linked_condition_codes: list[str] = Field(default_factory=list)
    dose: DoseOut
    kb_allowed_range: dict[str, Any] = Field(default_factory=dict)
    contraindications_checked: list[ContraCheck] = Field(default_factory=list)
    interactions_checked: list[InteractionCheck] = Field(default_factory=list)
    allergy_check: AllergyCheck
    monitoring_uz: list[str] = Field(default_factory=list)
    adverse_effects_uz: list[str] = Field(default_factory=list)
    evidence_level: Literal["guideline", "expert", "limited"]
    confidence: float
    low_confidence: bool = False
    requires_doctor_approval: Literal[True] = True
    kb_status: str = "draft"
    kb_version: int = 1
    sources: list[dict[str, Any]] = Field(default_factory=list)
    warnings_uz: list[str] = Field(default_factory=list)


class BlockedDrug(BaseModel):
    drug_id: str
    reasons: list[str]
    source: Literal["kb_filter", "llm_excluded", "guard"] = "kb_filter"


class DrugProposalsResult(BaseModel):
    status: AiStatus
    proposals: list[DrugProposal] = Field(default_factory=list)
    excluded: list[BlockedDrug] = Field(default_factory=list)
    non_drug_measures_uz: list[str] = Field(default_factory=list)
    kb_version: int | None = None
    kb_status_note: str | None = None
    guard_events: list[str] = Field(default_factory=list)
    message_uz: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    cache_hit: bool = False


class DeidInfo(BaseModel):
    input_hash: str
    input_fields: list[str]
    dropped_fields: list[str]
    flags: dict[str, Any]
    request_ref: str


class AnalysisOptions(BaseModel):
    """Per-call options. `ai_consent` must be set by the backend from `patients.ai_consent`."""

    source: Literal["audio", "image"] = "audio"
    site: Literal["aortic", "pulmonic", "erb", "tricuspid", "mitral", "apex", "carotid", "other"] | None = (
        None
    )
    patient_position: str | None = None
    respiration: str | None = None
    run_ai: bool = True
    ai_consent: bool = True
    user_id: str | None = None  # opaque id for rate limiting (never sent to the LLM)
    paper_speed_mm_s: float = 25.0
    px_per_mm: float | None = None
    image_roi: tuple[int, int, int, int] | None = None
    recording_id: str | None = None
    analysis_id: str | None = None


class AnalysisOutput(BaseModel):
    pcg: PcgAnalysisResult
    artifacts: dict[str, bytes] = Field(default_factory=dict, exclude=True)
    ai: AiAssessmentResult
    drugs: DrugProposalsResult
    disclaimers: list[str] = Field(default_factory=list)
    deid: DeidInfo | None = None
    ai_calls: list[AiCallRecord] = Field(default_factory=list)
    kb_version: int | None = None
    prompt_version: str | None = None

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.models.enums import AgreementLevel, ConclusionStatus, PcgClass, PrescriptionStatus, Severity
from app.schemas.common import Out, Strict


class PrescriptionItemIn(Strict):
    drug_name: str = Field(min_length=1, max_length=160)
    inn_code: str | None = Field(default=None, max_length=64)
    atc_code: str | None = Field(default=None, max_length=10)
    dose: str = Field(min_length=1, max_length=60)
    route: str = Field(default="oral", min_length=1, max_length=30)
    frequency: str = Field(min_length=1, max_length=80)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    instructions: str | None = Field(default=None, max_length=2000)
    rationale: str | None = Field(default=None, max_length=2000)
    contraindications: list[str] = Field(default_factory=list, max_length=30)
    side_effects: list[str] = Field(default_factory=list, max_length=30)


class PrescriptionItemPatch(Strict):
    drug_name: str | None = Field(default=None, min_length=1, max_length=160)
    inn_code: str | None = Field(default=None, max_length=64)
    atc_code: str | None = Field(default=None, max_length=10)
    dose: str | None = Field(default=None, min_length=1, max_length=60)
    route: str | None = Field(default=None, min_length=1, max_length=30)
    frequency: str | None = Field(default=None, min_length=1, max_length=80)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    instructions: str | None = Field(default=None, max_length=2000)
    rationale: str | None = Field(default=None, max_length=2000)


class ApproveItemIn(Strict):
    override_reason: str | None = Field(default=None, max_length=1000)


class RejectItemIn(Strict):
    reason: str = Field(min_length=1, max_length=1000)


class PrescriptionItemOut(Out):
    id: UUID
    source: str
    drug_name: str
    inn_code: str | None = None
    atc_code: str | None = None
    dose: str
    route: str
    frequency: str
    duration_days: int | None = None
    instructions: str | None = None
    rationale: str | None = None
    contraindications: list[str] = []
    side_effects: list[str] = []
    interaction_warnings: list[Any] = []
    allergy_warning: bool
    safety_pending: bool
    override_reason: str | None = None
    status: PrescriptionStatus
    sort_order: int


class PrescriptionOut(Out):
    id: UUID
    status: PrescriptionStatus
    disclaimer: str
    safety_check: dict[str, Any]
    doctor_notes: str | None = None
    approved_at: datetime | None = None
    items: list[PrescriptionItemOut]
    version: int


# ------------------------------------------------------------------------------------ conclusion
class ConclusionIn(Strict):
    diagnosis_text: str = Field(min_length=1, max_length=10000)
    icd10_codes: list[str] = Field(default_factory=list, max_length=20)
    final_pcg_class: PcgClass
    final_severity: Severity
    agreement_with_ai: AgreementLevel
    disagreement_reason: str | None = Field(default=None, max_length=5000)
    recommendations: str = Field(default="", max_length=10000)
    follow_up_date: date | None = None
    follow_up_notes: str | None = Field(default=None, max_length=5000)
    referred_to: str | None = Field(default=None, max_length=160)


class AmendIn(ConclusionIn):
    amend_reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def _req(self):
        if not self.diagnosis_text.strip() or not self.recommendations.strip():
            raise ValueError("diagnosis_text va recommendations majburiy")
        return self


class ConclusionOut(Out):
    id: UUID
    examination_id: UUID
    doctor_id: UUID
    status: ConclusionStatus
    diagnosis_text: str
    icd10_codes: list[str]
    final_pcg_class: PcgClass
    final_severity: Severity
    agreement_with_ai: AgreementLevel
    disagreement_reason: str | None = None
    recommendations: str
    follow_up_date: date | None = None
    follow_up_notes: str | None = None
    referred_to: str | None = None
    amend_reason: str | None = None
    signed_at: datetime | None = None
    signature_hash: str | None = None
    amends_id: UUID | None = None
    is_current: bool
    version: int
    created_at: datetime
    updated_at: datetime


class SignOut(Out):
    id: UUID
    status: ConclusionStatus
    signed_at: datetime
    signature_hash: str
    exam_status: str

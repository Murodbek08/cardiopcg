"""AI report, prescriptions, doctor conclusions."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    AgreementLevel,
    ConclusionStatus,
    PcgClass,
    PrescriptionStatus,
    ReportStatus,
    Severity,
    pg_enum,
)

_JSONB = postgresql.JSONB
_EMPTY_OBJ = text("'{}'::jsonb")
_EMPTY_ARR = text("'[]'::jsonb")


class AiReport(UUIDPk, Base):
    __tablename__ = "ai_reports"

    examination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("examinations.id"), nullable=False)
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_results.id"), nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        pg_enum(ReportStatus, "report_status"),
        nullable=False,
        default=ReportStatus.generating,
        server_default="generating",
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    llm_provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="deepseek", server_default="deepseek"
    )
    llm_model: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[dict] = mapped_column(_JSONB, nullable=False, default=dict)
    differential_diagnoses: Mapped[list] = mapped_column(_JSONB, nullable=False, default=list)
    recommended_tests: Mapped[list] = mapped_column(
        _JSONB, nullable=False, default=list, server_default=_EMPTY_ARR
    )
    red_flags: Mapped[list] = mapped_column(_JSONB, nullable=False, default=list, server_default=_EMPTY_ARR)
    patient_friendly_text: Mapped[str | None] = mapped_column(Text)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(_JSONB, nullable=False, default=dict)
    raw_response: Mapped[dict | None] = mapped_column(_JSONB)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(8, 5))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index(
            "uq_ai_report_current_exam", "examination_id", unique=True, postgresql_where=text("is_current")
        ),
        Index("idx_ai_report_result", "analysis_result_id"),
        Index("idx_ai_report_created", "created_at"),
    )


class Prescription(UUIDPk, Timestamps, Base):
    __tablename__ = "prescriptions"

    examination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("examinations.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    ai_report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_reports.id"))
    status: Mapped[PrescriptionStatus] = mapped_column(
        pg_enum(PrescriptionStatus, "prescription_status"),
        nullable=False,
        default=PrescriptionStatus.suggested,
        server_default="suggested",
    )
    prescribed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safety_check: Mapped[dict] = mapped_column(
        _JSONB, nullable=False, default=dict, server_default=_EMPTY_OBJ
    )
    doctor_notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        Index("idx_rx_exam", "examination_id"),
        Index("idx_rx_patient_status", "patient_id", "status"),
    )


class DrugRecommendation(UUIDPk, Timestamps, Base):
    __tablename__ = "drug_recommendations"

    prescription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    drug_name: Mapped[str] = mapped_column(String(160), nullable=False)
    inn_code: Mapped[str | None] = mapped_column(String(64))
    atc_code: Mapped[str | None] = mapped_column(String(10))
    dose: Mapped[str] = mapped_column(String(60), nullable=False)
    route: Mapped[str] = mapped_column(String(30), nullable=False)
    frequency: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_days: Mapped[int | None] = mapped_column(SmallInteger)
    instructions: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    contraindications: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    side_effects: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    interaction_warnings: Mapped[list] = mapped_column(
        _JSONB, nullable=False, default=list, server_default=_EMPTY_ARR
    )
    allergy_warning: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    safety_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    override_reason: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PrescriptionStatus] = mapped_column(
        pg_enum(PrescriptionStatus, "prescription_status"),
        nullable=False,
        default=PrescriptionStatus.suggested,
        server_default="suggested",
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")

    __table_args__ = (Index("idx_drugrec_rx_sort", "prescription_id", "sort_order"),)


class DoctorConclusion(UUIDPk, Timestamps, Base):
    __tablename__ = "doctor_conclusions"

    examination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("examinations.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[ConclusionStatus] = mapped_column(
        pg_enum(ConclusionStatus, "conclusion_status"),
        nullable=False,
        default=ConclusionStatus.draft,
        server_default="draft",
    )
    diagnosis_text: Mapped[str] = mapped_column(Text, nullable=False)
    icd10_codes: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    final_pcg_class: Mapped[PcgClass] = mapped_column(pg_enum(PcgClass, "pcg_class"), nullable=False)
    final_severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"), nullable=False)
    agreement_with_ai: Mapped[AgreementLevel] = mapped_column(
        pg_enum(AgreementLevel, "agreement_level"), nullable=False
    )
    disagreement_reason: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    follow_up_notes: Mapped[str | None] = mapped_column(Text)
    referred_to: Mapped[str | None] = mapped_column(String(160))
    amend_reason: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signature_hash: Mapped[str | None] = mapped_column(String(64))
    amends_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doctor_conclusions.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        Index(
            "uq_conclusion_current_exam", "examination_id", unique=True, postgresql_where=text("is_current")
        ),
        Index("idx_concl_doctor_signed", "doctor_id", text("signed_at DESC")),
        Index("idx_concl_agreement", "agreement_with_ai", "signed_at"),
        Index("idx_concl_final_class", "final_pcg_class"),
    )

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
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

from app.db.base import Base, SoftDelete, Timestamps, UUIDPk
from app.models.enums import ExamPriority, ExamStatus, PatientPosition, pg_enum


class Examination(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "examinations"

    exam_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    status: Mapped[ExamStatus] = mapped_column(
        pg_enum(ExamStatus, "exam_status"), nullable=False, default=ExamStatus.draft, server_default="draft"
    )
    priority: Mapped[ExamPriority] = mapped_column(
        pg_enum(ExamPriority, "exam_priority"),
        nullable=False,
        default=ExamPriority.routine,
        server_default="routine",
    )
    performed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    examined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    complaints: Mapped[str | None] = mapped_column(Text)
    symptoms: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    patient_position: Mapped[PatientPosition | None] = mapped_column(
        pg_enum(PatientPosition, "patient_position")
    )
    heart_rate_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    bp_systolic: Mapped[int | None] = mapped_column(SmallInteger)
    bp_diastolic: Mapped[int | None] = mapped_column(SmallInteger)
    spo2_pct: Mapped[int | None] = mapped_column(SmallInteger)
    temperature_c: Mapped[float | None] = mapped_column(Numeric(3, 1))
    weight_kg_at_exam: Mapped[float | None] = mapped_column(Numeric(5, 1))
    ai_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    current_job_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        CheckConstraint(
            "bp_systolic IS NULL OR bp_diastolic IS NULL OR bp_systolic > bp_diastolic", name="bp_order"
        ),
        CheckConstraint("status <> 'completed' OR completed_at IS NOT NULL", name="completed_has_ts"),
        Index("idx_exam_patient_examined", "patient_id", text("examined_at DESC")),
        Index(
            "idx_exam_status_created",
            "status",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_exam_doctor_status",
            "assigned_doctor_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_exam_performed_created", "performed_by", text("created_at DESC")),
        Index("idx_exam_examined_at", "examined_at"),
        Index(
            "idx_exam_priority_status",
            "priority",
            "status",
            postgresql_where=text("status IN ('ai_ready','in_review')"),
        ),
        Index("idx_exam_created_brin", "created_at", postgresql_using="brin"),
    )


class ExamStatusHistory(Base):
    __tablename__ = "exam_status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    examination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("examinations.id"), nullable=False)
    from_status: Mapped[ExamStatus | None] = mapped_column(pg_enum(ExamStatus, "exam_status"))
    to_status: Mapped[ExamStatus] = mapped_column(pg_enum(ExamStatus, "exam_status"), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("idx_esh_exam_created", "examination_id", "created_at"),)


class ExamCounter(Base):
    __tablename__ = "exam_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

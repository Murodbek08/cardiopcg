from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    REAL,
    Boolean,
    CheckConstraint,
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

from app.db.base import Base, UUIDPk
from app.models.enums import JobStatus, MurmurTiming, PcgClass, SegmentType, Severity, pg_enum


class AnalysisJob(UUIDPk, Base):
    __tablename__ = "analysis_jobs"

    examination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("examinations.id"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.pending, server_default="pending"
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", server_default="queued")
    progress_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3, server_default="3")
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(40))
    options: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_job_exam_created", "examination_id", text("created_at DESC")),
        Index("idx_job_active", "status", postgresql_where=text("status IN ('pending','running')")),
    )


class AnalysisResult(UUIDPk, Base):
    __tablename__ = "analysis_results"

    examination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("examinations.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    pcg_class: Mapped[PcgClass] = mapped_column(pg_enum(PcgClass, "pcg_class"), nullable=False)
    class_probs: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        pg_enum(Severity, "severity"), nullable=False, default=Severity.none, server_default="none"
    )
    murmur_timing: Mapped[MurmurTiming] = mapped_column(
        pg_enum(MurmurTiming, "murmur_timing"),
        nullable=False,
        default=MurmurTiming.none,
        server_default="none",
    )
    murmur_grade: Mapped[int | None] = mapped_column(SmallInteger)
    murmur_shape: Mapped[str | None] = mapped_column(String(30))
    heart_rate_bpm: Mapped[float | None] = mapped_column(Numeric(5, 1))
    hr_variability_ms: Mapped[float | None] = mapped_column(Numeric(7, 2))
    s1_count: Mapped[int | None] = mapped_column(Integer)
    s2_count: Mapped[int | None] = mapped_column(Integer)
    mean_s1_s2_ms: Mapped[float | None] = mapped_column(Numeric(7, 2))
    mean_s2_s1_ms: Mapped[float | None] = mapped_column(Numeric(7, 2))
    systole_ms: Mapped[float | None] = mapped_column(Numeric(7, 2))
    diastole_ms: Mapped[float | None] = mapped_column(Numeric(7, 2))
    dominant_freq_hz: Mapped[float | None] = mapped_column(Numeric(7, 2))
    features: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    quality_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    quality_notes: Mapped[str | None] = mapped_column(Text)
    waveform_key: Mapped[str | None] = mapped_column(Text)
    spectrogram_recording_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recordings.id"))
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index(
            "uq_analysis_current_exam",
            "examination_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("idx_ar_class_created", "pcg_class", "created_at"),
        Index("idx_ar_severity", "severity"),
        Index("idx_ar_model", "model_version"),
    )


class PcgSegment(UUIDPk, Base):
    __tablename__ = "pcg_segments"

    analysis_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recordings.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[SegmentType] = mapped_column(pg_enum(SegmentType, "segment_type"), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_no: Mapped[int | None] = mapped_column(Integer)
    peak_amplitude: Mapped[float | None] = mapped_column(REAL)
    energy: Mapped[float | None] = mapped_column(REAL)
    dominant_freq_hz: Mapped[float | None] = mapped_column(REAL)
    confidence: Mapped[float | None] = mapped_column(REAL)
    meta: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint("end_ms > start_ms", name="segment_order"),
        Index("idx_seg_result_rec_start", "analysis_result_id", "recording_id", "start_ms"),
        Index("idx_seg_rec_type", "recording_id", "type"),
    )

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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

from app.db.base import Base, SoftDelete, Timestamps, UUIDPk
from app.models.enums import AuscultationSite, RecordingKind, RecordingStatus, pg_enum


class Recording(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "recordings"

    examination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("examinations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[RecordingKind] = mapped_column(pg_enum(RecordingKind, "recording_kind"), nullable=False)
    status: Mapped[RecordingStatus] = mapped_column(
        pg_enum(RecordingStatus, "recording_status"),
        nullable=False,
        default=RecordingStatus.uploading,
        server_default="uploading",
    )
    site: Mapped[AuscultationSite | None] = mapped_column(pg_enum(AuscultationSite, "auscultation_site"))
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    derived_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recordings.id"))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    ext: Mapped[str] = mapped_column(String(8), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_sec: Mapped[float | None] = mapped_column(Numeric(7, 3))
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(SmallInteger)
    bit_depth: Mapped[int | None] = mapped_column(SmallInteger)
    codec: Mapped[str | None] = mapped_column(String(30))
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    snr_db: Mapped[float | None] = mapped_column(Numeric(5, 2))
    validation_report: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    scan_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("kind <> 'audio' OR site IS NOT NULL", name="audio_has_site"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("idx_rec_exam_kind", "examination_id", "kind"),
        Index("idx_rec_sha256", "sha256"),
        Index(
            "idx_rec_exam_site",
            "examination_id",
            "site",
            postgresql_where=text("kind = 'audio' AND deleted_at IS NULL"),
        ),
    )

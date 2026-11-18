from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDelete, Timestamps, UUIDPk
from app.models.enums import AllergySeverity, BloodGroup, Gender, HistoryKind, pg_enum

patient_mrn_seq = Sequence("patient_mrn_seq", metadata=Base.metadata)


class Patient(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "patients"

    mrn: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(80))
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[Gender] = mapped_column(pg_enum(Gender, "gender"), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(postgresql.CITEXT())
    address: Mapped[str | None] = mapped_column(Text)
    national_id_enc: Mapped[bytes | None] = mapped_column(postgresql.BYTEA)
    national_id_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    blood_group: Mapped[BloodGroup] = mapped_column(
        pg_enum(BloodGroup, "blood_group"),
        nullable=False,
        default=BloodGroup.unknown,
        server_default="unknown",
    )
    height_cm: Mapped[float | None] = mapped_column(Numeric(5, 1))
    weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 1))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(160))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))
    primary_doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    ai_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("height_cm IS NULL OR (height_cm >= 30 AND height_cm <= 260)", name="height_range"),
        CheckConstraint("weight_kg IS NULL OR (weight_kg >= 1 AND weight_kg <= 400)", name="weight_range"),
        Index(
            "idx_patients_name_trgm",
            text("(last_name || ' ' || first_name || ' ' || coalesce(middle_name, '')) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index("idx_patients_phone", "phone"),
        Index("idx_patients_birth", "birth_date"),
        Index("idx_patients_doctor", "primary_doctor_id", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_patients_created", text("created_at DESC")),
    )


class MedicalHistory(UUIDPk, Timestamps, Base):
    __tablename__ = "medical_history"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[HistoryKind] = mapped_column(pg_enum(HistoryKind, "history_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    icd10_code: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)
    onset_date: Mapped[date | None] = mapped_column(Date)
    resolved_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        Index("idx_mh_patient_kind", "patient_id", "kind"),
        Index("idx_mh_patient_active", "patient_id", postgresql_where=text("is_active")),
    )


class Allergy(UUIDPk, Timestamps, Base):
    __tablename__ = "allergies"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    substance: Mapped[str] = mapped_column(String(160), nullable=False)
    substance_code: Mapped[str | None] = mapped_column(String(64))
    reaction: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[AllergySeverity] = mapped_column(
        pg_enum(AllergySeverity, "allergy_severity"),
        nullable=False,
        default=AllergySeverity.moderate,
        server_default="moderate",
    )
    noted_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        Index("idx_allergy_patient_active", "patient_id", postgresql_where=text("is_active")),
        Index("idx_allergy_code", text("lower(substance_code)")),
        Index(
            "uq_allergy_patient_substance",
            "patient_id",
            text("lower(substance)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class CurrentMedication(UUIDPk, Timestamps, Base):
    __tablename__ = "current_medications"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    drug_name: Mapped[str] = mapped_column(String(160), nullable=False)
    inn_code: Mapped[str | None] = mapped_column(String(64))
    dose: Mapped[str | None] = mapped_column(String(60))
    frequency: Mapped[str | None] = mapped_column(String(60))
    route: Mapped[str | None] = mapped_column(String(30))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    prescribed_by: Mapped[str | None] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        Index("idx_med_patient_active", "patient_id", postgresql_where=text("is_active")),
        Index("idx_med_inn", text("lower(inn_code)")),
    )

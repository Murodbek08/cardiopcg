"""Notifications, audit log, settings and helper tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk
from app.models.enums import (
    AuditAction,
    ExportFormat,
    JobStatus,
    NotificationType,
    UserRole,
    pg_enum,
)


class Notification(UUIDPk, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[NotificationType] = mapped_column(
        pg_enum(NotificationType, "notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_notif_user_read_created", "user_id", "is_read", text("created_at DESC")),
        Index("idx_notif_user_created", "user_id", text("created_at DESC")),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    username_snapshot: Mapped[str | None] = mapped_column(String(32))
    role_snapshot: Mapped[UserRole | None] = mapped_column(pg_enum(UserRole, "user_role"))
    action: Mapped[AuditAction] = mapped_column(pg_enum(AuditAction, "audit_action"), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(postgresql.INET)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    request_id: Mapped[str | None] = mapped_column(String(40))
    method: Mapped[str | None] = mapped_column(String(8))
    path: Mapped[str | None] = mapped_column(String(300))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    changes: Mapped[dict | None] = mapped_column(postgresql.JSONB)
    meta: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        Index("idx_audit_ts", text("ts DESC")),
        Index("idx_audit_user_ts", "user_id", text("ts DESC")),
        Index(
            "idx_audit_patient_ts",
            "patient_id",
            text("ts DESC"),
            postgresql_where=text("patient_id IS NOT NULL"),
        ),
        Index("idx_audit_resource", "resource_type", "resource_id"),
        Index("idx_audit_action_ts", "action", text("ts DESC")),
        Index("idx_audit_request", "request_id"),
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[object] = mapped_column(postgresql.JSONB, nullable=False)
    value_type: Mapped[str] = mapped_column(String(12), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ExportJob(UUIDPk, Base):
    __tablename__ = "export_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    params: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    format: Mapped[ExportFormat] = mapped_column(pg_enum(ExportFormat, "export_format"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.pending, server_default="pending"
    )
    file_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True))
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict | None] = mapped_column(postgresql.JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (PrimaryKeyConstraint("key", "user_id", name="pk_idempotency_keys"),)

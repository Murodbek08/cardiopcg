"""Drug knowledge base tables (admin-managed; the AI engine reads PUBLISHED drugs only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class KbDrug(UUIDPk, Timestamps, Base):
    __tablename__ = "kb_drugs"

    drug_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)  # engine id (slug)
    inn: Mapped[str] = mapped_column(String(160), nullable=False)
    group: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    atc_code: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", server_default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    data: Mapped[dict] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict
    )  # engine (cardiopcg-kb/1) record
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        Index("idx_kbdrug_status", "status"),
        Index("idx_kbdrug_inn_trgm", "inn", postgresql_using="gin", postgresql_ops={"inn": "gin_trgm_ops"}),
    )


class KbDrugVersion(Base):
    __tablename__ = "kb_drug_versions"

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    drug_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_drugs.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    snapshot: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False)
    change: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # create|update|publish|archive|import|seed
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("idx_kbver_drug", "drug_pk", "version"),)


class KbInteraction(UUIDPk, Timestamps, Base):
    __tablename__ = "kb_interactions"

    drug_a: Mapped[str] = mapped_column(String(100), nullable=False)  # drug_id or class:<name>
    drug_b: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    mechanism_uz: Mapped[str | None] = mapped_column(Text)
    effect_uz: Mapped[str | None] = mapped_column(Text)
    management_uz: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(
        postgresql.JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("drug_a", "drug_b", name="uq_kbint_pair"),
        Index("idx_kbint_b", "drug_b"),
    )


class KbMeta(Base):
    __tablename__ = "kb_meta"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

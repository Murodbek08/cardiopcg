from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.models.enums import NotificationType
from app.schemas.common import Out, Strict


class NotificationOut(Out):
    id: UUID
    type: NotificationType
    title: str
    body: str | None = None
    payload: dict[str, Any]
    is_read: bool
    created_at: datetime


class UnreadCount(Out):
    count: int


class AuditOut(Out):
    id: int
    ts: datetime
    user: dict[str, Any] | None = None
    action: str
    resource_type: str | None = None
    resource_id: UUID | None = None
    patient_id: UUID | None = None
    ip: str | None = None
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    success: bool
    changes: dict[str, Any] | None = None
    meta: dict[str, Any] = {}


class CsvExportIn(Strict):
    kind: Literal["examinations", "patients", "analytics_timeseries", "conclusions"]
    filters: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] | None = None
    anonymize: bool = True


class ExportJobOut(Out):
    export_id: UUID
    status: str
    kind: str
    file_url: str | None = None
    size_bytes: int | None = None
    error: str | None = None
    expires_at: datetime | None = None

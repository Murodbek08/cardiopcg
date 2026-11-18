from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from fastapi import Response
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Strict(BaseModel):
    """Input schema base: unknown fields are rejected (doc 01 section 7.4)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageMeta(BaseModel):
    limit: int
    next_cursor: str | None = None
    total: int | None = None


class Page[T](BaseModel):
    items: list[T]
    page: PageMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class UserRef(Out):
    id: UUID
    full_name: str


class Message(BaseModel):
    message: str = "ok"


def json_response(
    model: BaseModel, status_code: int = 200, headers: dict[str, str] | None = None
) -> Response:
    """Serialize a specific (role-dependent) model variant exactly, bypassing response_model re-validation."""
    return Response(
        content=model.model_dump_json(),
        status_code=status_code,
        media_type="application/json",
        headers=headers,
    )


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "UNAUTHENTICATED / TOKEN_EXPIRED"},
    403: {"model": ErrorResponse, "description": "FORBIDDEN"},
    404: {"model": ErrorResponse, "description": "NOT_FOUND"},
    422: {"model": ErrorResponse, "description": "VALIDATION_ERROR"},
}

__all__ = [
    "ERROR_RESPONSES",
    "ErrorResponse",
    "Field",
    "Message",
    "Out",
    "Page",
    "PageMeta",
    "Strict",
    "UserRef",
    "iso",
    "json_response",
]

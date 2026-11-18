"""Per-request context (request id, ip, UA, user) via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RequestInfo:
    request_id: str = ""
    ip: str | None = None
    user_agent: str | None = None
    method: str | None = None
    path: str | None = None
    user_id: str | None = None
    role: str | None = None
    extra: dict = field(default_factory=dict)


_request_info: ContextVar[RequestInfo | None] = ContextVar("request_info", default=None)


def set_request_info(info: RequestInfo):
    return _request_info.set(info)


def reset_request_info(token) -> None:
    _request_info.reset(token)


def get_request_info() -> RequestInfo:
    return _request_info.get() or RequestInfo()


def get_request_id() -> str | None:
    info = _request_info.get()
    return info.request_id if info else None

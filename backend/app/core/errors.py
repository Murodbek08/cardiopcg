"""Unified error format (doc 01 section 0) and exception handlers."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id

log = structlog.get_logger()

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    423: "ACCOUNT_LOCKED",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "AI_UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


def bad_request(
    code: str = "BAD_REQUEST", message: str = "So'rov noto'g'ri", details: Any = None
) -> AppError:
    return AppError(400, code, message, details)


def unauthenticated(
    code: str = "UNAUTHENTICATED", message: str = "Autentifikatsiya talab qilinadi"
) -> AppError:
    return AppError(401, code, message, headers={"WWW-Authenticate": "Bearer"})


def forbidden(
    message: str = "Bu amal uchun ruxsat yo'q", code: str = "FORBIDDEN", details: Any = None
) -> AppError:
    return AppError(403, code, message, details)


def not_found(what: str = "Resurs") -> AppError:
    return AppError(404, "NOT_FOUND", f"{what} topilmadi")


def conflict(code: str, message: str, details: Any = None) -> AppError:
    return AppError(409, code, message, details)


def unprocessable(code: str, message: str, details: Any = None) -> AppError:
    return AppError(422, code, message, details)


def invalid_state(
    current: str, allowed: list[str], message: str = "Joriy holatda bu amal mumkin emas"
) -> AppError:
    return AppError(409, "INVALID_STATE", message, {"current": current, "allowed": allowed})


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details is not None:
        err["details"] = details
    return {"error": err}


def _json(status: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None):
    return JSONResponse(error_body(code, message, details), status_code=status, headers=headers)


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _json(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = []
        for e in exc.errors():
            loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
            details.append({"field": ".".join(loc), "msg": str(e.get("msg", "")), "type": e.get("type", "")})
        return _json(422, "VALIDATION_ERROR", "Ma'lumotlar noto'g'ri", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return _json(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.error("unhandled_exception", exc_type=type(exc).__name__, exc_info=exc)
        return _json(500, "INTERNAL_ERROR", "Ichki xatolik")

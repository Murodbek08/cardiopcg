from __future__ import annotations

from fastapi import Request

from app.core.errors import AppError


def check_if_match(request: Request, current_version: int) -> None:
    """Optimistic locking: if `If-Match` is sent and differs from the stored version -> 409 VERSION_CONFLICT."""
    raw = request.headers.get("if-match")
    if raw is None:
        return
    val = raw.strip().strip('"').removeprefix("W/").strip('"')
    if not val.isdigit() or int(val) != current_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "Yozuv boshqa foydalanuvchi tomonidan o'zgartirilgan",
            {"current_version": current_version},
        )


def etag(version: int) -> dict[str, str]:
    return {"ETag": f'"{version}"'}

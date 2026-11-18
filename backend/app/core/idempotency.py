"""Idempotency-Key support (upload / analyze / sign): replays the stored response for a repeated key."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.system import IdempotencyKey


def _key(request: Request) -> str | None:
    k = request.headers.get("idempotency-key")
    if k is None:
        return None
    k = k.strip()
    if not 8 <= len(k) <= 64:
        raise AppError(422, "VALIDATION_ERROR", "Idempotency-Key 8..64 belgi bo'lishi kerak")
    return k


async def replay(db: AsyncSession, request: Request, user_id, endpoint: str) -> JSONResponse | None:
    k = _key(request)
    if k is None:
        return None
    row = await db.get(IdempotencyKey, (k, user_id))
    if row is None:
        return None
    if row.endpoint != endpoint:
        raise AppError(422, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key boshqa amal uchun ishlatilgan")
    resp = JSONResponse(row.response_body, status_code=row.status_code or 200)
    resp.headers["Idempotent-Replay"] = "true"
    return resp


async def store(
    db: AsyncSession, request: Request, user_id, endpoint: str, status: int, body: dict[str, Any]
) -> None:
    k = _key(request)
    if k is None:
        return
    safe = orjson.loads(orjson.dumps(body, default=str))
    db.add(
        IdempotencyKey(
            key=k,
            user_id=user_id,
            endpoint=endpoint,
            status_code=status,
            response_body=safe,
            response_hash=hashlib.sha256(orjson.dumps(safe, option=orjson.OPT_SORT_KEYS)).hexdigest(),
        )
    )

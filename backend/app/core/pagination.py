"""Keyset (cursor) pagination with multi-key sort and id tie-breaker (doc 01 section 3.14)."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import orjson
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError


def _enc_val(v: Any) -> list:
    if isinstance(v, datetime):
        return ["dt", v.isoformat()]
    if isinstance(v, date):
        return ["d", v.isoformat()]
    if isinstance(v, uuid.UUID):
        return ["u", str(v)]
    if hasattr(v, "value") and not isinstance(v, str | int | float):
        return ["v", v.value]
    if hasattr(v, "__float__") and not isinstance(v, int | float | bool):
        return ["f", float(v)]
    return ["v", v]


def _dec_val(t: list) -> Any:
    tag, v = t
    if tag == "dt":
        return datetime.fromisoformat(v)
    if tag == "d":
        return date.fromisoformat(v)
    if tag == "u":
        return uuid.UUID(v)
    return v


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(orjson.dumps({"k": [_enc_val(v) for v in values]})).decode()


def decode_cursor(cursor: str) -> list[Any]:
    try:
        raw = orjson.loads(base64.urlsafe_b64decode(cursor.encode()))
        return [_dec_val(t) for t in raw["k"]]
    except Exception:
        raise AppError(400, "BAD_CURSOR", "Kursor noto'g'ri")


@dataclass
class SortKey:
    expr: ColumnElement
    desc: bool


def parse_sort(sort: str | None, allowed: dict[str, ColumnElement], default: str) -> list[SortKey]:
    keys: list[SortKey] = []
    spec = sort or default
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        desc = part.startswith("-")
        name = part.lstrip("-+")
        if name not in allowed:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                f"Saralash maydoni ruxsat etilmagan: {name}",
                [{"field": "sort", "msg": f"allowed: {', '.join(sorted(allowed))}", "type": "value_error"}],
            )
        keys.append(SortKey(allowed[name], desc))
    return keys


def _after(keys: list[SortKey], id_col: ColumnElement, values: list[Any]) -> ColumnElement:
    """Lexicographic 'strictly after cursor' predicate for mixed-direction keys (+ id ASC tiebreak)."""
    all_keys = [*keys, SortKey(id_col, False)]
    if len(values) != len(all_keys):
        raise AppError(400, "BAD_CURSOR", "Kursor saralashga mos emas")
    ors = []
    for i, k in enumerate(all_keys):
        eqs = [all_keys[j].expr == values[j] for j in range(i)]
        cmp = k.expr < values[i] if k.desc else k.expr > values[i]
        ors.append(and_(*eqs, cmp))
    return or_(*ors)


def clamp_limit(limit: int | None, default: int = 20, maximum: int = 100) -> int:
    if limit is None:
        return default
    return max(1, min(limit, maximum))


async def paginate(
    db: AsyncSession,
    stmt: Select,
    *,
    id_col: ColumnElement,
    sort: list[SortKey],
    cursor: str | None,
    limit: int,
    with_total: bool,
    row_key_cols: list[ColumnElement] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Returns (rows, page_meta). `stmt` must select columns incl. sort exprs labelled `_k0.._kN` and `_id`."""
    total = None
    if with_total:
        total = (
            await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    q = stmt
    if cursor:
        q = q.where(_after(sort, id_col, decode_cursor(cursor)))
    order = [(k.expr.desc() if k.desc else k.expr.asc()) for k in sort] + [id_col.asc()]
    q = q.order_by(*order).limit(limit + 1)
    rows = list((await db.execute(q)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]._mapping
        next_cursor = encode_cursor([last[f"_k{i}"] for i in range(len(sort))] + [last["_id"]])
    page: dict[str, Any] = {"limit": limit, "next_cursor": next_cursor}
    if total is not None:
        page["total"] = total
    return rows, page


def with_sort_columns(stmt: Select, sort: list[SortKey], id_col: ColumnElement) -> Select:
    cols = [k.expr.label(f"_k{i}") for i, k in enumerate(sort)] + [id_col.label("_id")]
    return stmt.add_columns(*cols)

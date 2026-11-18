"""Admin drug knowledge base (docs/03 section 3.22). Admin writes; doctors read."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlalchemy import func, or_, select, text

from app.core.deps import DB, Perm
from app.core.errors import AppError, conflict
from app.core.permissions import Permission
from app.core.route import TxRoute
from app.db.base import new_id, utcnow
from app.models.enums import AuditAction
from app.models.kb import KbDrug, KbDrugVersion, KbInteraction
from app.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.drugs import DrugIn, ImportReportOut
from app.services import audit_service
from app.services import kb_service as kb
from app.services.export_service import csv_safe

router = APIRouter(
    prefix="/admin/drugs", tags=["admin-drugs"], route_class=TxRoute, responses=ERROR_RESPONSES
)
READ = Perm(Permission.drug_kb_read)
WRITE = Perm(Permission.drug_kb_write)
STATUSES = ("draft", "published", "archived")


def _audit(db, user, action, row, **meta):
    audit_service.log_event(
        db,
        action,
        user=user,
        resource_type="drug",
        resource_id=row.id,
        meta={"inn": row.inn, "version": row.version, **meta},
    )


@router.get("")
async def list_drugs(
    db: DB,
    user: User = READ,
    q: str | None = Query(default=None, max_length=100),
    group: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=12),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = select(KbDrug)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                KbDrug.inn.ilike(like),
                KbDrug.drug_id.ilike(like),
                text("kb_drugs.data::text ILIKE :aq").bindparams(aq=like),
            )
        )
    if group:
        stmt = stmt.where(KbDrug.group == group)
    if status:
        if status not in STATUSES:
            raise AppError(422, "VALIDATION_ERROR", "status: draft|published|archived")
        stmt = stmt.where(KbDrug.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(func.lower(KbDrug.inn), KbDrug.id)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [kb.list_item(r) for r in rows],
        "page": {"page": page, "page_size": page_size, "total": total},
    }


@router.get("/groups")
async def list_groups(db: DB, user: User = READ):
    rows = (
        await db.execute(select(KbDrug.group, func.count()).group_by(KbDrug.group).order_by(KbDrug.group))
    ).all()
    return {"items": [{"group": g, "count": c} for g, c in rows]}


@router.get("/export")
async def export_drugs(db: DB, user: User = READ, status: str | None = None):
    stmt = select(KbDrug).order_by(func.lower(KbDrug.inn))
    if status in STATUSES:
        stmt = stmt.where(KbDrug.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(kb.IMPORT_COLUMNS + ["status", "version"])
    for r in rows:
        d = await kb.detail(db, r)
        dr = d["dose_rules"][0] if d["dose_rules"] else {}
        src = d["sources"][0] if d["sources"] else {}
        w.writerow(
            [
                csv_safe(x)
                for x in (
                    r.inn,
                    r.group,
                    r.atc_code,
                    ";".join(d["trade_names"]),
                    ";".join(d["forms"]),
                    ";".join(d["indications_icd10"]),
                    dr.get("population"),
                    dr.get("min_dose"),
                    dr.get("max_dose"),
                    dr.get("unit"),
                    dr.get("max_daily"),
                    dr.get("note"),
                    src.get("title"),
                    src.get("url"),
                    r.status,
                    r.version,
                )
            ]
        )
    audit_service.log_event(
        db, AuditAction.export, user=user, resource_type="drug_kb", meta={"rows": len(rows)}
    )
    return Response(
        buf.getvalue().encode(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="drugs.csv"'},
    )


@router.get("/interactions")
async def list_interactions(
    db: DB,
    user: User = READ,
    q: str | None = Query(default=None, max_length=100),
    severity: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    stmt = select(KbInteraction)
    if q:
        stmt = stmt.where(KbInteraction.drug_a.ilike(f"%{q}%") | KbInteraction.drug_b.ilike(f"%{q}%"))
    if severity:
        stmt = stmt.where(KbInteraction.severity == severity)
    rows = (
        (await db.execute(stmt.order_by(KbInteraction.drug_a, KbInteraction.drug_b).limit(limit)))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "drug_a": r.drug_a,
                "drug_b": r.drug_b,
                "level": r.severity,
                "mechanism": r.mechanism_uz,
                "effect": r.effect_uz,
                "recommendation": r.management_uz,
            }
            for r in rows
        ]
    }


@router.get("/interactions/graph")
async def interaction_graph(db: DB, user: User = READ):
    drugs = (await db.execute(select(KbDrug))).scalars().all()
    inter = (await db.execute(select(KbInteraction))).scalars().all()
    nodes = {
        d.drug_id: {"id": d.drug_id, "label": d.inn, "group": d.group, "status": d.status, "kind": "drug"}
        for d in drugs
    }
    edges = []
    for i in inter:
        for ref in (i.drug_a, i.drug_b):
            if ref not in nodes:
                nodes[ref] = {
                    "id": ref,
                    "label": ref.removeprefix("class:"),
                    "group": "class" if ref.startswith("class:") else "unknown",
                    "status": None,
                    "kind": "class" if ref.startswith("class:") else "unknown",
                }
        edges.append({"source": i.drug_a, "target": i.drug_b, "level": i.severity})
    return {"nodes": list(nodes.values()), "edges": edges}


@router.post("/import", response_model=ImportReportOut)
async def import_csv(
    db: DB, user: User = WRITE, file: UploadFile = File(...), dry_run: bool = Query(default=True)
):
    """CSV import. dry_run=true validates only; dry_run=false creates DRAFT drugs for valid rows."""
    parsed, total = kb.parse_import(await file.read(2 * 1024 * 1024 + 1))
    errors = [{"row": n, "message": m} for n, body, m in parsed if body is None]
    seen: set[str] = set()
    ok: list[tuple[int, DrugIn]] = []
    for n, body, _ in parsed:
        if body is None:
            continue
        key = body.inn.strip().lower()
        exists = (await db.execute(select(KbDrug.id).where(func.lower(KbDrug.inn) == key))).first()
        if exists or key in seen:
            errors.append({"row": n, "message": f"INN takrorlangan yoki bazada mavjud: {body.inn}"})
            continue
        seen.add(key)
        ok.append((n, body))
    created = 0
    if not dry_run:
        for _, body in ok:
            drug_id = await kb.unique_drug_id(db, body.inn)
            row = KbDrug(
                id=new_id(),
                drug_id=drug_id,
                inn=body.inn,
                group=body.group,
                atc_code=body.atc_code,
                status="draft",
                version=1,
                data=kb.apply_input(None, body, drug_id),
                updated_by=user.id,
            )
            db.add(row)
            await db.flush()
            kb.record_version(db, row, "import", user.id)
            created += 1
        audit_service.log_event(
            db,
            AuditAction.create,
            user=user,
            resource_type="drug_kb",
            meta={"import": True, "created": created, "errors": len(errors)},
        )
        if created:
            await kb.bump_kb_version(db)
    return {
        "total": total,
        "valid": len(ok),
        "errors": sorted(errors, key=lambda e: e["row"]),
        "created": created,
        "dry_run": dry_run,
    }


@router.post("", status_code=201)
async def create_drug(body: DrugIn, db: DB, user: User = WRITE):
    drug_id = await kb.unique_drug_id(db, body.inn)
    row = KbDrug(
        id=new_id(),
        drug_id=drug_id,
        inn=body.inn,
        group=body.group,
        atc_code=body.atc_code,
        status="draft",
        version=1,
        data=kb.apply_input(None, body, drug_id),
        updated_by=user.id,
    )
    db.add(row)
    await db.flush()
    await kb.replace_interactions(db, row, body.interactions)
    kb.record_version(db, row, "create", user.id)
    await kb.bump_kb_version(db)
    _audit(db, user, AuditAction.create, row)
    await db.flush()
    return await kb.detail(db, row)


@router.get("/{drug_pk}")
async def get_drug(drug_pk: uuid.UUID, db: DB, user: User = READ):
    return await kb.detail(db, await kb.get_row(db, drug_pk))


@router.put("/{drug_pk}")
async def update_drug(drug_pk: uuid.UUID, body: DrugIn, db: DB, user: User = WRITE):
    """Edit creates a new version. A published drug goes back to draft and must be re-published (re-review)."""
    row = await kb.get_row(db, drug_pk)
    if row.status == "archived":
        raise conflict("DRUG_ARCHIVED", "Arxivlangan dori tahrirlanmaydi")
    if body.inn.strip().lower() != row.inn.strip().lower():
        await kb.unique_drug_id(db, body.inn, exclude=row.id)  # INN uniqueness check
    before = {"inn": row.inn, "group": row.group, "status": row.status}
    row.data = kb.apply_input(row.data, body, row.drug_id)
    row.inn, row.group, row.atc_code = body.inn, body.group, body.atc_code
    was_published = row.status == "published"
    row.status = "draft"
    row.version += 1
    row.updated_by, row.updated_at = user.id, utcnow()
    await db.flush()
    await kb.replace_interactions(db, row, body.interactions)
    kb.record_version(db, row, "update", user.id)
    await kb.bump_kb_version(db)
    _audit(db, user, AuditAction.update, row, unpublished=was_published, before=before)
    await db.flush()
    return await kb.detail(db, row)


@router.post("/{drug_pk}/publish", responses={422: {"description": "PUBLISH_BLOCKED"}})
async def publish(drug_pk: uuid.UUID, db: DB, user: User = WRITE):
    row = await kb.get_row(db, drug_pk)
    if row.status == "archived":
        raise conflict("DRUG_ARCHIVED", "Arxivlangan dorini nashr qilib bo'lmaydi")
    blockers = kb.publish_blockers(row.data, row.inn, row.group)
    if blockers:
        raise AppError(
            422,
            "PUBLISH_BLOCKED",
            "Nashr qilish uchun majburiy bo'limlar to'ldirilmagan",
            {"missing": blockers},
        )
    if row.status != "published":
        row.status = "published"
        row.updated_by, row.updated_at = user.id, utcnow()
        kb.record_version(db, row, "publish", user.id)
        await kb.bump_kb_version(db)
        audit_service.log_event(
            db,
            AuditAction.status_change,
            user=user,
            resource_type="drug",
            resource_id=row.id,
            changes={"before": {"status": "draft"}, "after": {"status": "published"}},
            meta={"inn": row.inn, "version": row.version},
        )
        await db.flush()
    return await kb.detail(db, row)


@router.post("/{drug_pk}/archive")
async def archive(drug_pk: uuid.UUID, db: DB, user: User = WRITE):
    row = await kb.get_row(db, drug_pk)
    if row.status != "archived":
        prev = row.status
        row.status = "archived"
        row.updated_by, row.updated_at = user.id, utcnow()
        kb.record_version(db, row, "archive", user.id)
        await kb.bump_kb_version(db)
        audit_service.log_event(
            db,
            AuditAction.status_change,
            user=user,
            resource_type="drug",
            resource_id=row.id,
            changes={"before": {"status": prev}, "after": {"status": "archived"}},
            meta={"inn": row.inn},
        )
        await db.flush()
    return await kb.detail(db, row)


@router.get("/{drug_pk}/versions")
async def versions(drug_pk: uuid.UUID, db: DB, user: User = READ):
    row = await kb.get_row(db, drug_pk)
    vs = (
        (
            await db.execute(
                select(KbDrugVersion)
                .where(KbDrugVersion.drug_pk == row.id)
                .order_by(KbDrugVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "version": v.version,
                "status": v.status,
                "change": v.change,
                "changed_by": v.changed_by,
                "created_at": v.created_at,
                "snapshot": v.snapshot,
            }
            for v in vs
        ]
    }


_: Any = None

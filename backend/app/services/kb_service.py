"""Drug KB persistence: DB <-> admin API view <-> AI engine KB (app.services.ai.kb.DrugKB).

DB row ``data`` holds the engine record (cardiopcg-kb/1). The admin/frontend view is derived from it.
Status mapping: draft <-> kb_status draft, published <-> reviewed (+enabled), archived <-> retired.
The engine only proposes ``reviewed`` drugs unless CARDIOPCG_KB_ALLOW_DRAFT is set (its own filter).
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, conflict, not_found
from app.db.base import new_id, utcnow
from app.models.kb import KbDrug, KbDrugVersion, KbInteraction, KbMeta
from app.schemas.drugs import ATC_RE, DrugIn
from app.services.ai.kb import Drug, DrugKB, Interaction

ENGINE_STATUS = {"draft": "draft", "published": "reviewed", "archived": "retired"}
FROM_ENGINE = {"draft": "draft", "reviewed": "published", "retired": "archived"}
FREQ_MAP = {"common": "common", "uncommon": "uncommon", "rare": "rare"}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")[:80] or "drug"


# ------------------------------------------------------------------------------ meta / versions
async def get_meta(db: AsyncSession, key: str, default: Any) -> Any:
    row = await db.get(KbMeta, key)
    return row.value.get("v", default) if row else default


async def set_meta(db: AsyncSession, key: str, value: Any) -> None:
    row = await db.get(KbMeta, key)
    if row is None:
        db.add(KbMeta(key=key, value={"v": value}))
    else:
        row.value = {"v": value}
        row.updated_at = utcnow()


async def bump_kb_version(db: AsyncSession) -> int:
    v = int(await get_meta(db, "kb_version", 0)) + 1
    await set_meta(db, "kb_version", v)
    return v


def _snapshot(row: KbDrug) -> dict[str, Any]:
    return {"drug_id": row.drug_id, "status": row.status, "version": row.version, "data": row.data}


def record_version(db: AsyncSession, row: KbDrug, change: str, user_id: uuid.UUID | None) -> None:
    db.add(
        KbDrugVersion(
            id=new_id(),
            drug_pk=row.id,
            version=row.version,
            status=row.status,
            snapshot=_snapshot(row),
            change=change,
            changed_by=user_id,
        )
    )


# ------------------------------------------------------------------------------------ mapping
def _srcs_to_view(src: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for s in src or []:
        title = s.get("title") or s.get("name") or ""
        if s.get("year"):
            title = f"{title} ({s['year']})"
        out.append({"title": title, "url": s.get("url") or ""})
    return out


def _dose_view(d: dict[str, Any]) -> dict[str, Any]:
    lo = d.get("dose_min") if d.get("dose_min") is not None else d.get("per_kg_min")
    hi = d.get("dose_max") if d.get("dose_max") is not None else d.get("per_kg_max")
    note = " ".join(x for x in (d.get("frequency"), d.get("titration_uz")) if x) or None
    return {
        "population": d.get("population", "adult"),
        "min_dose": lo or 0,
        "max_dose": hi or 0,
        "unit": d.get("unit", ""),
        "max_daily": d.get("max_daily"),
        "note": note or "",
    }


def _se_freq(f: str | None) -> str:
    f = (f or "").lower()
    return "rare" if "rare" in f or "kam" in f else "uncommon" if "uncommon" in f else "common"


async def _interaction_views(db: AsyncSession, row: KbDrug) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(KbInteraction)
                .where((KbInteraction.drug_a == row.drug_id) | (KbInteraction.drug_b == row.drug_id))
                .order_by(KbInteraction.created_at)
            )
        )
        .scalars()
        .all()
    )
    others = {(r.drug_b if r.drug_a == row.drug_id else r.drug_a) for r in rows}
    ids = {}
    names = {}
    if others:
        for k in (await db.execute(select(KbDrug).where(KbDrug.drug_id.in_(others)))).scalars():
            ids[k.drug_id], names[k.drug_id] = str(k.id), k.inn
    out = []
    for r in rows:
        o = r.drug_b if r.drug_a == row.drug_id else r.drug_a
        out.append(
            {
                "drug_id": ids.get(o, o),
                "drug_name": names.get(o, o.removeprefix("class:")),
                "level": r.severity,
                "mechanism": r.mechanism_uz or r.effect_uz or "-",
                "recommendation": r.management_uz or r.effect_uz or "-",
            }
        )
    return out


def list_item(row: KbDrug) -> dict[str, Any]:
    return {
        "id": row.id,
        "inn": row.inn,
        "trade_names": row.data.get("aliases", []),
        "group": row.group,
        "version": row.version,
        "status": row.status,
        "updated_at": row.updated_at.isoformat(),
    }


async def detail(db: AsyncSession, row: KbDrug) -> dict[str, Any]:
    d = row.data
    forms = [
        f.get("form", "")
        + (f" {'/'.join(str(x) for x in f['strengths_mg'])} mg" if f.get("strengths_mg") else "")
        if isinstance(f, dict)
        else str(f)
        for f in d.get("forms", [])
    ]
    return {
        **list_item(row),
        "atc_code": row.atc_code,
        "forms": [f.strip() for f in forms if f.strip()],
        "indications_icd10": d.get("indications_icd10", []),
        "dose_rules": [_dose_view(x) for x in d.get("doses", [])],
        "contraindications": [
            {"text": c.get("note_uz") or c.get("code", ""), "absolute": c.get("kind") == "absolute"}
            for c in d.get("contraindications", [])
        ],
        "side_effects": [
            {"text": a.get("effect_uz", ""), "frequency": _se_freq(a.get("frequency"))}
            for a in d.get("adverse_effects", [])
        ],
        "interactions": await _interaction_views(db, row),
        "sources": _srcs_to_view(d.get("sources", [])),
    }


def apply_input(existing: dict[str, Any] | None, body: DrugIn, drug_id: str) -> dict[str, Any]:
    """Merge the admin payload into the engine record, preserving engine-only fields by position."""
    d = dict(existing or {})
    old_doses = d.get("doses", [])
    old_contra = d.get("contraindications", [])
    d.update(
        {
            "drug_id": drug_id,
            "inn_en": body.inn,
            "aliases": body.trade_names,
            "atc_code": body.atc_code,
            "class_group": body.group,
            "drug_class": d.get("drug_class") or body.group,
            "indications_icd10": body.indications_icd10,
        }
    )
    d.setdefault("indications", [])
    d.setdefault("interaction_classes", [])
    old_forms = {(f.get("form", "") if isinstance(f, dict) else str(f)): f for f in d.get("forms", [])}
    d["forms"] = [old_forms.get(f, {"form": f}) for f in body.forms]
    doses = []
    for i, r in enumerate(body.dose_rules):
        base = dict(old_doses[i]) if i < len(old_doses) and _dose_view(old_doses[i])["unit"] == r.unit else {}
        base.update(
            {
                "population": r.population
                if r.population in ("adult", "elderly", "pediatric")
                else base.get("population", "adult"),
                "dose_min": r.min_dose,
                "dose_max": r.max_dose,
                "unit": r.unit,
                "max_daily": r.max_daily,
                "frequency": r.note or base.get("frequency") or "-",
                "route": base.get("route", "po"),
            }
        )
        base.pop("per_kg_min", None) if base.get("dose_min") else None
        doses.append(base)
    d["doses"] = doses
    contra = []
    for i, c in enumerate(body.contraindications):
        base = (
            dict(old_contra[i])
            if i < len(old_contra) and (old_contra[i].get("note_uz") or old_contra[i].get("code")) == c.text
            else {}
        )
        base.update(
            {
                "kind": "absolute" if c.absolute else "relative",
                "code": base.get("code") or slugify(c.text)[:60],
                "note_uz": c.text,
            }
        )
        contra.append(base)
    d["contraindications"] = contra
    d["adverse_effects"] = [{"effect_uz": s.text, "frequency": s.frequency} for s in body.side_effects]
    d["sources"] = [
        {"type": "reference", "title": s.title, "name": s.title, "url": s.url} for s in body.sources
    ]
    return d


def publish_blockers(row_data: dict[str, Any], inn: str, group: str) -> list[str]:
    out = []
    if not (inn or "").strip():
        out.append("inn")
    if not (group or "").strip():
        out.append("group")
    if not row_data.get("doses"):
        out.append("dose_rules")
    if not [s for s in row_data.get("sources", []) if s.get("url")]:
        out.append("sources")
    return out


async def resolve_other(db: AsyncSession, ref: str) -> str:
    """Interaction partner: KB uuid -> drug_id; drug_id / class:<name> pass through (must exist if a drug)."""
    ref = ref.strip()
    if ref.startswith("class:"):
        return ref
    try:
        u = uuid.UUID(ref)
        row = await db.get(KbDrug, u)
        if row is None:
            raise AppError(422, "VALIDATION_ERROR", f"Interaksiya dorisi topilmadi: {ref}")
        return row.drug_id
    except ValueError:
        row = (await db.execute(select(KbDrug).where(KbDrug.drug_id == ref))).scalar_one_or_none()
        if row is None:
            raise AppError(422, "VALIDATION_ERROR", f"Interaksiya dorisi topilmadi: {ref}")
        return row.drug_id


async def replace_interactions(db: AsyncSession, row: KbDrug, items: list) -> None:
    keep_class = {}
    existing = (
        (
            await db.execute(
                select(KbInteraction).where(
                    (KbInteraction.drug_a == row.drug_id) | (KbInteraction.drug_b == row.drug_id)
                )
            )
        )
        .scalars()
        .all()
    )
    for e in existing:
        keep_class[(e.drug_a, e.drug_b)] = e
    wanted: dict[tuple[str, str], Any] = {}
    for it in items:
        other = await resolve_other(db, it.drug_id)
        if other == row.drug_id:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "Dori o'zi bilan o'zaro ta'sir qila olmaydi",
                [{"field": "interactions", "msg": "self interaction", "type": "value_error"}],
            )
        a, b = (row.drug_id, other)
        if (other, row.drug_id) in keep_class:
            a, b = other, row.drug_id
        wanted[(a, b)] = it
    for key, e in keep_class.items():
        if key not in wanted:
            await db.delete(e)
    await db.flush()
    for (a, b), it in wanted.items():
        e = keep_class.get((a, b))
        if e is None:
            db.add(
                KbInteraction(
                    drug_a=a,
                    drug_b=b,
                    severity=it.level,
                    mechanism_uz=it.mechanism,
                    management_uz=it.recommendation,
                )
            )
        else:
            e.severity, e.mechanism_uz, e.management_uz = it.level, it.mechanism, it.recommendation


async def unique_drug_id(db: AsyncSession, inn: str, exclude: uuid.UUID | None = None) -> str:
    base = slugify(inn)
    q = select(KbDrug).where(func.lower(KbDrug.inn) == inn.strip().lower())
    if exclude:
        q = q.where(KbDrug.id != exclude)
    if (await db.execute(q)).first():
        raise conflict("INN_TAKEN", "Bu INN bilan dori mavjud")
    cand, n = base, 2
    while (await db.execute(select(KbDrug.id).where(KbDrug.drug_id == cand))).first():
        cand = f"{base}_{n}"
        n += 1
    return cand


async def get_row(db: AsyncSession, pk: uuid.UUID) -> KbDrug:
    row = await db.get(KbDrug, pk)
    if row is None:
        raise not_found("Dori")
    return row


# ------------------------------------------------------------------------------------- seeding
def _status_from_engine(d: dict[str, Any]) -> str:
    return FROM_ENGINE.get(d.get("kb_status", "draft"), "draft")


async def seed_from_yaml(
    db: AsyncSession, directory: str | Path | None = None, user_id: uuid.UUID | None = None
) -> dict[str, int]:
    """Idempotent: inserts drugs/interactions that are missing; never overwrites admin edits."""
    from app.services.ai.config import default_kb_dir

    d = Path(directory or default_kb_dir())
    kb = DrugKB.load(d)
    added = 0
    for drug in kb.drugs.values():
        if (await db.execute(select(KbDrug.id).where(KbDrug.drug_id == drug.drug_id))).first():
            continue
        data = drug.model_dump(mode="json")
        data["aliases"] = list(drug.aliases)
        row = KbDrug(
            id=new_id(),
            drug_id=drug.drug_id,
            inn=drug.inn_en,
            group=drug.class_group,
            atc_code=drug.atc_code,
            status=_status_from_engine(data),
            version=1,
            data=data,
            updated_by=user_id,
        )
        db.add(row)
        await db.flush()
        record_version(db, row, "seed", user_id)
        added += 1
    inter = 0
    for it in kb.interactions:
        exists = (
            await db.execute(
                select(KbInteraction.id).where(
                    ((KbInteraction.drug_a == it.drug_a) & (KbInteraction.drug_b == it.drug_b_or_class))
                    | ((KbInteraction.drug_a == it.drug_b_or_class) & (KbInteraction.drug_b == it.drug_a))
                )
            )
        ).first()
        if exists:
            continue
        db.add(
            KbInteraction(
                drug_a=it.drug_a,
                drug_b=it.drug_b_or_class,
                severity=it.severity,
                mechanism_uz=it.mechanism_uz,
                effect_uz=it.effect_uz,
                management_uz=it.management_uz,
                sources=it.sources,
            )
        )
        inter += 1
    if await get_meta(db, "aliases", None) is None:
        aliases = (
            yaml.safe_load((d / "_aliases.yaml").read_text(encoding="utf8"))
            if (d / "_aliases.yaml").is_file()
            else {}
        )
        await set_meta(db, "aliases", aliases or {})
    if await get_meta(db, "kb_version", None) is None:
        await set_meta(db, "kb_version", kb.version)
    await db.flush()
    return {"drugs_added": added, "interactions_added": inter}


# ---------------------------------------------------------------------------- engine integration
async def build_engine_kb(db: AsyncSession) -> tuple[DrugKB, str]:
    """Engine KB built from the DB (all statuses mapped; engine filters on kb_status/enabled).
    Returns (kb, fingerprint) so callers can cache and refresh cheaply."""
    rows = (await db.execute(select(KbDrug))).scalars().all()
    drugs: list[Drug] = []
    for r in rows:
        data = dict(r.data)
        data["kb_status"] = ENGINE_STATUS[r.status]
        if r.status == "published":
            data["enabled"] = True
        elif r.status == "archived":
            data["enabled"] = False
        try:
            drugs.append(Drug(**data))
        except Exception:  # noqa: S112 - a malformed row must not take the whole KB down
            continue
    inter = [
        Interaction(
            drug_a=i.drug_a,
            drug_b_or_class=i.drug_b,
            severity=i.severity,
            mechanism_uz=i.mechanism_uz,
            effect_uz=i.effect_uz,
            management_uz=i.management_uz,
            sources=i.sources or [],
        )
        for i in (await db.execute(select(KbInteraction))).scalars()
    ]
    aliases = await get_meta(db, "aliases", {})
    version = int(await get_meta(db, "kb_version", 1))
    stamp = (await db.execute(select(func.count(), func.max(KbDrug.updated_at)).select_from(KbDrug))).one()
    istamp = (
        await db.execute(select(func.count(), func.max(KbInteraction.updated_at)).select_from(KbInteraction))
    ).one()
    return DrugKB(
        drugs, inter, aliases or {}, version
    ), f"{version}|{stamp[0]}|{stamp[1]}|{istamp[0]}|{istamp[1]}"


# -------------------------------------------------------------------------------------- CSV import
IMPORT_COLUMNS = [
    "inn",
    "group",
    "atc_code",
    "trade_names",
    "forms",
    "indications_icd10",
    "population",
    "min_dose",
    "max_dose",
    "unit",
    "max_daily",
    "dose_note",
    "source_title",
    "source_url",
]


def _split(s: str | None) -> list[str]:
    return [x.strip() for x in re.split(r"[;|]", s or "") if x.strip()]


def parse_import(raw: bytes) -> tuple[list[tuple[int, DrugIn | None, str | None]], int]:
    if len(raw) > 2 * 1024 * 1024:
        raise AppError(413, "FILE_TOO_LARGE", "CSV 2 MB dan oshmasligi kerak")
    try:
        text_ = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(422, "VALIDATION_ERROR", "CSV UTF-8 kodlashda bo'lishi kerak")
    rd = csv.DictReader(io.StringIO(text_), delimiter=",")
    if not rd.fieldnames or "inn" not in [f.strip().lower() for f in rd.fieldnames]:
        raise AppError(422, "VALIDATION_ERROR", f"CSV ustunlari: {', '.join(IMPORT_COLUMNS)} (inn majburiy)")
    out: list[tuple[int, DrugIn | None, str | None]] = []
    for n, row in enumerate(rd, start=2):  # row 1 = header
        if n > 1001:
            raise AppError(422, "VALIDATION_ERROR", "Bir importda 1000 tadan ko'p qator bo'lmasin")
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            payload: dict[str, Any] = {
                "inn": r.get("inn", ""),
                "group": r.get("group", ""),
                "atc_code": r.get("atc_code") or None,
                "trade_names": _split(r.get("trade_names")),
                "forms": _split(r.get("forms")),
                "indications_icd10": _split(r.get("indications_icd10")),
                "dose_rules": [],
                "sources": [],
            }
            if r.get("min_dose") or r.get("max_dose"):
                payload["dose_rules"] = [
                    {
                        "population": r.get("population") or "adult",
                        "min_dose": float(r.get("min_dose") or 0),
                        "max_dose": float(r.get("max_dose") or 0),
                        "unit": r.get("unit", ""),
                        "max_daily": float(r["max_daily"]) if r.get("max_daily") else None,
                        "note": r.get("dose_note") or None,
                    }
                ]
            if r.get("source_url") or r.get("source_title"):
                payload["sources"] = [{"title": r.get("source_title", ""), "url": r.get("source_url", "")}]
            out.append((n, DrugIn(**payload), None))
        except Exception as exc:  # noqa: BLE001
            msg = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in getattr(exc, "errors", lambda: [])()
            ) or str(exc)
            out.append((n, None, msg[:300]))
    return out, len(out)


_ = (ATC_RE, csv)

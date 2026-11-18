from __future__ import annotations

import pytest
from sqlalchemy import select
from support import PASSWORD  # noqa: F401

from app.db import session as dbs
from app.models.system import AuditLog
from app.services import kb_service
from app.services.ai.drug_filter import build_candidates

BASE = {
    "inn": "Metoprolol test",
    "trade_names": ["Betalok"],
    "group": "beta_blockers",
    "atc_code": "C07AB02",
    "forms": ["tablet"],
    "indications_icd10": ["I10"],
    "dose_rules": [
        {
            "population": "adult",
            "min_dose": 25,
            "max_dose": 200,
            "unit": "mg",
            "max_daily": 400,
            "note": "kuniga 2 marta",
        }
    ],
    "contraindications": [{"text": "AV blokada", "absolute": True}],
    "side_effects": [{"text": "Bradikardiya", "frequency": "common"}],
    "interactions": [],
    "sources": [{"title": "ESC Guidelines", "url": "https://example.org/esc"}],
}


async def _seed():
    async with dbs.get_sessionmaker()() as s:
        res = await kb_service.seed_from_yaml(s)
        await s.commit()
    return res


async def test_rbac_and_seed(admin, doctor, nurse):
    res = await _seed()
    assert res["drugs_added"] == 16 and res["interactions_added"] == 27
    assert (await _seed()) == {"drugs_added": 0, "interactions_added": 0}  # idempotent
    for url in (
        "/admin/drugs",
        "/admin/drugs/groups",
        "/admin/drugs/interactions",
        "/admin/drugs/interactions/graph",
        "/admin/drugs/export",
    ):
        assert (await admin.get(url)).status_code == 200, url
        assert (await doctor.get(url)).status_code == 200, url
        assert (await nurse.get(url)).status_code == 403, url
    assert (await doctor.post("/admin/drugs", json=BASE)).status_code == 403
    assert (await nurse.post("/admin/drugs", json=BASE)).status_code == 403
    lst = (await doctor.get("/admin/drugs", params={"page_size": 5})).json()
    assert (
        lst["page"]["total"] == 16
        and len(lst["items"]) == 5
        and set(lst["items"][0]) == {"id", "inn", "trade_names", "group", "version", "status", "updated_at"}
    )
    assert all(i["status"] == "draft" for i in lst["items"])  # seeds are NOT clinically reviewed
    f = (await doctor.get("/admin/drugs", params={"q": "furosemide"})).json()["items"]
    assert [i["inn"] for i in f] == ["furosemide"]
    assert (await doctor.get("/admin/drugs", params={"group": "diuretics"})).json()["page"]["total"] >= 1
    assert (await doctor.get("/admin/drugs", params={"status": "bogus"})).status_code == 422
    d = (await doctor.get(f"/admin/drugs/{f[0]['id']}")).json()
    assert d["atc_code"] == "C03CA01" and d["dose_rules"][0]["unit"] and d["forms"] and d["interactions"]
    graph = (await admin.get("/admin/drugs/interactions/graph")).json()
    assert graph["nodes"] and graph["edges"]


async def test_create_validation_lifecycle_versions_audit(admin, doctor):
    for bad in (
        {"atc_code": "XYZ"},
        {"dose_rules": [{"population": "adult", "min_dose": 10, "max_dose": 5, "unit": "mg"}]},
        {"sources": [{"title": "x1", "url": "javascript:alert(1)"}]},
        {"inn": "A"},
        {"unknown": 1},
    ):
        r = await admin.post("/admin/drugs", json={**BASE, **bad})
        assert r.status_code == 422, bad
    r = await admin.post("/admin/drugs", json=BASE)
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "draft" and d["version"] == 1 and d["trade_names"] == ["Betalok"]
    assert (await admin.post("/admin/drugs", json={**BASE, "inn": "metoprolol TEST"})).json()["error"][
        "code"
    ] == "INN_TAKEN"
    # publish blockers
    bare = (await admin.post("/admin/drugs", json={"inn": "Bare drug", "group": "misc"})).json()
    pb = await admin.post(f"/admin/drugs/{bare['id']}/publish")
    assert pb.status_code == 422 and set(pb.json()["error"]["details"]["missing"]) == {
        "dose_rules",
        "sources",
    }
    pub = await admin.post(f"/admin/drugs/{d['id']}/publish")
    assert pub.status_code == 200 and pub.json()["status"] == "published"
    # editing a published drug creates a new version and returns it to draft (re-review)
    upd = await admin.put(
        f"/admin/drugs/{d['id']}", json={**BASE, "group": "beta_blockers", "side_effects": []}
    )
    assert upd.status_code == 200 and upd.json()["version"] == 2 and upd.json()["status"] == "draft"
    assert (await admin.put(f"/admin/drugs/{d['id']}", json={**BASE, "atc_code": "bad"})).status_code == 422
    await admin.post(f"/admin/drugs/{d['id']}/publish")
    vs = (await doctor.get(f"/admin/drugs/{d['id']}/versions")).json()["items"]
    assert [v["change"] for v in vs] == ["publish", "update", "publish", "create"] and vs[-1]["version"] == 1
    arch = (await admin.post(f"/admin/drugs/{d['id']}/archive")).json()
    assert arch["status"] == "archived"
    assert (await admin.put(f"/admin/drugs/{d['id']}", json=BASE)).json()["error"]["code"] == "DRUG_ARCHIVED"
    assert (await admin.post(f"/admin/drugs/{d['id']}/publish")).status_code == 409
    assert (await admin.get("/admin/drugs/00000000-0000-0000-0000-000000000000")).status_code == 404
    async with dbs.get_sessionmaker()() as s:
        acts = [
            (a.action.value, a.resource_type)
            for a in (await s.execute(select(AuditLog).where(AuditLog.resource_type == "drug"))).scalars()
        ]
        assert (
            acts.count(("create", "drug")) == 2
            and ("status_change", "drug") in acts
            and ("update", "drug") in acts
        )


async def test_interactions_are_symmetric_and_validated(admin):
    a = (await admin.post("/admin/drugs", json={**BASE, "inn": "Alpha drug"})).json()
    ix = {"drug_id": a["id"], "level": "major", "mechanism": "CYP3A4", "recommendation": "Birga bermang"}
    b = (await admin.post("/admin/drugs", json={**BASE, "inn": "Beta drug", "interactions": [ix]})).json()
    assert b["interactions"][0]["drug_name"] == "Alpha drug" and b["interactions"][0]["level"] == "major"
    a2 = (await admin.get(f"/admin/drugs/{a['id']}")).json()  # symmetric: visible from the other side
    assert a2["interactions"][0]["drug_name"] == "Beta drug" and a2["interactions"][0]["drug_id"] == b["id"]
    selfx = await admin.put(
        f"/admin/drugs/{a['id']}",
        json={**BASE, "inn": "Alpha drug", "interactions": [{**ix, "drug_id": a["id"]}]},
    )
    assert selfx.status_code == 422
    unknown = await admin.put(
        f"/admin/drugs/{a['id']}",
        json={**BASE, "inn": "Alpha drug", "interactions": [{**ix, "drug_id": "no_such_drug"}]},
    )
    assert unknown.status_code == 422
    cls = await admin.put(
        f"/admin/drugs/{a['id']}",
        json={**BASE, "inn": "Alpha drug", "interactions": [{**ix, "drug_id": "class:nsaids"}]},
    )
    assert cls.status_code == 200 and cls.json()["interactions"][0]["drug_id"] == "class:nsaids"
    assert (await admin.get(f"/admin/drugs/{b['id']}")).json()["interactions"] == []  # old pair removed


async def test_csv_import_dry_run_and_commit(admin, doctor):
    csv_text = (
        b"inn,group,atc_code,trade_names,forms,indications_icd10,population,min_dose,max_dose,unit,max_daily,dose_note,source_title,source_url\n"
        b"Ivabradine,antianginal,C01EB17,Procoralan,tablet,I20,adult,5,7.5,mg,15,kuniga 2 marta,ESC,https://example.org/esc\n"
        b"Bad Atc,misc,ZZZ,,,,adult,1,2,mg,,,Src1,https://example.org/x\n"
        b"Bad Dose,misc,,,,,adult,9,3,mg,,,Src1,https://example.org/x\n"
        b"Ivabradine,dup,,,,,,,,,,,,\n"
        b"Plain Draft,misc,,,,,,,,,,,,\n"
    )
    files = {"file": ("drugs.csv", csv_text, "text/csv")}
    r = await admin.post("/admin/drugs/import", params={"dry_run": "true"}, files=files)
    rep = r.json()
    assert (
        r.status_code == 200
        and rep["total"] == 5
        and rep["valid"] == 2
        and rep["created"] == 0
        and rep["dry_run"] is True
    )
    assert {e["row"] for e in rep["errors"]} == {3, 4, 5}
    assert (await admin.get("/admin/drugs")).json()["page"]["total"] == 0  # dry run wrote nothing
    real = (await admin.post("/admin/drugs/import", params={"dry_run": "false"}, files=files)).json()
    assert real["created"] == 2
    items = (await admin.get("/admin/drugs")).json()["items"]
    assert {i["inn"] for i in items} == {"Ivabradine", "Plain Draft"} and all(
        i["status"] == "draft" for i in items
    )
    assert (await doctor.post("/admin/drugs/import", files=files)).status_code == 403
    assert (
        await admin.post("/admin/drugs/import", files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")})
    ).status_code == 422
    exp = await doctor.get("/admin/drugs/export")
    assert exp.content.startswith(b"\xef\xbb\xbf") and b"Ivabradine" in exp.content


async def test_engine_reads_published_drugs_only(admin):
    await _seed()
    items = (await admin.get("/admin/drugs", params={"q": "furosemide"})).json()["items"]
    fid = items[0]["id"]
    d = (await admin.get(f"/admin/drugs/{fid}")).json()
    body = {
        k: d[k]
        for k in (
            "inn",
            "trade_names",
            "group",
            "atc_code",
            "forms",
            "indications_icd10",
            "dose_rules",
            "contraindications",
            "side_effects",
        )
    }
    body["interactions"] = d["interactions"]
    body["sources"] = [{"title": "ESC HF Guidelines 2021", "url": "https://example.org/esc-hf"}]
    assert (await admin.put(f"/admin/drugs/{fid}", json=body)).status_code == 200
    diff = [{"condition_code": "heart_failure", "probability": 0.8}]
    safety = {"age_years": 60, "sex": "male"}
    async with dbs.get_sessionmaker()() as s:
        kb, stamp1 = await kb_service.build_engine_kb(s)
    assert kb.drugs["furosemide"].kb_status == "draft"
    assert build_candidates(kb, safety, diff).by_id() == {}  # nothing published: engine proposes nothing
    assert (
        "furosemide" in build_candidates(kb, safety, diff, allow_draft=True).by_id()
    )  # CARDIOPCG_KB_ALLOW_DRAFT path
    assert (await admin.post(f"/admin/drugs/{fid}/publish")).status_code == 200
    async with dbs.get_sessionmaker()() as s:
        kb, stamp2 = await kb_service.build_engine_kb(s)
    assert (
        stamp1 != stamp2 and kb.drugs["furosemide"].kb_status == "reviewed" and kb.drugs["furosemide"].enabled
    )
    cands = build_candidates(kb, safety, diff).by_id()
    assert set(cands) == {"furosemide"}  # only the published drug is a candidate; other drafts stay out
    assert kb.drugs["furosemide"].interaction_classes == [
        "loop_diuretics"
    ]  # engine-only fields survive admin edits
    assert (await admin.post(f"/admin/drugs/{fid}/archive")).status_code == 200
    async with dbs.get_sessionmaker()() as s:
        kb, _ = await kb_service.build_engine_kb(s)
    assert (
        build_candidates(kb, safety, diff, allow_draft=True).by_id().get("furosemide") is None
    )  # retired is never proposed


@pytest.mark.parametrize("flag,expected", [("false", False), ("true", True)])
def test_allow_draft_env_flag(monkeypatch, flag, expected):
    from app.services.ai.config import AISettings

    monkeypatch.setenv("CARDIOPCG_KB_ALLOW_DRAFT", flag)
    assert AISettings.from_env().kb_allow_draft is expected

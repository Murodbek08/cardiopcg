from __future__ import annotations

import pytest
from fakes import FakeAnalysis
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from support import new_exam, new_patient, ready_exam, run_analysis

from app.db import session as dbs
from app.models.system import AuditLog
from app.services.analysis_port import set_analysis_service

CONCL = {
    "diagnosis_text": "MR",
    "icd10_codes": ["I34.0"],
    "final_pcg_class": "murmur",
    "final_severity": "moderate",
    "agreement_with_ai": "agree",
    "recommendations": "Exo-KG",
}


async def _complete(nurse, doctor, fake=None, concl=None):
    set_analysis_service(fake or FakeAnalysis())
    p, e = await ready_exam(nurse)
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    await doctor.post(f"/examinations/{e['id']}/prescription/approve")
    assert (await doctor.put(f"/examinations/{e['id']}/conclusion", json=concl or CONCL)).status_code == 200
    assert (await doctor.post(f"/examinations/{e['id']}/conclusion/sign")).status_code == 200
    return p, e


# ---------------------------------------------------------------------------------------- audit
async def test_each_mutation_writes_audit_and_masks_secrets(nurse, doctor, admin):
    p = await new_patient(nurse, national_id="31204755550012")
    e = await new_exam(nurse, p["id"])
    await doctor.patch(f"/patients/{p['id']}", json={"address": "Toshkent", "national_id": "99999999999999"})
    await doctor.get(f"/patients/{p['id']}")
    await admin.post(
        "/users",
        json={
            "username": "new.nurse",
            "full_name": "New Nurse",
            "role": "nurse",
            "password": "Aq9-Zx7-Pass-1!",
        },
    )
    rows = (await admin.get("/audit-logs", params={"limit": 200})).json()["items"]
    acts = [(r["action"], r["resource_type"]) for r in rows]
    for needed in (
        ("create", "patient"),
        ("create", "examination"),
        ("update", "patient"),
        ("read", "patient"),
        ("create", "user"),
        ("login", "user"),
    ):
        assert needed in acts, needed
    blob = str(rows)
    assert "31204755550012" not in blob and "99999999999999" not in blob and "Aq9-Zx7" not in blob
    upd = next(r for r in rows if r["action"] == "update" and r["resource_type"] == "patient")
    assert (
        upd["patient_id"] == p["id"]
        and upd["ip"] is not None
        and upd["method"] == "PATCH"
        and upd["user"]["role"] == "doctor"
    )
    assert upd["changes"]["after"]["national_id"] == "***"
    # patient access history (admin) and exam audit
    hist = (await admin.get(f"/patients/{p['id']}/audit")).json()["items"]
    assert {h["action"] for h in hist} >= {"create", "update", "read"}
    _ = e


async def test_audit_is_append_only(nurse):
    await new_patient(nurse)
    async with dbs.get_sessionmaker()() as s:
        assert (await s.execute(select(AuditLog.id))).first()
        for stmt in ("UPDATE audit_logs SET success=false", "DELETE FROM audit_logs", "TRUNCATE audit_logs"):
            with pytest.raises(DBAPIError):
                await s.execute(text(stmt))
            await s.rollback()


async def test_audit_scopes_and_filters(nurse, doctor, admin):
    await new_patient(nurse)
    await doctor.get("/patients")
    mine = (await doctor.get("/audit-logs")).json()["items"]
    assert mine and all(
        r["user"]["username"] == "doctor.main" for r in mine
    )  # doctors only see their own actions
    assert (await nurse.get("/audit-logs")).status_code == 403
    f = (await admin.get("/audit-logs", params={"action": "create", "resource_type": "patient"})).json()[
        "items"
    ]
    assert len(f) == 1
    p1 = (await admin.get("/audit-logs", params={"limit": 2})).json()
    p2 = (await admin.get("/audit-logs", params={"limit": 2, "cursor": p1["page"]["next_cursor"]})).json()
    assert {r["id"] for r in p1["items"]}.isdisjoint({r["id"] for r in p2["items"]})
    csv = await admin.get("/audit-logs/export", params={"format": "csv"})
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf") and b"create" in csv.content
    assert (await doctor.get("/audit-logs/export")).status_code == 403


async def test_settings_validation_public_and_audit(admin, nurse):
    r = await admin.patch("/settings", json={"upload.max_audio_mb": 30, "ai.llm_enabled": False})
    assert r.status_code == 200
    assert (await admin.patch("/settings", json={"upload.max_audio_mb": "lots"})).status_code == 422
    assert (await admin.patch("/settings", json={"upload.max_audio_mb": 99999})).status_code == 422
    assert (await admin.patch("/settings", json={"no.such": 1})).status_code == 422
    pub = (await nurse.get("/settings/public")).json()
    assert pub["upload.max_audio_mb"] == 30 and "ai.llm_enabled" not in pub and pub["clinic.name"]
    assert (await nurse.patch("/settings", json={"ai.llm_enabled": True})).status_code == 403
    logs = (await admin.get("/audit-logs", params={"action": "settings_change"})).json()["items"]
    assert logs and logs[0]["changes"]["after"]["ai.llm_enabled"] is False


async def test_users_admin_rules(admin, doctor):
    me_id = str(admin.id)
    assert (await admin.delete(f"/users/{me_id}")).status_code == 409  # cannot delete self / last admin
    assert (await admin.patch(f"/users/{me_id}", json={"role": "doctor"})).status_code == 409
    u = (
        await admin.post(
            "/users",
            json={
                "username": "dup.user",
                "full_name": "Dup User",
                "role": "nurse",
                "password": "Aq9-Zx7-Pass-1!",
            },
        )
    ).json()
    assert (
        await admin.post(
            "/users",
            json={
                "username": "dup.user",
                "full_name": "Other",
                "role": "nurse",
                "password": "Aq9-Zx7-Pass-1!",
            },
        )
    ).status_code == 409
    assert (
        await admin.post(
            "/users",
            json={"username": "weak.pw", "full_name": "Weak", "role": "nurse", "password": "password123"},
        )
    ).json()["error"]["code"] == "WEAK_PASSWORD"
    docs = (await doctor.get("/users/doctors")).json()
    assert any(d["id"] == str(doctor.id) for d in docs) and set(docs[0]) == {"id", "full_name", "specialty"}
    assert (await admin.post(f"/users/{u['id']}/suspend")).json()["status"] == "suspended"
    assert (await admin.delete(f"/users/{u['id']}")).status_code == 204
    lst = (await admin.get("/users", params={"q": "dup"})).json()
    assert lst["page"]["total"] == 0


# ------------------------------------------------------------------------------------- analytics
async def test_analytics_numbers_match_fixture(nurse, doctor, admin):
    # 3 exams: A (agree, murmur), B (disagree: AI murmur / final normal), C pending review
    await _complete(nurse, doctor)
    await _complete(
        nurse,
        doctor,
        concl=dict(
            CONCL,
            final_pcg_class="normal",
            final_severity="none",
            agreement_with_ai="disagree",
            disagreement_reason="ovoz artefakt",
        ),
    )
    set_analysis_service(FakeAnalysis())
    _, e3 = await ready_exam(nurse)
    assert await run_analysis(nurse, e3["id"]) == "succeeded"

    k = (await admin.get("/analytics/admin/kpis")).json()["kpis"]
    assert k["total_patients"]["value"] == 3 and k["new_patients"]["value"] == 3
    assert k["examinations_total"]["value"] == 3 and k["examinations_completed"]["value"] == 2
    assert k["pending_review"]["value"] == 1
    assert k["abnormal_rate_pct"]["value"] == 100.0
    assert k["ai_doctor_agreement_pct"]["value"] == 50.0
    assert k["avg_ai_processing_sec"]["value"] is not None
    assert k["llm_cost_usd"]["value"] == pytest.approx(0.0036, abs=1e-6)  # 3 reports x 0.0012
    assert k["storage_used_gb"]["value"] >= 0 and k["active_users"]["value"] >= 3

    ts = (await admin.get("/analytics/admin/timeseries", params={"metric": "examinations"})).json()
    assert sum(s["value"] for s in ts["series"]) == 3 and len(ts["series"]) == 30
    grp = (
        await admin.get(
            "/analytics/admin/timeseries", params={"metric": "examinations", "group_by": "status"}
        )
    ).json()
    assert set(grp["series_by"]) == {"completed", "ai_ready"}
    dist = (await admin.get("/analytics/admin/distributions", params={"dimension": "pcg_class"})).json()
    assert dist["total"] == 3 and dist["items"][0] == {"key": "murmur", "count": 3, "pct": 100.0}
    ag = (await admin.get("/analytics/admin/distributions", params={"dimension": "age_group"})).json()
    assert (
        ag["items"][0]["key"] == "40-59"
        or ag["items"][0]["key"] == "60-74"
        or ag["items"][0]["key"] == "40-59"
    )
    assert (
        await admin.get("/analytics/admin/distributions", params={"dimension": "drop table"})
    ).status_code == 422
    wl = (await admin.get("/analytics/admin/workload")).json()
    d = next(x for x in wl["doctors"] if x["full_name"].startswith("Doctor"))
    assert d["completed"] == 2 and d["agreement_pct"] == 50.0 and wl["queue"]["ai_ready"] == 1
    n = next(x for x in wl["nurses"] if x["exams_created"])
    assert n["exams_created"] == 3 and n["recordings_uploaded"] == 3 and n["avg_recordings_per_exam"] == 1.0
    hm = (await admin.get("/analytics/admin/heatmap")).json()["items"]
    assert sum(i["value"] for i in hm) == 3
    perf = (await admin.get("/analytics/admin/ai-performance")).json()
    mv = perf["model_versions"][0]
    assert mv["n"] == 2 and mv["agreement_pct"] == 50.0 and mv["disagree_pct"] == 50.0
    cm = mv["confusion_matrix"]
    labels = cm["labels"]
    assert (
        cm["matrix"][labels.index("murmur")][labels.index("murmur")] == 1
        and cm["matrix"][labels.index("normal")][labels.index("murmur")] == 1
    )
    assert perf["llm"]["total_tokens"] == 450
    sysm = (await admin.get("/analytics/admin/system")).json()
    assert sysm["api_latency_ms"]["p95"] is not None

    dk = (await doctor.get("/analytics/doctor/kpis")).json()["kpis"]
    assert (
        dk["my_completed_period"]["value"] == 2
        and dk["my_pending"]["value"] == 0
        and dk["ai_agreement_pct"]["value"] == 50.0
    )
    assert dk["overrides_count"]["value"] == 1 and dk["patients_seen"]["value"] == 2
    q = (await doctor.get("/analytics/doctor/queue")).json()["items"]
    assert len(q) == 1 and q[0]["ai_class"] == "murmur"
    av = (await doctor.get("/analytics/doctor/ai-vs-doctor")).json()
    assert (
        av["total"] == 2
        and av["disagree"] == 1
        and av["disagreements"][0]["final_class"] == "normal"
        and av["weighted_agreement_pct"] == 50.0
    )
    dd = (await doctor.get("/analytics/doctor/distributions", params={"dimension": "final_pcg_class"})).json()
    assert {i["key"]: i["count"] for i in dd["items"]} == {"murmur": 1, "normal": 1}
    assert (await doctor.get("/analytics/doctor/timeseries", params={"metric": "completed"})).json()[
        "series"
    ][-1]["value"] == 2
    nk = (await nurse.get("/analytics/nurse/kpis")).json()
    assert nk["exams_created_period"] == 3 and nk["recordings_uploaded"] == 3 and nk["awaiting_ai"] == 0
    # scopes
    assert (await doctor.get("/analytics/admin/kpis")).status_code == 403
    assert (await nurse.get("/analytics/doctor/kpis")).status_code == 403
    assert (
        await doctor.get("/analytics/doctor/kpis", params={"doctor_id": str(admin.id)})
    ).status_code == 403
    assert (await admin.get("/analytics/doctor/kpis", params={"doctor_id": str(doctor.id)})).json()["kpis"][
        "my_completed_period"
    ]["value"] == 2
    assert (await admin.get("/analytics/admin/kpis", params={"tz": "Mars/Base"})).status_code == 422
    assert (
        await admin.get("/analytics/admin/kpis", params={"from": "2030-01-02", "to": "2030-01-01"})
    ).status_code == 422


async def test_analytics_cache_and_invalidation(nurse, doctor, admin, monkeypatch):
    monkeypatch.setenv("ANALYTICS_CACHE_TTL", "60")
    from app.config import reset_settings_cache

    reset_settings_cache()
    await _complete(nurse, doctor)
    first = (await admin.get("/analytics/admin/kpis")).json()["kpis"]["examinations_completed"]["value"]
    await new_patient(admin, last_name="Cache", first_name="Test")
    cached = (await admin.get("/analytics/admin/kpis")).json()["kpis"]["total_patients"]["value"]
    assert first == 1 and cached == 1  # stale by design within TTL
    await _complete(nurse, doctor)  # sign invalidates analytics:* keys
    fresh = (await admin.get("/analytics/admin/kpis")).json()["kpis"]
    assert fresh["examinations_completed"]["value"] == 2 and fresh["total_patients"]["value"] == 3
    reset_settings_cache()

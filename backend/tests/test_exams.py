"""Examination CRUD + status state machine (unit table + API)."""

from __future__ import annotations

import itertools

import pytest
from fakes import FakeAnalysis
from sqlalchemy import select
from support import make_wav, new_exam, new_patient, ready_exam, run_analysis, upload

from app.db import session as dbs
from app.models.enums import ExamStatus
from app.models.examination import ExamStatusHistory
from app.models.system import AuditLog
from app.services import exam_state
from app.services.analysis_port import set_analysis_service

S = ExamStatus


def test_transition_table_is_exhaustive_and_sane():
    allowed = set(exam_state.TRANSITIONS)
    # terminal states have no outgoing edges
    assert not [t for t in allowed if t[0] in (S.completed, S.cancelled)]
    # completed is only reachable from in_review by a doctor
    assert {k: v for k, v in exam_state.TRANSITIONS.items() if k[1] == S.completed} == {
        (S.in_review, S.completed): {"doctor"}
    }
    # nurses may only cancel draft/uploaded
    nurse_cancel = {
        f for (f, t), who in exam_state.TRANSITIONS.items() if t == S.cancelled and "nurse" in who
    }
    assert nurse_cancel == {S.draft, S.uploaded}
    for a, b in itertools.product(S, S):
        if (a, b) not in allowed:
            assert exam_state.allowed_targets(a, "doctor") == sorted(
                t.value for (f, t), w in exam_state.TRANSITIONS.items() if f == a and "doctor" in w
            )


async def test_create_validation(nurse, doctor):
    p = await new_patient(nurse)
    bad = await nurse.post(
        "/examinations", json={"patient_id": p["id"], "bp_systolic": 80, "bp_diastolic": 90}
    )
    assert bad.status_code == 422
    assert (
        await nurse.post("/examinations", json={"patient_id": p["id"], "symptoms": ["nonsense"]})
    ).status_code == 422
    e = await new_exam(
        nurse,
        p["id"],
        heart_rate_bpm=88,
        bp_systolic=135,
        bp_diastolic=85,
        symptoms=["dyspnea"],
        assigned_doctor_id=doctor.id.__str__(),
    )
    assert e["status"] == "draft" and e["exam_no"].startswith("E-") and e["assigned_doctor"]["full_name"]
    e2 = await new_exam(nurse, p["id"])
    assert e2["exam_no"] != e["exam_no"] and e2["exam_no"].endswith("-0002")
    async with dbs.get_sessionmaker()() as s:
        hist = (await s.execute(select(ExamStatusHistory))).scalars().all()
        assert len(hist) == 2 and all(h.from_status is None and h.to_status == S.draft for h in hist)


async def test_full_state_machine_via_api(nurse, doctor, admin):
    fake = FakeAnalysis()
    set_analysis_service(fake)
    p, e = await ready_exam(nurse)
    eid = e["id"]
    st = lambda: None  # noqa: E731
    assert (await nurse.get(f"/examinations/{eid}/status")).json()["status"] == "uploaded"
    # cannot sign / conclude before analysis
    assert (await doctor.post(f"/examinations/{eid}/conclusion/sign")).status_code in (409, 422)
    assert await run_analysis(nurse, eid) == "succeeded"
    s = (await nurse.get(f"/examinations/{eid}/status")).json()
    assert s["status"] == "ai_ready" and [h["to"] for h in s["history"]] == [
        "draft",
        "uploaded",
        "queued",
        "processing",
        "ai_ready",
    ]
    # invalid transitions give 409 INVALID_STATE with details
    r = await nurse.post(f"/examinations/{eid}/analyze")
    assert (
        r.status_code == 409
        and r.json()["error"]["code"] == "INVALID_STATE"
        and r.json()["error"]["details"]["current"] == "ai_ready"
    )
    # nurse cannot cancel an analysed exam / rerun
    assert (await nurse.post(f"/examinations/{eid}/cancel", json={"reason": "x"})).status_code in (403, 409)
    assert (await nurse.post(f"/examinations/{eid}/reanalyze")).status_code == 403
    assert (await nurse.post(f"/examinations/{eid}/analyze", json={"force_rerun": True})).status_code == 403
    # doctor opens -> in_review, reanalyze -> queued again, then cancel
    assert (await doctor.get(f"/examinations/{eid}/report")).status_code == 200
    assert (await nurse.get(f"/examinations/{eid}/status")).json()["status"] == "in_review"
    assert (await doctor.post(f"/examinations/{eid}/reanalyze")).status_code == 202
    assert (await nurse.get(f"/examinations/{eid}/status")).json()["status"] == "queued"
    r = await doctor.post(f"/examinations/{eid}/cancel", json={"reason": "bemor ketdi"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # terminal: nothing else allowed
    assert (await doctor.post(f"/examinations/{eid}/cancel", json={"reason": "x"})).status_code == 409
    assert (await admin.delete(f"/examinations/{eid}")).status_code == 204
    _ = st
    async with dbs.get_sessionmaker()() as s2:
        n = (
            (
                await s2.execute(
                    select(AuditLog).where(
                        AuditLog.action == "status_change",
                        AuditLog.resource_id == __import__("uuid").UUID(eid),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(n) >= 7


async def test_nurse_cancel_rules_and_update_lock(nurse, doctor):
    p = await new_patient(nurse)
    e = await new_exam(nurse, p["id"])
    assert (await nurse.patch(f"/examinations/{e['id']}", json={"complaints": "yangi"})).status_code == 200
    assert (
        await nurse.post(f"/examinations/{e['id']}/assign", json={"doctor_id": str(doctor.id)})
    ).status_code == 200
    r = await nurse.post(f"/examinations/{e['id']}/cancel", json={"reason": "xato"})
    assert r.status_code == 200
    assert (await nurse.patch(f"/examinations/{e['id']}", json={"complaints": "again"})).status_code == 403
    assert (await doctor.patch(f"/examinations/{e['id']}", json={"complaints": "again"})).status_code == 409


async def test_delete_last_audio_returns_to_draft(nurse):
    _, e = await ready_exam(nurse)
    rid = (await nurse.get(f"/examinations/{e['id']}/recordings")).json()[0]["id"]
    assert (await nurse.delete(f"/recordings/{rid}")).status_code == 204
    assert (await nurse.get(f"/examinations/{e['id']}/status")).json()["status"] == "draft"
    assert (await nurse.post(f"/examinations/{e['id']}/analyze")).status_code == 409


async def test_analyze_preconditions_and_idempotency(nurse):
    set_analysis_service(FakeAnalysis())
    p = await new_patient(nurse)
    e = await new_exam(nurse, p["id"])
    assert (await nurse.post(f"/examinations/{e['id']}/analyze")).status_code == 409  # draft
    assert (await upload(nurse, e["id"])).status_code == 201
    h = {"Idempotency-Key": "key-123456789"}
    a = await nurse.post(f"/examinations/{e['id']}/analyze", headers=h)
    b = await nurse.post(f"/examinations/{e['id']}/analyze", headers=h)
    assert (
        a.status_code == b.status_code == 202
        and a.json()["job_id"] == b.json()["job_id"]
        and b.headers["idempotent-replay"] == "true"
    )


async def test_auto_start_setting(admin, nurse):
    assert (await admin.patch("/settings", json={"analysis.auto_start": True})).status_code == 200
    p = await new_patient(nurse)
    e = await new_exam(nurse, p["id"])
    assert (await upload(nurse, e["id"])).status_code == 201
    assert (await nurse.get(f"/examinations/{e['id']}/status")).json()["status"] == "queued"


async def test_list_filters_and_priority_sort(doctor, nurse):
    p = await new_patient(nurse)
    await new_exam(nurse, p["id"], priority="routine")
    await new_exam(nurse, p["id"], priority="emergency")
    await new_exam(nurse, p["id"], priority="urgent")
    items = (await doctor.get("/examinations", params={"sort": "-priority"})).json()["items"]
    assert [i["priority"] for i in items] == ["emergency", "urgent", "routine"]
    r1 = (
        await doctor.get("/examinations", params={"limit": 2, "sort": "-priority", "with_total": "true"})
    ).json()
    r2 = (
        await doctor.get(
            "/examinations", params={"limit": 2, "sort": "-priority", "cursor": r1["page"]["next_cursor"]}
        )
    ).json()
    assert r1["page"]["total"] == 3 and len(r2["items"]) == 1 and r2["items"][0]["priority"] == "routine"
    assert (
        len((await doctor.get("/examinations", params={"status": ["draft", "uploaded"]})).json()["items"])
        == 3
    )
    assert (await doctor.get("/examinations", params={"needs_review": "true"})).json()["items"] == []
    assert len((await doctor.get("/examinations", params={"q": "rahim"})).json()["items"]) == 3
    _ = pytest, make_wav

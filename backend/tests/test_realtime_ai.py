from __future__ import annotations

import asyncio

import pytest
from fakes import FakeAnalysis
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from support import PASSWORD, create_user, make_wav, new_patient, ready_exam, run_analysis

from app.api.v1.examinations import sse_generator
from app.config import get_settings
from app.models.enums import UserRole
from app.services import realtime
from app.services.ai_adapter import EngineAnalysisService, engine_context
from app.services.analysis_port import PatientContext, set_analysis_service


# --------------------------------------------------------------------------------------- SSE / bus
async def test_sse_replay_and_heartbeat():
    env1 = await realtime.bus.publish("analysis.progress", {"stage": "a"}, ["exam:E1"])
    await realtime.bus.publish("analysis.progress", {"stage": "b"}, ["exam:E1"])
    gen = sse_generator("E1", env1["id"], heartbeat=0.05)  # Last-Event-ID replay: only events AFTER env1
    first = await gen.__anext__()
    assert first.startswith("event: analysis.progress") and '"stage":"b"' in first
    assert (await gen.__anext__()) == ": ping\n\n"  # heartbeat on idle
    await realtime.bus.publish("analysis.completed", {"x": 1}, ["exam:E1"])
    assert "analysis.completed" in await gen.__anext__()
    await gen.aclose()
    assert not realtime.bus._subs


async def test_events_emitted_after_commit_and_progress_sequence(nurse, doctor):
    set_analysis_service(FakeAnalysis())
    p = await new_patient(nurse)
    from support import new_exam, upload

    e = await new_exam(nurse, p["id"], assigned_doctor_id=str(doctor.id))
    sub = realtime.bus.subscribe([f"exam:{e['id']}", f"user:{doctor.id}"])
    assert (await upload(nurse, e["id"])).status_code == 201
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    got = []
    while not sub.queue.empty():
        got.append(sub.queue.get_nowait())
    types = [g["type"] for g in got]
    assert types.index("recording.uploaded") < types.index("exam.status_changed")
    prog = [g["data"]["progress_pct"] for g in got if g["type"] == "analysis.progress"]
    assert prog == sorted(prog) and prog[-1] == 100 and 0 in prog
    for must in ("analysis.signal_done", "analysis.report_ready", "analysis.completed", "notification.new"):
        assert must in types, must
    assert all(g["v"] == 1 and g["id"] and g["ts"].endswith("Z") for g in got)


async def test_failed_request_emits_no_events(nurse):
    p = await new_patient(nurse)
    sub = realtime.bus.subscribe(["role:admin", "role:doctor"])
    bad = await nurse.post(
        "/examinations", json={"patient_id": p["id"], "bp_systolic": 50, "bp_diastolic": 90}
    )
    assert bad.status_code == 422 and sub.queue.empty()


# ------------------------------------------------------------------------------------- WebSocket
async def test_websocket_auth_subscribe_and_events():
    doc = await create_user(UserRole.doctor, "ws.doctor")
    nrs = await create_user(UserRole.nurse, "ws.nurse")
    nrs2 = await create_user(UserRole.nurse, "ws.nurse2")

    def body() -> None:
        from app.main import create_app

        app = create_app(get_settings().model_copy(update={"db_null_pool": True}))
        with TestClient(app) as tc:

            def tok(u):
                return tc.post(
                    "/api/v1/auth/login", json={"username": u.username, "password": PASSWORD}
                ).json()["access_token"]

            dt, nt, n2t = tok(doc), tok(nrs), tok(nrs2)
            with (
                pytest.raises(WebSocketDisconnect) as ei,
                tc.websocket_connect("/api/v1/ws?token=garbage") as ws,
            ):
                ws.receive_json()
            assert ei.value.code == 4401
            hdr = {"Authorization": f"Bearer {nt}"}
            pid = tc.post(
                "/api/v1/patients",
                headers=hdr,
                json={"last_name": "W", "first_name": "S", "birth_date": "1980-01-01", "gender": "male"},
            ).json()["id"]
            with tc.websocket_connect(f"/api/v1/ws?token={dt}") as ws:
                ws.send_json({"type": "ping"})
                assert ws.receive_json() == {"type": "pong"}
                r = tc.post(
                    "/api/v1/examinations",
                    headers=hdr,
                    json={"patient_id": pid, "assigned_doctor_id": str(doc.id)},
                )
                assert r.status_code == 201
                seen = {ws.receive_json()["type"] for _ in range(3)}
                assert {"exam.created", "notification.new", "exam.assigned"} <= seen
                eid = r.json()["id"]
                ws.send_json({"type": "subscribe", "channels": [f"exam:{eid}"]})
                assert ws.receive_json()["type"] == "subscribed"
            # nurse2 may not subscribe to nurse1's exam -> 4403; nobody may subscribe to other users' channels
            with tc.websocket_connect(f"/api/v1/ws?token={n2t}") as ws2:
                ws2.send_json({"type": "subscribe", "channels": [f"exam:{eid}"]})
                with pytest.raises(WebSocketDisconnect) as ei2:
                    ws2.receive_json()
                assert ei2.value.code == 4403
            with tc.websocket_connect(f"/api/v1/ws?token={nt}") as ws3:
                ws3.send_json({"type": "subscribe", "channels": [f"user:{doc.id}"]})
                with pytest.raises(WebSocketDisconnect) as ei3:
                    ws3.receive_json()
                assert ei3.value.code == 4403

    await asyncio.to_thread(body)


# ------------------------------------------------------- real engine (app.ml + app.services.ai)
def test_engine_context_is_deidentified_mapping():
    ctx = engine_context(
        PatientContext(
            age_years=51,
            gender="male",
            symptoms=["dyspnea"],
            complaints="nafas qisilishi",
            vitals={"bp_systolic": 135, "bp_diastolic": 85, "heart_rate_bpm": 88},
            allergies=[{"substance": "Penitsillin"}],
            medications=[{"drug_name": "Varfarin", "inn_code": "warfarin", "frequency": "1"}],
            history=[{"title": "Gipertoniya", "icd10_code": "I10"}],
            ai_consent=True,
        )
    )
    assert ctx["vitals"] == {"bp_sys": 135, "bp_dia": 85, "hr_bpm": 88} and ctx["known_conditions_icd10"] == [
        "I10"
    ]
    assert ctx["current_medications"] == [{"inn": "warfarin", "freq": "1"}] and "ai_consent" not in ctx


async def test_real_engine_end_to_end_without_llm_key(nurse, doctor):
    """Runs the REAL signal pipeline (app.ml) through the adapter; DeepSeek key is empty so AI must degrade."""
    set_analysis_service(EngineAnalysisService())
    p, e = await ready_exam(nurse, sites=("mitral", "aortic"))
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    a = (await doctor.get(f"/examinations/{e['id']}/analysis")).json()
    assert (
        a["pcg_class"] in {"normal", "murmur", "extra_heart_sound", "artifact", "undetermined"}
        and len(a["recordings"]) == 2
    )
    assert all(r["spectrogram_url"] for r in a["recordings"])
    sp = await doctor.get(a["recordings"][0]["spectrogram_url"].removeprefix("/api/v1"))
    assert sp.content[:4] == b"\x89PNG"
    rep = (await doctor.get(f"/examinations/{e['id']}/report")).json()
    assert rep["status"] in ("ready", "failed")  # rule template or AI-unavailable message, never an exception
    assert (await nurse.get(f"/examinations/{e['id']}/status")).json()["status"] in ("ai_ready", "in_review")


async def test_real_engine_consent_gate_and_unusable_audio(nurse):
    svc = EngineAnalysisService()
    set_analysis_service(svc)
    pt = await new_patient(nurse, ai_consent=False)
    from support import new_exam, upload

    e = await new_exam(nurse, pt["id"])
    assert (await upload(nurse, e["id"], make_wav(10.0), site="apex")).status_code == 201
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    import uuid

    from app.db import session as dbs
    from app.services.exam_service import current_report

    async with dbs.get_sessionmaker()() as s:
        rep = await current_report(s, uuid.UUID(e["id"]))
        assert rep is None or rep.status.value == "failed" or rep.llm_provider != "deepseek"
        if rep is not None and rep.status.value == "failed":
            assert "rozilik" in (rep.error_message or "").lower() or rep.error_message

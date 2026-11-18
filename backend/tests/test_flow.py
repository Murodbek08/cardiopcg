"""End-to-end clinical flow with the fake analysis engine: worker, report, drugs, conclusion, PDF, CSV, analytics."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fakes import FakeAnalysis
from sqlalchemy import select, update
from support import make_wav, new_exam, new_patient, ready_exam, run_analysis, upload

from app.db import session as dbs
from app.db.base import utcnow
from app.models.analysis import AnalysisJob
from app.models.clinical import AiReport
from app.models.enums import JobStatus
from app.models.system import AuditLog
from app.services import analysis_service, maintenance
from app.services.analysis_port import AnalysisRequest, set_analysis_service

CONCL = {
    "diagnosis_text": "Mitral yetishmovchilik (ehtimoliy)",
    "icd10_codes": ["I34.0"],
    "final_pcg_class": "murmur",
    "final_severity": "moderate",
    "agreement_with_ai": "agree",
    "recommendations": "Exo-KG, 2 haftadan so'ng nazorat",
    "follow_up_date": (utcnow() + timedelta(days=5)).date().isoformat(),
}


async def _analysed(nurse, fake=None, sites=("mitral",)):
    fake = fake or FakeAnalysis()
    set_analysis_service(fake)
    p, e = await ready_exam(nurse, sites)
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    return p, e, fake


async def test_worker_persists_signal_segments_artifacts(nurse, doctor):
    p, e, fake = await _analysed(nurse, sites=("mitral", "aortic"))
    eid = e["id"]
    a = (await doctor.get(f"/examinations/{eid}/analysis")).json()
    assert a["pcg_class"] == "murmur" and a["severity"] == "moderate" and len(a["recordings"]) == 2
    assert all(r["spectrogram_url"] for r in a["recordings"])
    segs = (await doctor.get(f"/examinations/{eid}/segments")).json()["items"]
    assert [s["type"] for s in segs] == ["S1", "S2"]  # invalid segment dropped
    sp = await doctor.get(a["recordings"][0]["spectrogram_url"].removeprefix("/api/v1"))
    assert sp.status_code == 200 and sp.content[:4] == b"\x89PNG"
    wf = (
        await doctor.get(
            f"/recordings/{(await doctor.get(f'/examinations/{eid}/recordings')).json()[0]['id']}/waveform"
        )
    ).json()
    assert wf["data"] == [-0.5, 0.5, -0.2, 0.3]
    rep = (await doctor.get(f"/examinations/{eid}/report")).json()
    assert rep["summary"] and rep["disclaimer"] and rep["status"] == "ready"
    # de-identified request: no name / phone / address / national id / MRN reaches the AI layer
    req: AnalysisRequest = fake.requests[0]
    blob = req.model_dump_json()
    for secret in ("Rahimov", "Jasur", p["mrn"], "+998"):
        assert secret not in blob
    assert req.patient.ai_consent is True and req.patient.age_years >= 50
    async with dbs.get_sessionmaker()() as s:
        ai = (await s.execute(select(AuditLog).where(AuditLog.action == "ai_call"))).scalars().all()
        assert len(ai) == 1 and ai[0].meta["model"] == "fake-llm" and "Rahimov" not in json.dumps(ai[0].meta)
        r = (await s.execute(select(AiReport))).scalar_one()
        assert "Rahimov" not in json.dumps(r.input_snapshot)


async def test_llm_failure_keeps_exam_ai_ready_and_regenerate(nurse, doctor):
    fake = FakeAnalysis()
    fake.llm_fail = True
    _, e, _ = await _analysed(nurse, fake)
    st = (await nurse.get(f"/examinations/{e['id']}/status")).json()["status"]
    assert st == "ai_ready"
    rep = await doctor.get(f"/examinations/{e['id']}/report")
    assert rep.json()["status"] == "failed" and rep.json()["error_message"]
    fake.llm_fail = False
    r = await doctor.post(f"/examinations/{e['id']}/report/regenerate")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    hist = (await doctor.get(f"/examinations/{e['id']}/report/history")).json()
    assert len(hist) == 2
    assert (await nurse.post(f"/examinations/{e['id']}/report/regenerate")).status_code == 403


async def test_deterministic_and_transient_failures(nurse, admin):
    fake = FakeAnalysis()
    fake.fail_code = "AUDIO_CORRUPT"
    set_analysis_service(fake)
    _, e = await ready_exam(nurse)
    assert await run_analysis(nurse, e["id"]) == "failed"
    assert len(fake.requests) == 1  # no retry for deterministic errors
    assert (await nurse.get(f"/examinations/{e['id']}/status")).json()["status"] == "failed"
    n = (await nurse.get("/notifications")).json()["items"]
    assert any(i["type"] == "analysis_failed" for i in n)
    # transient: retried then success
    fake2 = FakeAnalysis()
    fake2.transient_failures = 2
    set_analysis_service(fake2)
    _, e2 = await ready_exam(nurse)
    assert await run_analysis(nurse, e2["id"]) == "succeeded" and len(fake2.requests) == 3
    # transient exhausted
    fake3 = FakeAnalysis()
    fake3.transient_failures = 9
    set_analysis_service(fake3)
    _, e3 = await ready_exam(nurse)
    assert await run_analysis(nurse, e3["id"]) == "failed" and len(fake3.requests) == 3
    # failed -> reanalyze by admin works
    fake3.transient_failures = 0
    r = await admin.post(f"/examinations/{e3['id']}/reanalyze")
    assert r.status_code == 202
    assert await analysis_service.run_job(r.json()["job_id"]) == "succeeded"


async def test_job_idempotent_and_cancel(nurse, doctor):
    set_analysis_service(FakeAnalysis())
    _, e = await ready_exam(nurse)
    r = await nurse.post(f"/examinations/{e['id']}/analyze")
    jid = r.json()["job_id"]
    assert await analysis_service.run_job(jid) == "succeeded"
    assert await analysis_service.run_job(jid) == "skipped"  # second delivery of the same task is a no-op
    _, e2 = await ready_exam(nurse)
    r2 = await nurse.post(f"/examinations/{e2['id']}/analyze")
    assert (await doctor.post(f"/examinations/{e2['id']}/cancel", json={"reason": "x"})).status_code == 200
    assert await analysis_service.run_job(r2.json()["job_id"]) == "skipped"


async def test_reap_stuck_jobs(nurse):
    set_analysis_service(FakeAnalysis())
    _, e = await ready_exam(nurse)
    r = await nurse.post(f"/examinations/{e['id']}/analyze")
    jid = uuid.UUID(r.json()["job_id"])
    async with dbs.get_sessionmaker()() as s:  # simulate a worker that died mid-run
        from app.models.enums import ExamStatus
        from app.models.examination import Examination

        await s.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == jid)
            .values(status=JobStatus.running, updated_at=utcnow() - timedelta(minutes=30))
        )
        await s.execute(
            update(Examination)
            .where(Examination.id == uuid.UUID(e["id"]))
            .values(status=ExamStatus.processing)
        )
        await s.commit()
    assert await analysis_service.reap_stuck_jobs() == 1
    st = (await nurse.get(f"/examinations/{e['id']}/status")).json()
    assert st["status"] == "queued" and st["job"]["attempt"] == 2
    assert await analysis_service.run_job(st["job"]["id"]) == "succeeded"


async def test_critical_notification_and_events(nurse, doctor, admin):
    fake = FakeAnalysis()
    fake.severity, fake.red_flags = "severe", ["sinkopa"]
    _, e, _ = await _analysed(nurse, fake)
    for who in (doctor, admin):
        types = [n["type"] for n in (await who.get("/notifications")).json()["items"]]
        assert "critical_finding" in types and "analysis_done" in types or who is admin
    assert (await doctor.get("/notifications/unread-count")).json()["count"] >= 2
    nid = (await doctor.get("/notifications")).json()["items"][0]["id"]
    assert (await doctor.post(f"/notifications/{nid}/read")).status_code == 204
    assert (await doctor.post("/notifications/read-all")).status_code == 204
    assert (await doctor.get("/notifications/unread-count")).json()["count"] == 0
    assert (await nurse.post(f"/notifications/{nid}/read")).status_code == 404  # not yours


async def test_prescription_safety_and_approval_flow(nurse, doctor):
    fake = FakeAnalysis()
    from app.services.analysis_port import DrugSuggestion

    fake.drugs = [
        DrugSuggestion(
            drug_name="Amoksitsillin", inn_code="amoxicillin", dose="500 mg", frequency="kuniga 3 marta"
        ),
        DrugSuggestion(
            drug_name="Furosemid", inn_code="furosemide", dose="20 mg", frequency="kuniga 1 marta"
        ),
        DrugSuggestion(drug_name="Aspirin", inn_code="aspirin", dose="100 mg", frequency="kuniga 1 marta"),
    ]
    set_analysis_service(fake)
    p, e = await ready_exam(nurse)
    await nurse.post(
        f"/patients/{p['id']}/allergies",
        json={"substance": "Penitsillin", "substance_code": "J01C", "severity": "severe"},
    )
    await nurse.post(
        f"/patients/{p['id']}/medications",
        json={"drug_name": "Varfarin", "inn_code": "warfarin", "dose": "5 mg"},
    )
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    rx = (await doctor.get(f"/examinations/{e['id']}/prescription")).json()
    by = {i["drug_name"]: i for i in rx["items"]}
    assert by["Amoksitsillin"]["allergy_warning"] is True
    assert any(i["level"] == "major" for i in by["Aspirin"]["interaction_warnings"])  # warfarin + aspirin
    assert rx["safety_check"]["allergy_conflicts"] and "disclaimer" in rx and rx["status"] == "suggested"
    # allergy item needs an explicit override reason
    r = await doctor.post(f"/prescription-items/{by['Amoksitsillin']['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALLERGY_OVERRIDE_REQUIRED"
    assert (
        await doctor.post(
            f"/prescription-items/{by['Amoksitsillin']['id']}/approve",
            json={"override_reason": "yo'q alternativa"},
        )
    ).status_code == 200
    bulk = (await doctor.post(f"/examinations/{e['id']}/prescription/approve")).json()
    assert (
        bulk["approved"] == 1 and len(bulk["skipped_with_warnings"]) == 1
    )  # aspirin has an interaction warning
    # signing is blocked while a row is undecided
    assert (await doctor.put(f"/examinations/{e['id']}/conclusion", json=CONCL)).status_code == 200
    s = await doctor.post(f"/examinations/{e['id']}/conclusion/sign")
    assert s.status_code == 409 and s.json()["error"]["code"] == "PRESCRIPTION_PENDING"
    assert (
        await doctor.post(
            f"/prescription-items/{by['Aspirin']['id']}/reject", json={"reason": "varfarin bilan"}
        )
    ).status_code == 200
    # doctor adds a manual row; allergy list change recomputes safety for open rows
    add = await doctor.post(
        f"/examinations/{e['id']}/prescription/items",
        json={
            "drug_name": "Seftriakson",
            "inn_code": "ceftriaxone",
            "dose": "1 g",
            "frequency": "kuniga 1 marta",
        },
    )
    assert (
        add.status_code == 201 and add.json()["allergy_warning"] is True
    )  # cross-reactivity penicillin/cephalosporin
    assert (
        await doctor.post(f"/prescription-items/{add.json()['id']}/reject", json={"reason": "allergiya"})
    ).status_code == 200
    # nurse cannot touch prescriptions
    assert (
        await nurse.post(f"/prescription-items/{by['Furosemid']['id']}/approve", json={})
    ).status_code == 403


async def test_dose_limit_and_contraindication(nurse, doctor):
    set_analysis_service(FakeAnalysis())
    p, e = await ready_exam(nurse)
    await nurse.post(
        f"/patients/{p['id']}/history",
        json={"kind": "chronic", "title": "Bronxial astma", "icd10_code": "J45"},
    )
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    add = await doctor.post(
        f"/examinations/{e['id']}/prescription/items",
        json={
            "drug_name": "Metoprolol",
            "inn_code": "metoprolol",
            "dose": "300 mg",
            "frequency": "kuniga 3 marta",
        },
    )
    assert add.status_code == 201
    rx = (await doctor.get(f"/examinations/{e['id']}/prescription")).json()
    assert rx["safety_check"]["contraindications"][0]["note"].startswith("Bronxial")
    assert rx["safety_check"]["dose_warnings"][0]["max_daily_mg"] == 400


async def test_conclusion_sign_amend_pdf(nurse, doctor, doctor2, admin):
    _, e, _ = await _analysed(nurse)
    eid = e["id"]
    assign = await nurse.post(f"/examinations/{eid}/assign", json={"doctor_id": str(doctor.id)})
    assert assign.status_code == 200
    assert (
        await doctor2.put(f"/examinations/{eid}/conclusion", json=CONCL)
    ).status_code == 403  # assigned to someone else
    assert (
        await admin.put(f"/examinations/{eid}/conclusion", json=CONCL)
    ).status_code == 403  # admins never sign
    r = await doctor.put(f"/examinations/{eid}/conclusion", json=CONCL)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    stale = await doctor.put(f"/examinations/{eid}/conclusion", json=CONCL, headers={"If-Match": '"99"'})
    assert stale.status_code == 409
    bad = dict(CONCL, agreement_with_ai="disagree")
    assert (await doctor.put(f"/examinations/{eid}/conclusion", json=bad)).status_code == 200
    s = await doctor.post(f"/examinations/{eid}/conclusion/sign")
    assert s.status_code == 422 and s.json()["error"]["code"] == "DISAGREEMENT_REASON_REQUIRED"
    assert (
        await doctor.put(
            f"/examinations/{eid}/conclusion",
            json=dict(bad, disagreement_reason="Shifokor boshqacha baholadi", final_pcg_class="normal"),
        )
    ).status_code == 200
    # nurse PDF before signing is forbidden; doctor gets a draft
    assert (await nurse.get(f"/examinations/{eid}/export/pdf")).status_code == 403
    d = await doctor.get(f"/examinations/{eid}/export/pdf")
    assert d.status_code == 200 and d.content[:5] == b"%PDF-"
    assert (await doctor.post(f"/examinations/{eid}/prescription/approve")).status_code == 200
    h = {"Idempotency-Key": "sign-key-0001"}
    s = await doctor.post(f"/examinations/{eid}/conclusion/sign", headers=h)
    assert (
        s.status_code == 200
        and s.json()["exam_status"] == "completed"
        and len(s.json()["signature_hash"]) == 64
    )
    assert (await doctor.post(f"/examinations/{eid}/conclusion/sign", headers=h)).json()["id"] == s.json()[
        "id"
    ]  # replay
    assert (await doctor.post(f"/examinations/{eid}/conclusion/sign")).status_code == 409
    assert (
        await doctor.put(f"/examinations/{eid}/conclusion", json=CONCL)
    ).status_code == 409  # signed is immutable
    # nurse now sees signed conclusion + gets the PDF; notified
    assert (await nurse.get(f"/examinations/{eid}/conclusion")).json()["status"] == "signed"
    pdf = await nurse.get(f"/examinations/{eid}/export/pdf")
    assert (
        pdf.status_code == 200
        and b"%PDF" in pdf.content[:8]
        and "CardioPCG_" in pdf.headers["content-disposition"]
    )
    assert any(n["type"] == "conclusion_signed" for n in (await nurse.get("/notifications")).json()["items"])
    # public verification (QR target) returns no PHI
    v = (await nurse.client.get(f"/api/v1/verify/{e['exam_no']}/{s.json()['signature_hash'][:8]}")).json()
    assert v["valid"] is True and "patient" not in json.dumps(v)
    assert (await nurse.client.get(f"/api/v1/verify/{e['exam_no']}/deadbeef")).json() == {"valid": False}
    # amend: new version with reason, status stays completed
    am = await doctor.post(
        f"/examinations/{eid}/conclusion/amend",
        json=dict(CONCL, amend_reason="Tashxis aniqlashtirildi", agreement_with_ai="agree"),
    )
    assert (
        am.status_code == 201
        and am.json()["status"] == "amended"
        and am.json()["amends_id"] == s.json()["id"]
    )
    hist = (await doctor.get(f"/examinations/{eid}/conclusion/history")).json()
    assert [h["status"] for h in hist] == ["signed", "amended"] and [h["is_current"] for h in hist] == [
        False,
        True,
    ]
    assert (await nurse.get(f"/examinations/{eid}/status")).json()["status"] == "completed"


async def test_csv_export_and_formula_injection(nurse, doctor, admin):
    _, e, _ = await _analysed(nurse)
    await doctor.put(f"/examinations/{e['id']}/conclusion", json=CONCL)
    await doctor.post(f"/examinations/{e['id']}/prescription/approve")
    assert (await doctor.post(f"/examinations/{e['id']}/conclusion/sign")).status_code == 200
    p = await new_patient(admin, last_name="=cmd|' /C calc'!A0", first_name="+Evil", phone="+998901112233")
    assert p
    r = await admin.post("/export/csv", json={"kind": "examinations", "anonymize": True})
    assert (
        r.status_code == 200
        and r.content.startswith(b"\xef\xbb\xbf")
        and "Rahimov" not in r.text
        and "P-20" not in r.text
    )
    assert "murmur" in r.text and "H-" in r.text
    plain = await admin.post(
        "/export/csv",
        json={"kind": "patients", "anonymize": False, "columns": ["mrn", "patient_name", "phone"]},
    )
    assert "'=cmd" in plain.text and "'+Evil" not in plain.text.replace(
        "'=cmd|' /C calc'!A0 +Evil", ""
    )  # formula cell is neutralised
    assert (await nurse.post("/export/csv", json={"kind": "patients"})).status_code == 403
    assert (
        await admin.post("/export/csv", json={"kind": "examinations", "columns": ["password"]})
    ).status_code == 422
    doc = await doctor.post("/export/csv", json={"kind": "conclusions"})
    assert doc.status_code == 200 and "murmur" in doc.text


async def test_large_csv_becomes_background_job(admin, monkeypatch):
    monkeypatch.setenv("CSV_SYNC_MAX_ROWS", "0")
    from app.config import reset_settings_cache
    from app.services import export_service

    reset_settings_cache()
    await new_patient(admin)
    r = await admin.post("/export/csv", json={"kind": "patients"})
    assert r.status_code == 202
    eid = r.json()["export_id"]
    assert await export_service.run_export_job(eid) == "succeeded"
    st = (await admin.get(f"/export/{eid}")).json()
    assert st["status"] == "succeeded" and st["file_url"]
    dl = await admin.client.get(st["file_url"])
    assert dl.status_code == 200 and b"mrn" in dl.content
    assert (await admin.client.get(st["file_url"][:-4] + "abcd")).status_code == 403
    reset_settings_cache()


async def test_maintenance_cleanup(nurse):
    from app.models.enums import RecordingStatus
    from app.models.recording import Recording

    _, e = await ready_exam(nurse)
    async with dbs.get_sessionmaker()() as s:
        rec = (await s.execute(select(Recording))).scalars().first()
        await s.execute(
            update(Recording)
            .where(Recording.id == rec.id)
            .values(status=RecordingStatus.uploading, created_at=utcnow() - timedelta(hours=2))
        )
        await s.commit()
    assert await maintenance.cleanup_uploading_recordings() == 1
    _ = e, make_wav, new_exam, upload

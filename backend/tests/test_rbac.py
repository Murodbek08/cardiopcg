"""RBAC: unit matrix (doc 01 section 2) + HTTP-level matrix + IDOR."""

from __future__ import annotations

import pytest
from fakes import FakeAnalysis
from support import new_exam, new_patient, ready_exam, run_analysis

from app.core.permissions import PERMISSIONS, Permission, policy
from app.models.enums import UserRole
from app.services.analysis_port import set_analysis_service

A, D, N = UserRole.admin, UserRole.doctor, UserRole.nurse
P = Permission

# Expected matrix transcribed from doc 01 section 2 (True = allowed)
EXPECTED: dict[Permission, tuple[bool, bool, bool]] = {
    P.patient_read: (1, 1, 1),
    P.patient_write: (1, 1, 1),
    P.patient_delete: (1, 1, 0),
    P.patient_restore: (1, 0, 0),
    P.history_delete: (1, 1, 0),
    P.national_id_read: (1, 1, 0),
    P.exam_create: (1, 1, 1),
    P.exam_assign: (1, 1, 1),
    P.exam_cancel: (1, 1, 1),
    P.exam_delete: (1, 0, 0),
    P.recording_upload: (1, 1, 1),
    P.recording_delete: (1, 1, 1),
    P.analysis_start: (1, 1, 1),
    P.analysis_rerun: (1, 1, 0),
    P.report_read: (1, 1, 1),
    P.report_read_full: (1, 1, 0),
    P.report_regenerate: (1, 1, 0),
    P.prescription_read: (1, 1, 0),
    P.prescription_read_approved: (0, 0, 1),
    P.prescription_write: (0, 1, 0),
    P.prescription_approve: (0, 1, 0),
    P.conclusion_read: (1, 1, 0),
    P.conclusion_write: (0, 1, 0),
    P.conclusion_sign: (0, 1, 0),
    P.conclusion_read_signed: (1, 1, 1),
    P.analytics_admin: (1, 0, 0),
    P.analytics_doctor: (1, 1, 0),
    P.analytics_nurse: (1, 0, 1),
    P.audit_read: (1, 0, 0),
    P.audit_read_own: (0, 1, 0),
    P.user_manage: (1, 0, 0),
    P.settings_write: (1, 0, 0),
    P.export_pdf: (1, 1, 1),
    P.export_csv: (1, 1, 0),
    P.export_audit: (1, 0, 0),
    P.drug_kb_read: (1, 1, 0),
    P.drug_kb_write: (1, 0, 0),
}


def test_matrix_covers_every_permission():
    assert set(EXPECTED) == set(Permission)


@pytest.mark.parametrize("perm", list(Permission))
@pytest.mark.parametrize("role,idx", [(A, 0), (D, 1), (N, 2)])
def test_permission_matrix(perm, role, idx):
    assert (perm in PERMISSIONS[role]) == bool(EXPECTED[perm][idx])


def test_policy_object_rules():
    class U:  # noqa: D106
        def __init__(self, role, id_="u1"):
            self.role, self.id = role, id_

    class E:  # noqa: D106
        def __init__(self, status, by="u1"):
            self.status, self.performed_by = status, by

    from app.models.enums import ExamStatus as S

    nurse = U(N)
    assert policy.can(nurse, P.exam_cancel, E(S.draft))
    assert not policy.can(nurse, P.exam_cancel, E(S.processing))
    assert not policy.can(nurse, P.exam_cancel, E(S.draft, by="other"))
    assert policy.can(U(D), P.recording_delete, E(S.in_review))
    assert not policy.can(U(D), P.recording_delete, E(S.completed))


# ---------------------------------------------------------------------------- HTTP matrix
async def test_http_role_matrix(admin, doctor, nurse):
    p = await new_patient(admin)
    e = await new_exam(admin, p["id"])
    cases = [
        # (method, url, json, allowed roles)
        ("GET", "/users", None, {"admin"}),
        (
            "POST",
            "/users",
            {"username": "x.y.z", "full_name": "Xy Z", "role": "nurse", "password": "Aq9-Zx7-Pass-1!"},
            {"admin"},
        ),
        ("GET", "/settings", None, {"admin"}),
        ("PATCH", "/settings", {"ai.llm_enabled": True}, {"admin"}),
        ("GET", "/audit-logs/export", None, {"admin"}),
        ("GET", "/analytics/admin/kpis", None, {"admin"}),
        ("GET", "/analytics/doctor/kpis", None, {"admin", "doctor"}),
        ("GET", "/analytics/nurse/kpis", None, {"admin", "nurse"}),
        ("GET", "/audit-logs", None, {"admin", "doctor"}),
        ("GET", f"/examinations/{e['id']}/analysis/history", None, {"admin", "doctor"}),
        ("GET", f"/examinations/{e['id']}/conclusion/history", None, {"admin", "doctor"}),
        (
            "PUT",
            f"/examinations/{e['id']}/conclusion",
            {
                "diagnosis_text": "x",
                "final_pcg_class": "normal",
                "final_severity": "none",
                "agreement_with_ai": "agree",
            },
            {"doctor"},
        ),
        ("POST", f"/examinations/{e['id']}/conclusion/sign", None, {"doctor"}),
        (
            "POST",
            f"/examinations/{e['id']}/prescription/items",
            {"drug_name": "A", "dose": "1 mg", "frequency": "daily"},
            {"doctor"},
        ),
        ("POST", f"/patients/{p['id']}/restore", None, {"admin"}),
        ("DELETE", f"/examinations/{e['id']}", None, {"admin"}),
        ("POST", "/export/csv", {"kind": "patients"}, {"admin", "doctor"}),
    ]
    actors = {"admin": admin, "doctor": doctor, "nurse": nurse}
    for method, url, body, allowed in cases:
        for role, actor in actors.items():
            r = await actor.req(method, url, json=body) if body is not None else await actor.req(method, url)
            denied = r.status_code == 403
            if role in allowed:
                assert not denied, (method, url, role, r.text)
            elif allowed:
                assert denied, (method, url, role, r.status_code)


async def test_permission_denied_is_audited(nurse, admin):
    assert (await nurse.get("/users")).status_code == 403
    rows = (await admin.get("/audit-logs", params={"action": "permission_denied"})).json()["items"]
    assert rows and rows[0]["user"]["username"] == "nurse.main" and rows[0]["success"] is False


async def test_nurse_idor_exam_and_recordings(nurse, nurse2, doctor):
    _, e = await ready_exam(nurse)
    other_view = await nurse2.get(f"/examinations/{e['id']}")
    assert other_view.status_code == 403
    recs = (await nurse.get(f"/examinations/{e['id']}/recordings")).json()
    rid = recs[0]["id"]
    for url in (
        f"/recordings/{rid}",
        f"/recordings/{rid}/file",
        f"/recordings/{rid}/waveform",
        f"/examinations/{e['id']}/analysis",
        f"/examinations/{e['id']}/report",
    ):
        assert (await nurse2.get(url)).status_code == 403, url
    assert (await nurse2.delete(f"/recordings/{rid}")).status_code == 403
    assert (await nurse2.post(f"/examinations/{e['id']}/cancel", json={"reason": "x"})).status_code == 403
    assert (await nurse2.patch(f"/examinations/{e['id']}", json={"complaints": "x"})).status_code == 403
    # nurse2 list does not leak it; doctor sees all
    assert (await nurse2.get("/examinations")).json()["items"] == []
    assert len((await doctor.get("/examinations")).json()["items"]) == 1
    # ws/sse channel check
    assert (await nurse2.get(f"/examinations/{e['id']}/status")).status_code == 403


async def test_nurse_views_are_restricted(nurse, doctor):
    fake = FakeAnalysis()
    set_analysis_service(fake)
    p, e = await ready_exam(nurse)
    assert await run_analysis(nurse, e["id"]) == "succeeded"
    rep = (await nurse.get(f"/examinations/{e['id']}/report")).json()
    assert set(rep) == {"id", "status", "summary", "findings", "red_flags", "disclaimer", "created_at"}
    full = (await doctor.get(f"/examinations/{e['id']}/report")).json()
    assert full["differential_diagnoses"] and full["patient_friendly_text"]
    detail = (await nurse.get(f"/examinations/{e['id']}")).json()
    assert detail["prescription"] is None and detail["conclusion"] is None
    assert "differential_diagnoses" not in detail["report"]
    assert (await nurse.get(f"/examinations/{e['id']}/prescription")).status_code == 403
    assert (await nurse.get(f"/examinations/{e['id']}/conclusion")).status_code == 403
    # national id masked for nurse, visible for doctor
    pn = await new_patient(doctor, national_id="31204755550012")
    assert (await nurse.get(f"/patients/{pn['id']}")).json()["national_id"] == "****"
    assert (await doctor.get(f"/patients/{pn['id']}")).json()["national_id"] == "31204755550012"

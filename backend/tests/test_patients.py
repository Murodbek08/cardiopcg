from __future__ import annotations

from sqlalchemy import text
from support import new_exam, new_patient

from app.db import session as dbs


async def test_create_get_update_delete(nurse, doctor, admin):
    p = await new_patient(
        nurse, national_id="31204755550012", height_cm=176, weight_kg=84.5, phone="+998901112233"
    )
    assert p["mrn"].startswith("P-") and p["age"] >= 50 and p["bmi"] == 27.3
    # PII is encrypted at rest, only a keyed hash is searchable
    async with dbs.get_sessionmaker()() as s:
        row = (await s.execute(text("select national_id_enc, national_id_hash from patients"))).one()
        assert b"31204755550012" not in bytes(row[0]) and len(row[1]) == 64
    got = (await doctor.get(f"/patients/{p['id']}")).json()
    assert got["stats"]["exam_count"] == 0 and got["allergies"] == []
    # optimistic locking
    ok = await doctor.patch(f"/patients/{p['id']}", json={"address": "Toshkent"}, headers={"If-Match": '"1"'})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = await doctor.patch(f"/patients/{p['id']}", json={"address": "X"}, headers={"If-Match": '"1"'})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
    # nurse cannot delete; doctor can; admin can restore
    assert (await nurse.delete(f"/patients/{p['id']}")).status_code == 403
    assert (await doctor.delete(f"/patients/{p['id']}")).status_code == 204
    assert (await doctor.get(f"/patients/{p['id']}")).status_code == 404
    assert (await admin.post(f"/patients/{p['id']}/restore")).status_code == 200
    assert (await doctor.get(f"/patients/{p['id']}")).status_code == 200


async def test_validation_and_duplicates(nurse):
    bad = await nurse.post(
        "/patients",
        json={
            "last_name": "A",
            "first_name": "B",
            "birth_date": "2999-01-01",
            "gender": "male",
            "height_cm": 999,
        },
    )
    assert bad.status_code == 422
    fields = {d["field"] for d in bad.json()["error"]["details"]}
    assert {"birth_date", "height_cm"} <= fields
    extra = await nurse.post(
        "/patients",
        json={"last_name": "A", "first_name": "B", "birth_date": "1990-01-01", "gender": "male", "hack": 1},
    )
    assert extra.status_code == 422
    p = await new_patient(nurse, national_id="11111222223333")
    dup = await nurse.post(
        "/patients",
        json={
            "last_name": "Other",
            "first_name": "Name",
            "birth_date": "1980-01-01",
            "gender": "female",
            "national_id": "11111222223333",
        },
    )
    assert (
        dup.status_code == 409
        and dup.json()["error"]["code"] == "PATIENT_DUPLICATE"
        and dup.json()["error"]["details"]["patient_id"] == p["id"]
    )
    same = {"last_name": "Rahimov", "first_name": "Jasur", "birth_date": "1975-04-12", "gender": "male"}
    pd = await nurse.post("/patients", json=same)
    assert pd.status_code == 409 and pd.json()["error"]["code"] == "POSSIBLE_DUPLICATE"
    assert (await nurse.post("/patients?force=true", json=same)).status_code == 201


async def test_list_filters_search_sort_cursor(nurse, doctor):
    names = [
        ("Aliyev", "Bobur", "1990-01-01", "male"),
        ("Karimova", "Dilnoza", "1985-05-05", "female"),
        ("Rahimov", "Jasur", "1975-04-12", "male"),
        ("Rahimova", "Malika", "2010-02-02", "female"),
    ]
    for ln, fn, bd, g in names:
        await new_patient(nurse, last_name=ln, first_name=fn, birth_date=bd, gender=g)
    r = await doctor.get("/patients", params={"limit": 2, "sort": "last_name", "with_total": "true"})
    page1 = r.json()
    assert [i["full_name"].split()[0] for i in page1["items"]] == ["Aliyev", "Karimova"] and page1["page"][
        "total"
    ] == 4
    page2 = (
        await doctor.get(
            "/patients", params={"limit": 2, "sort": "last_name", "cursor": page1["page"]["next_cursor"]}
        )
    ).json()
    assert [i["full_name"].split()[0] for i in page2["items"]] == ["Rahimov", "Rahimova"] and page2["page"][
        "next_cursor"
    ] is None
    q = (await doctor.get("/patients", params={"q": "rahim"})).json()["items"]
    assert {i["full_name"].split()[0] for i in q} == {"Rahimov", "Rahimova"}
    assert len((await doctor.get("/patients", params={"gender": "female"})).json()["items"]) == 2
    assert len((await doctor.get("/patients", params={"age_max": 20})).json()["items"]) == 1
    assert (await doctor.get("/patients", params={"sort": "password_hash"})).status_code == 422


async def test_history_allergies_medications(nurse, doctor):
    p = await new_patient(nurse)
    pid = p["id"]
    a = await nurse.post(
        f"/patients/{pid}/allergies",
        json={"substance": "Penitsillin", "substance_code": "J01C", "severity": "severe"},
    )
    assert a.status_code == 201
    assert (
        await nurse.post(f"/patients/{pid}/allergies", json={"substance": "penitsillin"})
    ).status_code == 409
    assert (
        await nurse.delete(f"/patients/{pid}/allergies/{a.json()['id']}")
    ).status_code == 403  # nurse cannot archive
    h = await nurse.post(
        f"/patients/{pid}/history", json={"kind": "chronic", "title": "Gipertoniya", "icd10_code": "I10"}
    )
    m = await nurse.post(
        f"/patients/{pid}/medications", json={"drug_name": "Varfarin", "inn_code": "warfarin", "dose": "5 mg"}
    )
    assert h.status_code == 201 and m.status_code == 201
    assert (await doctor.delete(f"/patients/{pid}/allergies/{a.json()['id']}")).status_code == 204
    d = (await doctor.get(f"/patients/{pid}")).json()
    assert (
        d["allergies"] == []
        and len(d["medical_history"]) == 1
        and d["current_medications"][0]["drug_name"] == "Varfarin"
    )
    assert (await doctor.get(f"/patients/{pid}/allergies", params={"include_inactive": "true"})).json()[0][
        "is_active"
    ] is False


async def test_delete_blocked_by_active_exam_and_timeline(nurse, doctor):
    p = await new_patient(nurse)
    e = await new_exam(nurse, p["id"])
    r = await doctor.delete(f"/patients/{p['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PATIENT_HAS_ACTIVE_EXAMS"
    tl = (await doctor.get(f"/patients/{p['id']}/timeline")).json()["items"]
    assert tl[0]["type"] == "examination" and tl[0]["exam_id"] == e["id"]

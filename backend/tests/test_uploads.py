from __future__ import annotations

import contextlib
import io

import numpy as np
import pytest
import soundfile as sf
from PIL import Image
from sqlalchemy import select
from support import make_flac, make_wav, new_exam, new_patient, upload

from app.db import session as dbs
from app.models.system import AuditLog
from app.services.storage import LocalStorage, get_storage, sign_download, verify_download


async def _exam(nurse):
    p = await new_patient(nurse)
    return await new_exam(nurse, p["id"])


async def test_upload_wav_flac_metadata_and_download(nurse):
    e = await _exam(nurse)
    r = await upload(nurse, e["id"], make_wav(8.0), site="mitral", name="mitral_01.wav")
    assert r.status_code == 201, r.text
    b = r.json()
    assert (
        b["status"] == "validated"
        and b["site"] == "mitral"
        and b["mime_type"] == "audio/wav"
        and b["sample_rate_hz"] == 4000
    )
    assert 7.9 < b["duration_sec"] < 8.1 and b["snr_db"] is not None and len(b["sha256"]) == 64
    r2 = await upload(nurse, e["id"], make_flac(8.0), site="aortic", name="aortic.flac")
    assert r2.status_code == 201 and r2.json()["mime_type"] == "audio/flac"
    # storage key is server generated, never the client filename
    async with dbs.get_sessionmaker()() as s:
        from app.models.recording import Recording

        keys = [k for (k,) in (await s.execute(select(Recording.storage_key))).all()]
        assert all(k.startswith(f"exams/{e['id']}/") and "mitral_01" not in k for k in keys)
    full = await nurse.get(f"/recordings/{b['id']}/file")
    assert full.status_code == 200 and full.content[:4] == b"RIFF" and len(full.content) == b["size_bytes"]
    part = await nurse.get(f"/recordings/{b['id']}/file", headers={"Range": "bytes=0-99"})
    assert (
        part.status_code == 206
        and len(part.content) == 100
        and part.headers["content-range"].startswith("bytes 0-99/")
    )
    suffix = await nurse.get(f"/recordings/{b['id']}/file", headers={"Range": "bytes=-10"})
    assert suffix.status_code == 206 and len(suffix.content) == 10
    assert (
        await nurse.get(f"/recordings/{b['id']}/file", headers={"Range": "bytes=999999999-"})
    ).status_code == 416
    wf = (await nurse.get(f"/recordings/{b['id']}/waveform")).json()
    assert wf["sample_rate"] == 4000 and len(wf["data"]) >= 100 and max(wf["data"]) <= 1.0


async def test_rejections(nurse):
    e = await _exam(nurse)
    eid = e["id"]
    cases = [
        (make_wav(3.0), "short.wav", 422, "AUDIO_TOO_SHORT"),
        (make_wav(8.0, silent=True), "silent.wav", 422, "AUDIO_SILENT"),
        (make_wav(8.0, clip=True), "clip.wav", 422, "AUDIO_CLIPPED"),
        (b"RIFF\x00\x00\x00\x00WAVEgarbage" * 4, "corrupt.wav", 422, "AUDIO_CORRUPT"),
        (b"MZ\x90\x00this is an exe", "a.wav", 415, "UNSUPPORTED_MEDIA_TYPE"),  # content != extension
        (make_wav(8.0), "a.wav.exe", 415, "UNSUPPORTED_MEDIA_TYPE"),  # double extension
        (make_wav(8.0), "a.exe.wav", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"<svg onload=alert(1)/>", "x.svg", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"PK\x03\x04zip", "x.zip", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"", "empty.wav", 422, "AUDIO_CORRUPT"),
    ]
    for data, name, status, code in cases:
        r = await upload(nurse, eid, data, name=name)
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), (name, r.text)
    # nothing was stored, failures are audited
    assert (await nurse.get(f"/examinations/{eid}/recordings")).json() == []
    async with dbs.get_sessionmaker()() as s:
        failed = (
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.action == "upload", AuditLog.success.is_(False))
                )
            )
            .scalars()
            .all()
        )
        assert len(failed) == len(cases)


async def test_path_traversal_filename_is_sanitized(nurse):
    e = await _exam(nurse)
    r = await upload(nurse, e["id"], make_wav(8.0), name="../../etc/passwd.wav")
    assert r.status_code == 201 and r.json()["original_filename"] == "passwd.wav"
    r = await upload(
        nurse, e["id"], make_wav(8.0, seed=5), site="aortic", name="..\\..\\windows\\evil name!.wav"
    )
    assert (
        r.status_code == 201
        and "/" not in r.json()["original_filename"]
        and "\\" not in r.json()["original_filename"]
    )


async def test_duplicate_site_limits_and_invalid_site(nurse, admin):
    e = await _exam(nurse)
    eid = e["id"]
    assert (await upload(nurse, eid, make_wav(seed=1))).status_code == 201
    dup = await upload(nurse, eid, make_wav(seed=1), site="aortic")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_RECORDING"
    same_site = await upload(nurse, eid, make_wav(seed=2))
    assert same_site.status_code == 409 and same_site.json()["error"]["code"] == "SITE_ALREADY_RECORDED"
    assert (await upload(nurse, eid, make_wav(seed=2), replace="true")).status_code == 201
    assert len((await nurse.get(f"/examinations/{eid}/recordings")).json()) == 1
    bad_site = await nurse.post(
        f"/examinations/{eid}/recordings",
        files={"file": ("a.wav", make_wav(seed=3), "audio/wav")},
        data={"site": "knee"},
    )
    assert bad_site.status_code == 422
    no_site = await nurse.post(
        f"/examinations/{eid}/recordings", files={"file": ("a.wav", make_wav(seed=3), "audio/wav")}
    )
    assert no_site.status_code == 422
    # file count limit from settings
    assert (await admin.patch("/settings", json={"upload.max_files_per_exam": 2})).status_code == 200
    assert (await upload(nurse, eid, make_wav(seed=4), site="aortic")).status_code == 201
    r = await upload(nurse, eid, make_wav(seed=5), site="pulmonic")
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_MANY_FILES"


async def test_size_limit_from_settings(nurse, admin):
    e = await _exam(nurse)
    assert (await admin.patch("/settings", json={"upload.max_audio_mb": 1})).status_code == 200
    big = make_wav(60.0, sr=16000)  # ~1.9 MB
    r = await upload(nurse, e["id"], big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_audio_bomb_duration_limit(nurse):
    e = await _exam(nurse)
    long_wav = io.BytesIO()
    sf.write(long_wav, np.zeros(4000 * 200, dtype="float32") + 0.1, 4000, format="WAV")  # 200 s
    r = await upload(nurse, e["id"], long_wav.getvalue())
    assert r.status_code == 422 and r.json()["error"]["code"] == "AUDIO_TOO_LONG"


async def test_image_upload_reencoded_and_bomb(nurse):
    e = await _exam(nurse)
    buf = io.BytesIO()
    im = Image.new("RGB", (64, 64), "red")
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    im.save(buf, "JPEG", exif=exif)
    r = await nurse.post(
        f"/examinations/{e['id']}/recordings",
        files={"file": ("ecg.jpg", buf.getvalue(), "image/jpeg")},
        data={"kind": "other_image"},
    )
    assert r.status_code == 201 and r.json()["width_px"] == 64
    stored = await get_storage().get_bytes(f"exams/{e['id']}/{r.json()['id']}/original.jpg")
    assert b"SecretCamera" not in stored and Image.open(io.BytesIO(stored)).size == (64, 64)
    bad = await nurse.post(
        f"/examinations/{e['id']}/recordings",
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\nnot really", "image/png")},
        data={"kind": "other_image"},
    )
    assert bad.status_code == 422


async def test_infected_file_rejected(nurse, monkeypatch):
    from app.services import antivirus

    async def fake_scan(path, timeout=5.0):
        return "infected"

    monkeypatch.setattr(antivirus, "scan_file", fake_scan)
    e = await _exam(nurse)
    r = await upload(nurse, e["id"], make_wav(8.0))
    assert r.status_code == 422 and r.json()["error"]["code"] == "INFECTED_FILE"
    assert (await nurse.get(f"/examinations/{e['id']}/recordings")).json() == []


async def test_clamav_required_without_scanner(nurse, monkeypatch):
    monkeypatch.setenv("CLAMAV_REQUIRED", "true")
    from app.config import reset_settings_cache

    reset_settings_cache()
    e = await _exam(nurse)
    r = await upload(nurse, e["id"], make_wav(8.0))
    assert r.status_code == 503
    monkeypatch.delenv("CLAMAV_REQUIRED")
    reset_settings_cache()


async def test_upload_rolls_back_storage_on_db_failure(nurse, monkeypatch):
    e = await _exam(nurse)
    from app.services import recording_service

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        recording_service.audit_service, "log_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        pytest.skip("local-disk specific check")
    with contextlib.suppress(Exception):
        await upload(nurse, e["id"], make_wav(8.0))
    files = [p for p in storage.root.rglob("original.*") if e["id"] in str(p)]
    assert files == []  # compensating cleanup removed the object
    _ = boom


def test_storage_key_safety_and_signed_links(tmp_path):
    import pytest

    st = LocalStorage(str(tmp_path))
    for bad in ("../x", "/abs", "a/../../b", "a\\b"):
        with pytest.raises(ValueError):
            st._p(bad)
    tok = sign_download("exports/a.csv", "a.csv", "text/csv", ttl=60)
    assert verify_download(tok)["k"] == "exports/a.csv"
    from app.core.errors import AppError

    with pytest.raises(AppError):
        verify_download(tok[:-3] + "xxx")
    with pytest.raises(AppError):
        verify_download(sign_download("k", "f", "t", ttl=-1))

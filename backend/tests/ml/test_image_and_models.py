"""Image digitisation path + pluggable ML slot (registry, sha256, ONNX, ensemble)."""

from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
import pytest
from onnx_builder import build_logistic_onnx
from scipy import signal as sig
from synth import make_pcg, to_wav_bytes

from app.ml import AudioError, ModelRegistry, analyze_recording
from app.ml.classifier import classify
from app.ml.features import MurmurResult
from app.ml.image_digitize import ImageError, digitize_image

PX_MM = 8
SPEED = 50.0  # mm/s -> 400 px/s


def make_trace_png(hr=72.0, seconds=11.0, murmur=None, amp_px=110, grid=True) -> bytes:
    x, _ = make_pcg(duration=seconds, sr=4000, hr=hr, noise=0.02, murmur=murmur, murmur_amp=0.08, seed=4)
    fs_px = int(SPEED * PX_MM)  # px per second
    xd = sig.resample_poly(x, fs_px, 4000)
    W, H = len(xd), 400
    img = np.full((H, W, 3), 255, np.uint8)
    if grid:
        for gx in range(0, W, PX_MM):
            cv2.line(
                img, (gx, 0), (gx, H), (205, 205, 255) if gx % (5 * PX_MM) else (150, 150, 235), 1
            )  # BGR pinks
        for gy in range(0, H, PX_MM):
            cv2.line(img, (0, gy), (W, gy), (205, 205, 255) if gy % (5 * PX_MM) else (150, 150, 235), 1)
    ys = (H / 2 - xd / 0.8 * amp_px).astype(int)
    pts = np.stack([np.arange(W), ys], axis=1).reshape(-1, 1, 2).astype(np.int32)
    cv2.polylines(img, [pts], False, (0, 0, 0), 1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_digitize_detects_grid_scale_and_trace():
    png = make_trace_png()
    d = digitize_image(png, paper_speed_mm_s=SPEED)
    assert d.calibration == "grid_auto" and d.px_per_mm == pytest.approx(PX_MM, abs=0.5)
    assert d.fs_eff == pytest.approx(SPEED * PX_MM, rel=0.07)
    assert d.q_img > 0.6
    assert any("taxminiy" in n for n in d.notes)


def test_image_pipeline_hr_and_limits():
    png = make_trace_png(hr=72.0)
    res, arts = analyze_recording(png, source="image", paper_speed_mm_s=SPEED, px_per_mm=PX_MM)
    assert res.source == "image"
    assert res.quality.level != "good"  # images never reach "good"
    assert res.feature_flags["frequency_features_valid"] is False
    assert res.pipeline.ml_available is False
    assert any("Rasmdan olingan signal" in s for s in res.limitations)
    assert res.rhythm is not None and res.rhythm.hr_bpm == pytest.approx(72, abs=6)
    if res.murmur and res.murmur.systolic:
        assert res.murmur.systolic.f_peak_hz is None and res.murmur.systolic.frequency_class is None
    assert "scalogram.png" not in arts


def test_image_errors():
    with pytest.raises(ImageError) as e:
        digitize_image(b"%PDF-1.4 ...", paper_speed_mm_s=25)
    assert e.value.code == "UNSUPPORTED_FORMAT"
    with pytest.raises(ImageError) as e:
        digitize_image(b"\x00" * 500)
    assert e.value.code == "IMAGE_DECODE_FAILED"
    small = np.full((100, 300, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", small)
    with pytest.raises(ImageError) as e:
        digitize_image(buf.tobytes())
    assert e.value.code == "IMAGE_TOO_SMALL"
    blank = np.full((300, 1000, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", blank)
    with pytest.raises(ImageError) as e:
        digitize_image(buf.tobytes())
    assert e.value.code == "TRACE_NOT_FOUND"
    assert isinstance(e.value, AudioError)


def test_calibration_required_without_grid():
    png = make_trace_png(grid=False)
    with pytest.raises(ImageError) as e:
        digitize_image(png, paper_speed_mm_s=SPEED)
    assert e.value.code == "CALIBRATION_REQUIRED"


# ------------------------------------------------------------------ ML slot


def test_no_registry_is_graceful(tmp_path):
    reg = ModelRegistry.load(tmp_path / "does-not-exist")
    assert reg.models == [] and reg.warnings == []
    x, _ = make_pcg(noise=0.03)
    res, _ = analyze_recording(to_wav_bytes(x, 4000), registry=reg)
    assert res.pipeline.ml_available is False and res.classification.per_model.gbm is None


def _write_registry(d, onnx_bytes, sha=None, feature_names=("R_sys", "R_dia")):
    (d / "murmur_gbm.onnx").write_bytes(onnx_bytes)
    digest = sha or hashlib.sha256(onnx_bytes).hexdigest()
    (d / "registry.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "name": "murmur_gbm",
                        "version": "0.0.1-test",
                        "file": "murmur_gbm.onnx",
                        "sha256": digest,
                        "kind": "onnx",
                        "feature_names": list(feature_names),
                        "impute": {"R_sys": 1.0, "R_dia": 1.0},
                        "calibrator": {"type": "temperature", "T": 1.0},
                    }
                ]
            }
        ),
        encoding="utf8",
    )


def test_registry_loads_valid_onnx_and_predicts(tmp_path):
    _write_registry(tmp_path, build_logistic_onnx([0.5, 0.5], -4.0))
    reg = ModelRegistry.load(tmp_path)
    assert len(reg.models) == 1 and reg.warnings == []
    m = reg.models[0]
    lo = m.predict({"R_sys": 1.0, "R_dia": 1.0})
    hi = m.predict({"R_sys": 20.0, "R_dia": 20.0})
    assert 0 < lo < 0.2 and hi > 0.95
    assert m.predict({}) == pytest.approx(lo, abs=1e-6)  # imputation


def test_registry_rejects_sha_mismatch(tmp_path):
    _write_registry(tmp_path, build_logistic_onnx([0.5, 0.5], -4.0), sha="0" * 64)
    reg = ModelRegistry.load(tmp_path)
    assert reg.models == [] and any("sha256" in w for w in reg.warnings)


def test_registry_survives_corrupt_model(tmp_path):
    _write_registry(tmp_path, b"not an onnx file")
    reg = ModelRegistry.load(tmp_path)
    assert reg.models == [] and reg.warnings


def test_pipeline_uses_onnx_model_in_ensemble(tmp_path):
    _write_registry(tmp_path, build_logistic_onnx([0.3, 0.3], -2.0))
    reg = ModelRegistry.load(tmp_path)
    x, _ = make_pcg(noise=0.03, murmur="holosystolic", murmur_amp=0.07, seed=8)
    res, _ = analyze_recording(to_wav_bytes(x, 4000), registry=reg, site="mitral")
    assert res.pipeline.ml_available is True
    assert res.pipeline.ml_models[0].name == "murmur_gbm" and res.pipeline.ml_models[0].sha256
    pm = res.classification.per_model
    assert pm.rule is not None and pm.gbm is not None
    assert res.classification.outcome == "abnormal"


class FakeModel:
    name, version, sha256 = "fake_gbm", "1", None

    def __init__(self, p):
        self.p = p

    def predict(self, features):
        return self.p


class _Reg:
    def __init__(self, *models):
        self.models = list(models)
        self.warnings = []


def _mr(prob):
    return MurmurResult(True, prob > 0.5, prob, None, None)


def test_ensemble_disagreement_flag_and_uncertainty():
    rhythm = {"rhythm_irregular": False}
    cl, refs, used, _ = classify(_mr(0.05), rhythm, [], {}, 0.9, "good", 0.9, _Reg(FakeModel(0.95)))
    assert used and cl.models_disagree is True
    assert cl.uncertainty > 0.3
    cl2, _, _, _ = classify(_mr(0.9), rhythm, [], {}, 0.9, "good", 0.9, _Reg(FakeModel(0.92)))
    assert cl2.models_disagree is False and cl2.outcome == "abnormal"


def test_failing_model_does_not_break_classification():
    class Boom(FakeModel):
        def predict(self, features):
            raise RuntimeError("boom")

    cl, refs, used, notes = classify(
        _mr(0.9), {"rhythm_irregular": False}, [], {}, 0.9, "good", 0.9, _Reg(Boom(0.5))
    )
    assert used is False and cl.per_model.gbm is None and notes


def test_acceptable_quality_raises_uncertainty():
    args = (_mr(0.9), {"rhythm_irregular": False}, [], {})
    good, *_ = classify(*args, 0.9, "good", 0.9, None)
    acc, *_ = classify(*args, 0.9, "acceptable", 0.9, None)
    assert acc.uncertainty > good.uncertainty

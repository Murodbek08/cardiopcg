"""Signal pipeline tests on synthetic heart sounds (S1/S2 pulses + noise)."""

from __future__ import annotations

import numpy as np
import pytest
from synth import make_pcg, to_wav_bytes

from app.ml import AudioError, analyze_recording
from app.ml.envelope import shannon_envelope
from app.ml.preprocess import bandpass, decode_audio, preprocess, resample
from app.ml.segmentation import segment


def run(x, sr=4000, **kw):
    return analyze_recording(to_wav_bytes(x, sr), **kw)


# ----------------------------------------------------------------- preprocessing


def test_bandpass_frequency_response():
    sr = 4000
    t = np.arange(8 * sr) / sr
    inband = np.sin(2 * np.pi * 100 * t)
    low = np.sin(2 * np.pi * 5 * t)
    high = np.sin(2 * np.pi * 1500 * t)
    f = lambda s: np.sqrt(np.mean(bandpass(s, sr, 25, 400)[sr:-sr] ** 2))  # noqa: E731
    assert f(inband) > 0.6
    assert f(low) < 0.02
    assert f(high) < 0.02


def test_resample_preserves_tone_frequency():
    sr = 44100
    t = np.arange(5 * sr) / sr
    y = resample(np.sin(2 * np.pi * 80 * t), sr, 4000)
    assert len(y) == 5 * 4000
    spec = np.abs(np.fft.rfft(y))
    assert abs(np.argmax(spec) * 4000 / len(y) - 80) < 1.0


def test_preprocess_removes_dc_and_hum():
    x, _ = make_pcg(noise=0.02)
    x = x + 0.3  # DC offset
    pre = preprocess(x, 4000)
    assert abs(np.mean(pre.x)) < 0.05
    assert pre.sr == 4000 and pre.x_wide.shape == pre.x.shape


def test_decode_errors():
    with pytest.raises(AudioError) as e:
        decode_audio(b"this is definitely not audio" * 10)
    assert e.value.code == "AUDIO_DECODE_FAILED"
    short, _ = make_pcg(duration=2.0)
    with pytest.raises(AudioError) as e:
        decode_audio(to_wav_bytes(short, 4000))
    assert e.value.code == "AUDIO_TOO_SHORT"
    low, _ = make_pcg(duration=10.0, sr=1000)
    with pytest.raises(AudioError) as e:
        decode_audio(to_wav_bytes(low, 1000))
    assert e.value.code == "SAMPLE_RATE_TOO_LOW"


def test_decode_accepts_formats():
    x, _ = make_pcg(duration=8.0, sr=4000)
    for kw in ({"subtype": "PCM_16"}, {"subtype": "PCM_24"}, {"subtype": "FLOAT"}):
        d = decode_audio(to_wav_bytes(x, 4000, **kw))
        assert d.sr == 4000 and abs(d.duration_s - 8.0) < 0.01
    d = decode_audio(to_wav_bytes(x, 4000, subtype="PCM_16", fmt="FLAC"))
    assert d.sr == 4000


# ----------------------------------------------------------------- envelope / segmentation / HR


@pytest.mark.parametrize("hr,sys_", [(60, 0.32), (72, 0.30), (90, 0.28), (110, 0.25)])
def test_hr_and_segmentation(hr, sys_):
    x, truth = make_pcg(hr=hr, systole=sys_, noise=0.03, seed=3)
    res, _ = run(x)
    assert res.status == "ok"
    assert res.rhythm.hr_bpm == pytest.approx(hr, abs=2.5)
    seg = res.segmentation
    expected = len(truth["s1"])
    assert seg.n_cycles_valid >= expected - 3
    assert seg.confidence > 0.6
    assert res.rhythm.category in ("normal", "tachycardia")


def test_s1_s2_positions_match_truth():
    x, truth = make_pcg(hr=72, noise=0.03, seed=1)
    pre = preprocess(x, 4000)
    env = shannon_envelope(pre.x, 4000)
    seg = segment(env)
    valid = [c for c in seg.cycles if c.valid]
    assert len(valid) >= 15
    s1_true = np.array(truth["s1"])
    s2_true = np.array(truth["s2"])
    for c in valid:
        # envelope onset lies slightly after burst start; peaks within +-80 ms of truth pulse
        assert np.min(np.abs(s1_true + 0.03 - c.s1_peak_s)) < 0.08
        assert np.min(np.abs(s2_true + 0.03 - c.s2_peak_s)) < 0.08
        assert c.s2_peak_s > c.s1_peak_s  # S1 precedes S2: systole is the short interval


def test_intervals_systole_shorter_than_diastole():
    x, _ = make_pcg(hr=70, systole=0.30, noise=0.03)
    res, _ = run(x)
    iv = res.intervals
    assert 250 < iv.systole_ms < 420
    assert iv.diastole_ms > iv.systole_ms
    assert 0.4 < iv.sd_ratio < 1.0
    assert iv.s1_dur_ms and iv.s2_dur_ms


def test_irregular_rhythm_flag():
    x, _ = make_pcg(hr=75, noise=0.03, jitter=0.22, seed=5)
    res, _ = run(x)
    assert res.rhythm.rhythm_irregular is True
    assert res.rhythm.category == "irregular"
    assert any("EKG" in s for s in res.limitations)


def test_other_sample_rates_and_hum():
    x, _ = make_pcg(sr=8000, hr=72, noise=0.03, line_hum=0.1)
    res, _ = run(x, sr=8000)
    assert res.pipeline.sample_rate_hz == 4000 and res.pipeline.sample_rate_orig_hz == 8000
    assert res.rhythm.hr_bpm == pytest.approx(72, abs=2.5)


# ----------------------------------------------------------------- SQI


def test_sqi_levels():
    good, _ = make_pcg(noise=0.03)
    r, _ = run(good)
    assert r.quality.level == "good" and r.quality.sqi >= 0.7
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(4000 * 15) * 0.2
    r2, arts = analyze_recording(to_wav_bytes(noise, 4000))
    assert r2.status in ("rejected_low_quality", "low_quality_partial")
    assert r2.quality.sqi < 0.5
    if r2.status == "rejected_low_quality":
        assert r2.error_code == "LOW_QUALITY_REJECTED" and not arts
    else:
        assert r2.murmur.present is None  # murmur/ML blocked for `poor`


def test_noisy_but_usable_signal_degrades_gracefully():
    clean, _ = make_pcg(noise=0.03, seed=2)
    noisy, _ = make_pcg(noise=0.25, seed=2)
    a, _ = run(clean)
    b, _ = run(noisy)
    assert b.quality.sqi < a.quality.sqi


def test_clipping_lowers_quality_component():
    x, _ = make_pcg(noise=0.03)
    clipped = np.clip(x * 6, -0.8, 0.8)
    res, _ = run(clipped)
    assert res.quality.components.clip_ratio > 0.01 or res.quality.components.q_clip < 1.0


# ----------------------------------------------------------------- murmur


def test_normal_has_no_murmur():
    x, _ = make_pcg(noise=0.03, seed=7)
    res, _ = run(x)
    assert res.murmur.present is False
    assert res.classification.outcome == "normal"
    assert res.classification.probability_abnormal < 0.4


def test_holosystolic_murmur_detected():
    x, _ = make_pcg(noise=0.03, murmur="holosystolic", murmur_amp=0.07, seed=8)
    res, _ = run(x, site="mitral")
    m = res.murmur
    assert m.present is True and m.probability > 0.7
    assert m.systolic.present and m.systolic.timing == "holosystolic"
    assert m.systolic.R_sys > 3.0
    assert m.systolic.frequency_class in ("medium", "high")
    assert m.diastolic is None or not m.diastolic.present
    assert res.classification.outcome == "abnormal"
    assert any(h.hypothesis == "mitral_regurgitation_pattern" for h in m.location_hints)
    assert res.classification.per_model.gbm is None and res.pipeline.ml_available is False


def test_midsystolic_murmur_timing():
    x, _ = make_pcg(noise=0.03, murmur="midsystolic", murmur_amp=0.09, seed=9)
    res, _ = run(x, site="aortic")
    s = res.murmur.systolic
    assert res.murmur.present and s.present
    assert s.timing in ("mid_sys", "early_sys", "late_sys")  # not holosystolic
    assert s.timing != "holosystolic"


def test_diastolic_murmur_detected():
    x, _ = make_pcg(noise=0.03, diastolic_murmur=0.08, seed=10)
    res, _ = run(x, site="aortic")
    assert res.murmur.present is True
    assert res.murmur.diastolic.present
    assert res.murmur.diastolic.timing.endswith("_dia") or res.murmur.diastolic.timing == "holodiastolic"


# ----------------------------------------------------------------- artefacts / schema


def test_artifacts_and_schema_roundtrip():
    x, _ = make_pcg(noise=0.03)
    res, arts = run(x)
    for k in ("spectrogram.png", "waveform.png", "scalogram.png"):
        assert arts[k][:8] == b"\x89PNG\r\n\x1a\n" and len(arts[k]) > 3000
    assert res.artifacts.spectrogram_png == "spectrogram.png"
    import json

    peaks = json.loads(arts["wave_peaks.json"])
    assert len(peaks["peaks"]) >= 1000
    dumped = res.model_dump_json()
    from app.ml.schemas import PcgAnalysisResult

    again = PcgAnalysisResult.model_validate_json(dumped)
    assert again.schema_version == "pcg-analysis/1.0"
    rows = res.to_segment_rows()
    assert rows and all(r["end_ms"] > r["start_ms"] for r in rows)
    assert {r["type"] for r in rows} == {"S1", "S2"}
    assert res.pipeline.processing_ms is not None and res.pipeline.processing_ms < 15000


def test_long_recording_uses_best_window():
    x, _ = make_pcg(duration=140.0, noise=0.03, seed=11)
    res, _ = run(x)
    assert res.status == "ok"
    assert res.pipeline.duration_s <= 31
    assert any("Long recording" in s for s in res.limitations)


def test_features_present_and_flagged_missing():
    x, _ = make_pcg(noise=0.03, murmur="holosystolic", murmur_amp=0.07)
    res, _ = run(x)
    for k in ("hr_bpm", "systole_ms", "R_sys", "f_centroid_sys", "cycle_corr", "mfcc_1_mean", "sqi"):
        assert res.features.get(k) is not None, k
    assert "sample_entropy_sys" in res.feature_flags["missing"]
    assert res.feature_flags["frequency_features_valid"] is True


def test_stereo_input():
    x, _ = make_pcg(duration=10.0, noise=0.03)
    st = np.stack([x, x * 0.5], axis=1)
    import io

    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, st, 4000, format="WAV", subtype="PCM_16")
    res, _ = analyze_recording(buf.getvalue())
    assert res.status == "ok" and any("Stereo" in s for s in res.limitations)

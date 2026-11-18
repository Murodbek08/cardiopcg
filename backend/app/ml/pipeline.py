"""End-to-end PCG signal pipeline: bytes/path -> `PcgAnalysisResult` + PNG/JSON artefacts.

Synchronous and CPU-bound; call via `asyncio.to_thread` from async code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import classifier as clf
from . import features as feat
from . import spectrogram as spec
from .config import (
    DEFAULT_CONFIG,
    MURMUR_RULE_VERSION,
    PREPROCESS_VERSION,
    SEGMENTATION_METHOD,
    MLConfig,
)
from .envelope import shannon_envelope
from .image_digitize import digitize_image
from .preprocess import AudioError, Preprocessed, decode_audio, preprocess, select_channel, split_windows
from .schemas import (
    Artifacts,
    Classification,
    CycleOut,
    ExtraSound,
    Intervals,
    Murmur,
    PcgAnalysisResult,
    PipelineInfo,
    Quality,
    QualityComponents,
    Rhythm,
    SegmentationOut,
)
from .segmentation import Segmentation, segment
from .sqi import SQIResult, compute_sqi, level_for

ART_KEYS = {
    "waveform": "waveform.png",
    "spectrogram": "spectrogram.png",
    "scalogram": "scalogram.png",
    "envelope": "envelope.json",
    "peaks": "wave_peaks.json",
}


@dataclass
class _Win:
    pre: Preprocessed
    env: Any
    seg: Segmentation
    q: SQIResult
    start_s: float


def _analyze_window(
    x: np.ndarray,
    sr: int,
    cfg: MLConfig,
    source: str,
    start_s: float,
    native_sr: float | None = None,
    freq_valid: bool = True,
) -> _Win:
    pre = preprocess(x, sr, cfg, source=source, native_sr=native_sr)
    env = shannon_envelope(pre.x, pre.sr, cfg)
    seg = segment(env, cfg)
    q = compute_sqi(
        env, seg, pre.x_wide, pre.sr, pre.artifact_ratio, pre.clip_ratio, cfg, freq_valid=freq_valid
    )
    return _Win(pre, env, seg, q, start_s)


def _quality_schema(q: SQIResult) -> Quality:
    return Quality(
        sqi=round(q.sqi, 3),
        level=q.level,  # type: ignore[arg-type]
        components=QualityComponents(
            snr_db=round(q.snr_db, 2),
            q_snr=round(q.q_snr, 3),
            q_period=round(q.q_period, 3),
            q_cycles=round(q.q_cycles, 3),
            q_art=round(q.q_art, 3),
            q_clip=round(q.q_clip, 3),
            q_spec=round(q.q_spec, 3),
            artifact_ratio=round(q.artifact_ratio, 4),
            clip_ratio=round(q.clip_ratio, 4),
        ),
        warnings=list(q.warnings),
    )


def _r(v: Any, nd: int = 3) -> Any:
    return None if v is None else round(float(v), nd)


def analyze_recording(
    src: bytes | bytearray | str | Path,
    *,
    source: str = "audio",
    site: str | None = None,
    age_years: float | None = None,
    registry: clf.ModelRegistry | None = None,
    cfg: MLConfig = DEFAULT_CONFIG,
    paper_speed_mm_s: float = 25.0,
    px_per_mm: float | None = None,
    image_roi: tuple[int, int, int, int] | None = None,
    allow_ml: bool = True,
) -> tuple[PcgAnalysisResult, dict[str, bytes]]:
    """Run the full pipeline. Raises `AudioError`/`ImageError` (with `.code`) on invalid input."""
    t_start = time.perf_counter()
    limitations: list[str] = ["Murmur grade is an estimate based on relative energy"]
    limitations.append("Single recording site")
    extra_notes: list[str] = []
    freq_valid = True
    wins: list[_Win] = []
    sr_orig: int

    if source == "image":
        data = bytes(src) if not isinstance(src, (str, Path)) else Path(src).read_bytes()
        dig = digitize_image(
            data, paper_speed_mm_s=paper_speed_mm_s, px_per_mm=px_per_mm, roi=image_roi, cfg=cfg
        )
        freq_valid = False
        extra_notes = dig.notes
        limitations.append("Rasmdan olingan signal - taxminiy. Audio yozuv aniqroq.")
        limitations.append("Frequency features are invalid for image-sourced signals; ML models are blocked")
        sr_orig = int(dig.fs_eff)
        w = _analyze_window(
            dig.x, int(round(dig.fs_eff)), cfg, "image", 0.0, native_sr=dig.fs_eff, freq_valid=False
        )
        # image SQI: blend with q_img, never "good" (doc 10.2 item 5)
        blended = min(0.69, 0.6 * w.q.sqi + 0.4 * dig.q_img)
        w.q.sqi = blended
        w.q.level = level_for(blended, cfg)
        w.q.warnings.append("Rasmdan olingan signal - taxminiy")
        wins.append(w)
        allow_ml = False
    else:
        dec = decode_audio(src, cfg)
        sr_orig = dec.sr
        mono = select_channel(dec.x)
        if dec.n_channels > 1:
            limitations.append("Stereo recording: highest-energy unclipped channel used")
        for a, b in split_windows(mono, dec.sr, cfg):
            wins.append(_analyze_window(mono[a:b], dec.sr, cfg, "audio", a / dec.sr))
        if len(wins) > 1:
            limitations.append("Long recording: best-quality 30 s window analysed")

    best = max(wins, key=lambda w: w.q.sqi)
    pre, env, seg, q = best.pre, best.env, best.seg, best.q
    quality = _quality_schema(q)
    registry = registry if registry is not None else None

    pipeline = PipelineInfo(
        preprocess_version=PREPROCESS_VERSION,
        segmentation_method=SEGMENTATION_METHOD,
        ml_models=[],
        ml_available=False,
        duration_s=round(pre.duration_s, 2),
        sample_rate_hz=pre.sr,
        sample_rate_orig_hz=sr_orig,
        rule_version=MURMUR_RULE_VERSION,
        window_start_s=round(best.start_s, 2),
    )

    def finish(res: PcgAnalysisResult, arts: dict[str, bytes]) -> tuple[PcgAnalysisResult, dict[str, bytes]]:
        res.pipeline.processing_ms = int((time.perf_counter() - t_start) * 1000)
        return res, arts

    if q.level == "unusable":
        limitations.append("Signal sifati yaroqsiz: tahlil qilinmadi, qayta yozing")
        return finish(
            PcgAnalysisResult(
                source=source,
                status="rejected_low_quality",
                pipeline=pipeline,
                quality=quality,  # type: ignore[arg-type]
                limitations=limitations,
                error_code="LOW_QUALITY_REJECTED",
                error_message="Signal sifati juda past (SQI < 0.30): qayta yozib oling",
            ),
            {},
        )

    rhythm = feat.compute_rhythm(seg, age_years)
    intervals = feat.compute_intervals(seg)
    seg_out = SegmentationOut(
        method=seg.method,
        n_cycles_detected=seg.n_detected,
        n_cycles_valid=seg.n_valid,
        confidence=round(seg.confidence, 3),
        cycles=[
            CycleOut(
                idx=c.idx,
                s1_start_s=round(c.s1_start_s + best.start_s, 4),
                s1_end_s=round(c.s1_end_s + best.start_s, 4),
                s2_start_s=_r(None if c.s2_start_s is None else c.s2_start_s + best.start_s, 4),
                s2_end_s=_r(None if c.s2_end_s is None else c.s2_end_s + best.start_s, 4),
                next_s1_start_s=_r(
                    None if c.next_s1_start_s is None else c.next_s1_start_s + best.start_s, 4
                ),
                valid=c.valid,
            )
            for c in seg.cycles
        ],
    )
    if seg.rhythm_irregular:
        limitations.append("Ritm notekis (taxminan); EKG tavsiya etiladi")

    arts: dict[str, bytes] = {}
    art_names = Artifacts()
    if cfg.make_png:
        try:
            arts[ART_KEYS["spectrogram"]] = spec.spectrogram_png(pre.x_wide, pre.sr, seg.cycles)
            arts[ART_KEYS["waveform"]] = spec.waveform_png(pre.x, pre.sr, env, seg.cycles)
            if cfg.make_scalogram and freq_valid:
                arts[ART_KEYS["scalogram"]] = spec.scalogram_png(pre.x_wide, pre.sr, seg.cycles)
            arts[ART_KEYS["envelope"]] = spec.envelope_json(env)
            arts[ART_KEYS["peaks"]] = spec.wave_peaks_json(pre.x, pre.sr)
            art_names = Artifacts(
                waveform_png=ART_KEYS["waveform"],
                spectrogram_png=ART_KEYS["spectrogram"],
                scalogram_png=ART_KEYS["scalogram"] if ART_KEYS["scalogram"] in arts else None,
                envelope_json=ART_KEYS["envelope"],
                downsampled_wave_json=ART_KEYS["peaks"],
            )
        except Exception as exc:  # noqa: BLE001 - images must never fail the analysis
            limitations.append(f"Artefact PNG yaratilmadi: {type(exc).__name__}")

    if q.level == "poor":
        limitations.append("Signal sifati past: faqat HR va segmentatsiya ko'rsatiladi; murmur/ML bloklangan")
        return finish(
            PcgAnalysisResult(
                source=source,
                status="low_quality_partial",
                pipeline=pipeline,
                quality=quality,  # type: ignore[arg-type]
                rhythm=Rhythm(**{k: _r(v) if isinstance(v, float) else v for k, v in rhythm.items()}),
                segmentation=seg_out,
                intervals=Intervals(**{k: _r(v) for k, v in intervals.items()}),
                murmur=Murmur(present=None),
                classification=Classification(outcome="undetermined"),
                artifacts=art_names,
                limitations=limitations,
                feature_flags={"missing": ["*"], "frequency_features_valid": freq_valid},
            ),
            arts,
        )

    mr, mfeats = feat.analyze_murmur(pre.x_wide, pre.sr, env, seg, cfg, freq_valid=freq_valid)
    extras = feat.detect_extra_sounds(pre.x, pre.x_wide, pre.sr, seg, freq_valid=freq_valid)
    qd = {
        "sqi": q.sqi,
        "snr_db": q.snr_db,
        "artifact_ratio": q.artifact_ratio,
        "clip_ratio": q.clip_ratio,
        "duration_s": pre.duration_s,
    }
    features, flags = feat.build_features(rhythm, intervals, seg, mfeats, pre.x_wide, pre.sr, qd, freq_valid)
    features = {k: (None if v is None else round(float(v), 5)) for k, v in features.items()}
    murmur = clf.murmur_to_schema(mr, site, freq_valid)
    classification, refs, ml_used, notes = clf.classify(
        mr,
        rhythm,
        extras,
        features,
        q.sqi,
        q.level,
        seg.confidence,
        registry,
        allow_ml and registry is not None,
        cfg,
    )
    pipeline.ml_models = refs
    pipeline.ml_available = ml_used
    if not ml_used:
        limitations.append(
            "ML modeli mavjud emas: faqat qoidaga asoslangan tahlil (klinik validatsiyadan o'tmagan)"
        )
    limitations.extend(notes)
    limitations.extend(mr.notes)
    limitations.extend(extra_notes)
    limitations.append("S3/S4/klik/S2-bo'linish detektorlari past ishonchli (evristik)")
    if q.level == "acceptable":
        limitations.append("Signal sifati o'rtacha: ishonch pasaytirilgan")

    res = PcgAnalysisResult(
        source=source,
        status="ok",
        pipeline=pipeline,
        quality=quality,  # type: ignore[arg-type]
        rhythm=Rhythm(**{k: _r(v) if isinstance(v, float) else v for k, v in rhythm.items()}),
        segmentation=seg_out,
        intervals=Intervals(**{k: _r(v) for k, v in intervals.items()}),
        extra_sounds=[
            ExtraSound(type=e["type"], present=e["present"], confidence=round(e["confidence"], 3))
            for e in extras
        ],
        murmur=murmur,
        classification=classification,
        features=features,
        feature_flags=flags,
        artifacts=art_names,
        limitations=list(dict.fromkeys(limitations)),
    )
    return finish(res, arts)


__all__ = ["analyze_recording", "AudioError"]

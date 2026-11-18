"""Signal quality index (doc 02, section 3.5)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from .config import DEFAULT_CONFIG, MLConfig
from .envelope import Envelope
from .segmentation import Segmentation


@dataclass
class SQIResult:
    sqi: float
    level: str  # good|acceptable|poor|unusable
    snr_db: float
    q_snr: float
    q_period: float
    q_cycles: float
    q_art: float
    q_clip: float
    q_spec: float
    artifact_ratio: float
    clip_ratio: float
    warnings: list[str] = field(default_factory=list)


def _clip01(v: float) -> float:
    return float(np.clip(v, 0.0, 1.0))


def level_for(sqi: float, cfg: MLConfig = DEFAULT_CONFIG) -> str:
    if sqi >= cfg.sqi_good:
        return "good"
    if sqi >= cfg.sqi_acceptable:
        return "acceptable"
    if sqi >= cfg.sqi_poor:
        return "poor"
    return "unusable"


def compute_sqi(
    env: Envelope,
    seg: Segmentation,
    x_wide: np.ndarray,
    sr: int,
    artifact_ratio: float,
    clip_ratio: float,
    cfg: MLConfig = DEFAULT_CONFIG,
    freq_valid: bool = True,
) -> SQIResult:
    lin = env.lin
    # SNR: signal = mean of the strongest 25% of the linear envelope, noise = lowest 20% quantile
    noise = float(np.quantile(lin, 0.20)) + 1e-12
    sigp = float(np.mean(lin[lin >= np.quantile(lin, 0.75)])) + 1e-12
    snr_db = 10.0 * np.log10(sigp / noise)  # power ratio -> dB
    q_snr = _clip01((snr_db - 3.0) / (20.0 - 3.0))
    q_period = _clip01((seg.r1 - 0.2) / (0.7 - 0.2))
    q_cycles = _clip01((seg.n_valid - 2) / (6 - 2))
    q_art = _clip01(1.0 - artifact_ratio)
    q_clip = _clip01(1.0 - clip_ratio)
    if freq_valid and len(x_wide) > 512:
        f, p = sig.welch(x_wide, fs=sr, nperseg=512)
        lo = float(np.sum(p[(f >= 25) & (f <= 200)])) + 1e-18
        hi = float(np.sum(p[(f >= 400) & (f <= 1000)])) + 1e-18
        q_spec = _clip01((np.log10(lo / hi) - 0.3) / (1.3 - 0.3))
    else:
        q_spec = 0.5
    w = cfg.sqi_weights
    sqi = w[0] * q_snr + w[1] * q_period + w[2] * q_cycles + w[3] * q_art + w[4] * q_clip + w[5] * q_spec
    sqi = _clip01(sqi)
    level = level_for(sqi, cfg)
    warns: list[str] = []
    if level == "acceptable":
        warns.append("Signal sifati o'rtacha, natijaga ehtiyotkorlik bilan qarang")
    if level in ("poor", "unusable"):
        warns.append(
            "Signal sifati past: xonani tinchlantiring, stetoskopni qattiq bosing, nafasni 10 s ushlang va qayta yozing"
        )
    if clip_ratio > 0.01:
        warns.append("Signal klipping (to'yinish) belgilari bor")
    return SQIResult(
        sqi=sqi,
        level=level,
        snr_db=float(snr_db),
        q_snr=q_snr,
        q_period=q_period,
        q_cycles=q_cycles,
        q_art=q_art,
        q_clip=q_clip,
        q_spec=q_spec,
        artifact_ratio=artifact_ratio,
        clip_ratio=clip_ratio,
        warnings=warns,
    )

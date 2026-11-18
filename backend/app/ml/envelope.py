"""Shannon energy envelope (doc 02, section 4)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sig

from .config import DEFAULT_CONFIG, MLConfig

EPS = 1e-12


@dataclass
class Envelope:
    env: np.ndarray  # peak-picking envelope: mean of Shannon and Hilbert z-scores (see shannon_envelope)
    shannon: np.ndarray  # standardised, smoothed Shannon envelope (z-score)
    lin: np.ndarray  # linear (RMS^2) power envelope on the same grid
    hilbert: np.ndarray  # standardised Hilbert envelope on the same grid
    fs: float  # envelope rate (Hz), 100 by default
    t: np.ndarray  # time axis (s)


def _frame(x: np.ndarray, win: int, hop: int) -> np.ndarray:
    n = 1 + max(0, (len(x) - win) // hop)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def shannon_envelope(x: np.ndarray, sr: int, cfg: MLConfig = DEFAULT_CONFIG) -> Envelope:
    win = max(int(cfg.env_win_s * sr), 4)
    hop = max(int(cfg.env_hop_s * sr), 1)
    fs_env = sr / hop
    if len(x) < win:
        raise ValueError("signal too short for envelope")
    xn = x / (np.max(np.abs(x)) + EPS)
    frames = _frame(xn, win, hop)
    sq = frames**2
    shannon = -np.mean(sq * np.log(sq + EPS), axis=1)
    lin = np.mean(sq, axis=1)
    # standardise
    z = (shannon - shannon.mean()) / (shannon.std() + EPS)
    # smooth: Hann window of cfg.env_smooth_s
    sm_n = max(int(cfg.env_smooth_s * fs_env), 3)
    h = np.hanning(sm_n + 2)[1:-1]
    h /= h.sum()
    z = np.convolve(z, h, mode="same")
    lin_s = np.convolve(lin, h, mode="same")

    # Hilbert envelope on the same grid
    he = np.abs(sig.hilbert(xn))
    he_frames = _frame(he, win, hop)
    he_m = np.mean(he_frames, axis=1)
    he_m = np.convolve(he_m, h, mode="same")
    he_z = (he_m - he_m.mean()) / (he_m.std() + EPS)
    n = min(len(z), len(he_z), len(lin_s))
    t = (np.arange(n) * hop + win / 2) / sr
    # Shannon energy over-weights mid-amplitude content (strong murmurs can out-rank S2), so the
    # segmentation envelope is the average of the Shannon and (linear) Hilbert z-scores; both
    # agreeing is what doc 02 section 4 asks for.
    comb = 0.5 * (z[:n] + he_z[:n])
    comb = (comb - comb.mean()) / (comb.std() + EPS)
    return Envelope(env=comb, shannon=z[:n], lin=lin_s[:n], hilbert=he_z[:n], fs=fs_env, t=t)


def autocorr_period(
    env: np.ndarray, fs: float, lo_s: float = 0.30, hi_s: float = 1.7
) -> tuple[float | None, float]:
    """Return (period_s, peak_correlation r1) using envelope autocorrelation."""
    e = env - np.mean(env)
    if np.allclose(e, 0):
        return None, 0.0
    n = len(e)
    nfft = 1 << (2 * n - 1).bit_length()
    F = np.fft.rfft(e, nfft)
    ac = np.fft.irfft(F * np.conj(F))[:n]
    ac = ac / (ac[0] + EPS)
    lo = int(lo_s * fs)
    hi = min(int(hi_s * fs), n - 1)
    if hi <= lo + 2:
        return None, 0.0
    seg = ac[lo : hi + 1]
    peaks, props = sig.find_peaks(seg, height=0.0)
    if peaks.size == 0:
        return None, float(np.max(seg)) if seg.size else 0.0
    # prefer the first strong peak (fundamental), not just the max (could be a harmonic multiple)
    heights = props["peak_heights"]
    best = float(np.max(heights))
    pick = None
    for p, h in zip(peaks, heights, strict=False):
        if h >= 0.8 * best:
            pick = p
            break
    assert pick is not None
    lag = (lo + pick) / fs
    # parabolic refinement
    i = lo + pick
    if 1 <= i < len(ac) - 1:
        y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]
        denom = y0 - 2 * y1 + y2
        if abs(denom) > 1e-12:
            lag = (i + 0.5 * (y0 - y2) / denom) / fs
    return float(lag), float(ac[i])

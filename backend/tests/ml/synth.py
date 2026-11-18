"""Synthetic heart-sound generator for tests (S1/S2 pulses, optional murmur, noise)."""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf
from scipy import signal as sig


def _burst(n: int, sr: int, f0: float, dur: float, decay: float) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return np.sin(2 * np.pi * f0 * t) * np.exp(-t / decay) * np.hanning(len(t) + 2)[1:-1] ** 0.3


def make_pcg(
    duration=20.0,
    sr=4000,
    hr=72.0,
    systole=0.30,
    murmur=None,
    murmur_amp=0.0,
    noise=0.01,
    s1_amp=1.0,
    s2_amp=0.7,
    jitter=0.0,
    seed=0,
    diastolic_murmur=0.0,
    line_hum=0.0,
):
    """murmur: None | 'holosystolic' | 'midsystolic'. Returns (signal, truth dict)."""
    rng = np.random.default_rng(seed)
    n = int(duration * sr)
    x = np.zeros(n)
    T = 60.0 / hr
    t = 0.4
    truth = {"s1": [], "s2": [], "T": T}
    while t + T < duration:
        Tc = T * (1 + jitter * rng.standard_normal())
        s1 = _burst(0, sr, 55, 0.11, 0.04) * s1_amp
        s2 = _burst(0, sr, 95, 0.08, 0.025) * s2_amp
        i1 = int(t * sr)
        x[i1 : i1 + len(s1)] += s1[: n - i1]
        t2 = t + systole
        i2 = int(t2 * sr)
        if i2 + len(s2) < n:
            x[i2 : i2 + len(s2)] += s2
        truth["s1"].append(t)
        truth["s2"].append(t2)
        if murmur:
            a, b = t + 0.13, t2 - 0.01
            if murmur == "midsystolic":
                a, b = t + 0.14, t2 - 0.06
            ia, ib = int(a * sr), int(b * sr)
            ns = rng.standard_normal(ib - ia)
            bb, aa = sig.butter(3, [120, 380], btype="band", fs=sr)
            ns = sig.lfilter(bb, aa, ns)
            ns /= np.std(ns) + 1e-9
            env = np.ones(len(ns)) if murmur == "holosystolic" else np.hanning(len(ns))
            x[ia:ib] += murmur_amp * ns * env
        if diastolic_murmur:
            a, b = t2 + 0.10, t + Tc - 0.06
            ia, ib = int(a * sr), int(b * sr)
            if ib > ia and ib < n:
                ns = rng.standard_normal(ib - ia)
                bb, aa = sig.butter(3, [80, 250], btype="band", fs=sr)
                ns = sig.lfilter(bb, aa, ns)
                ns /= np.std(ns) + 1e-9
                x[ia:ib] += diastolic_murmur * ns * np.linspace(1, 0.4, len(ns))
        t += Tc
    x += noise * rng.standard_normal(n)
    if line_hum:
        x += line_hum * np.sin(2 * np.pi * 50 * np.arange(n) / sr)
    peak = np.max(np.abs(x)) + 1e-9
    return x / peak * 0.8, truth


def to_wav_bytes(x: np.ndarray, sr: int, subtype="PCM_16", fmt="WAV") -> bytes:
    buf = io.BytesIO()
    sf.write(buf, x, sr, format=fmt, subtype=subtype)
    return buf.getvalue()

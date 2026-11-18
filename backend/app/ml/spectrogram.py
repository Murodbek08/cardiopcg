"""Time-frequency images and UI helper data (doc 02, section 7)."""

from __future__ import annotations

import io
import json
from collections.abc import Iterable

import numpy as np
from scipy import signal as sig

from .envelope import Envelope
from .segmentation import Cycle

N_FFT = 256
HOP = 32
FMAX = 800.0


def stft_db(x: np.ndarray, sr: int, dyn_range: float = 80.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f, t, Z = sig.stft(x, fs=sr, window="hann", nperseg=N_FFT, noverlap=N_FFT - HOP, boundary=None)
    P = np.abs(Z) ** 2
    S = 10 * np.log10(P + 1e-10)
    S = S - S.max()
    S = np.maximum(S, -dyn_range)
    m = f <= min(FMAX, 0.5 * sr)
    return f[m], t + (N_FFT / 2) / sr, S[m]


def _fig_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
    return buf.getvalue()


def _mpl():
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    return plt


def _markers(ax, cycles: Iterable[Cycle], valid_only: bool = False) -> None:
    for c in cycles:
        if valid_only and not c.valid:
            continue
        ax.axvline(c.s1_start_s, color="#4aa3ff", lw=0.8, alpha=0.9)
        if c.s2_start_s is not None:
            ax.axvline(c.s2_start_s, color="#ffb347", lw=0.8, alpha=0.9)


def spectrogram_png(x_wide: np.ndarray, sr: int, cycles: list[Cycle]) -> bytes:
    plt = _mpl()
    f, t, S = stft_db(x_wide, sr)
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.pcolormesh(t, f, S, shading="auto", cmap="magma", vmin=-80, vmax=0)
    _markers(ax, cycles)
    ax.set_xlabel("Vaqt (s)")
    ax.set_ylabel("Chastota (Hz)")
    ax.set_title("Spektrogramma (ko'k: S1, to'q sariq: S2)")
    return _fig_bytes(fig)


def waveform_png(x: np.ndarray, sr: int, env: Envelope, cycles: list[Cycle]) -> bytes:
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(10, 2.8))
    t = np.arange(len(x)) / sr
    step = max(len(x) // 6000, 1)
    ax.plot(t[::step], x[::step], color="#555", lw=0.5)
    ev = env.shannon / (np.max(np.abs(env.shannon)) + 1e-9)
    ax.plot(env.t, ev, color="#d62728", lw=0.9, alpha=0.8, label="Shannon envelope")
    for c in cycles:
        col = "#4aa3ff" if c.valid else "#bbbbbb"
        ax.axvspan(c.s1_start_s, c.s1_end_s, color=col, alpha=0.35)
        if c.s2_start_s is not None and c.s2_end_s is not None:
            ax.axvspan(c.s2_start_s, c.s2_end_s, color="#ffb347" if c.valid else "#bbbbbb", alpha=0.35)
    ax.set_xlabel("Vaqt (s)")
    ax.set_ylabel("Amplituda")
    ax.legend(loc="upper right", fontsize=7)
    return _fig_bytes(fig)


def morlet_cwt_db(
    x: np.ndarray, sr: int, fmin: float = 20.0, fmax: float = 600.0, n: int = 64, w0: float = 6.0
):
    """Own FFT-based Morlet CWT (scipy.signal.cwt was removed). Returns (freqs, t, dB)."""
    dec = max(int(sr // (2.5 * fmax)), 1)
    xd = sig.decimate(x, dec, zero_phase=True) if dec > 1 else x
    fs = sr / dec
    freqs = np.geomspace(fmin, min(fmax, 0.45 * fs), n)
    N = len(xd)
    nfft = 1 << (N - 1).bit_length()
    X = np.fft.fft(xd, nfft)
    omega = 2 * np.pi * np.fft.fftfreq(nfft, d=1.0 / fs)
    out = np.empty((n, N))
    for i, f in enumerate(freqs):
        s = w0 / (2 * np.pi * f)
        psi = np.exp(-0.5 * (s * omega - w0) ** 2) * (omega > 0) * np.sqrt(s)
        out[i] = np.abs(np.fft.ifft(X * psi)[:N]) ** 2
    out_db = 10 * np.log10(out + 1e-10)
    out_db -= out_db.max()
    # downsample time axis to <= 1500 columns for plotting
    step = max(N // 1500, 1)
    t = np.arange(N)[::step] / fs
    return freqs, t, np.maximum(out_db[:, ::step], -80)


def scalogram_png(x_wide: np.ndarray, sr: int, cycles: list[Cycle]) -> bytes:
    plt = _mpl()
    freqs, t, db = morlet_cwt_db(x_wide, sr)
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.pcolormesh(t, freqs, db, shading="auto", cmap="viridis", vmin=-60, vmax=0)
    ax.set_yscale("log")
    _markers(ax, cycles)
    ax.set_xlabel("Vaqt (s)")
    ax.set_ylabel("Chastota (Hz)")
    ax.set_title("Skalogramma (Morlet CWT)")
    return _fig_bytes(fig)


def wave_peaks_json(x: np.ndarray, sr: int, points: int = 2000) -> bytes:
    """Min/max peaks for wavesurfer.js (`peaks` array, normalised -1..1)."""
    n = len(x)
    pts = min(points, max(n // 2, 1))
    edges = np.linspace(0, n, pts + 1).astype(int)
    mn, mx = [], []
    for a, b in zip(edges[:-1], edges[1:], strict=False):
        seg = x[a : max(b, a + 1)]
        mn.append(float(np.min(seg)))
        mx.append(float(np.max(seg)))
    scale = max(max(map(abs, mn + mx)), 1e-9)
    peaks = [round(v / scale, 4) for pair in zip(mn, mx, strict=False) for v in pair]
    return json.dumps({"sample_rate": sr, "duration_s": n / sr, "peaks": peaks}).encode()


def envelope_json(env: Envelope) -> bytes:
    step = 1
    return json.dumps(
        {
            "fs": env.fs,
            "t": [round(float(v), 4) for v in env.t[::step]],
            "shannon": [round(float(v), 4) for v in env.shannon[::step]],
        }
    ).encode()

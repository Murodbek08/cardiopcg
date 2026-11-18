"""Audio decoding, validation and preprocessing (doc 02, sections 2-3).

Pure numpy/scipy; pywt/librosa are NOT required. If PyWavelets is installed it is used for
wavelet denoising, otherwise a mild spectral gate is used instead.
"""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal as sig

from .config import DEFAULT_CONFIG, MLConfig


class AudioError(Exception):
    """Validation/decoding error carrying an API-style error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class DecodedAudio:
    x: np.ndarray  # float64, shape (n,) mono (or (n, ch) if keep_channels)
    sr: int
    n_channels: int
    duration_s: float


@dataclass
class Preprocessed:
    x: np.ndarray  # 25-400 Hz band (segmentation)
    x_wide: np.ndarray  # 20-800 Hz band (murmur frequency analysis)
    sr: int
    duration_s: float
    sr_orig: int
    clip_ratio: float
    artifact_ratio: float
    band_high_hz: float
    source: str = "audio"


# --------------------------------------------------------------------------- decoding


def _ffmpeg_decode(data: bytes) -> tuple[np.ndarray, int]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError("AUDIO_DECODE_FAILED", "Audio formatini o'qib bo'lmadi (ffmpeg mavjud emas)")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.bin"
        dst = Path(td) / "out.wav"
        src.write_bytes(data)
        cmd = [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(src),
            "-vn",
            "-acodec",
            "pcm_f32le",
            "-f",
            "wav",
            str(dst),
        ]
        try:
            subprocess.run(  # noqa: S603 - fixed argv, temp files only, 20 s timeout
                cmd,
                check=True,
                timeout=20,
                capture_output=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise AudioError("AUDIO_DECODE_FAILED", "Audio faylni dekod qilib bo'lmadi") from exc
        import soundfile as sf

        x, sr = sf.read(str(dst), dtype="float64", always_2d=True)
    return x, int(sr)


def decode_audio(
    src: bytes | bytearray | str | Path,
    cfg: MLConfig = DEFAULT_CONFIG,
) -> DecodedAudio:
    """Decode real audio (magic-bytes via libsndfile, ffmpeg fallback). Never trusts MIME."""
    import soundfile as sf

    if isinstance(src, (str, Path)):
        p = Path(src)
        if not p.is_file():
            raise AudioError("AUDIO_NOT_FOUND", "Audio fayl topilmadi")
        if p.stat().st_size > cfg.max_bytes:
            raise AudioError("AUDIO_TOO_LARGE", "Fayl 25 MB dan katta")
        data = p.read_bytes()
    else:
        data = bytes(src)
        if len(data) > cfg.max_bytes:
            raise AudioError("AUDIO_TOO_LARGE", "Fayl 25 MB dan katta")
    if len(data) < 64:
        raise AudioError("AUDIO_DECODE_FAILED", "Fayl bo'sh yoki buzilgan")

    try:
        x, sr = sf.read(io.BytesIO(data), dtype="float64", always_2d=True)
    except Exception:  # noqa: BLE001 - libsndfile does not know the container
        x, sr = _ffmpeg_decode(data)

    if x.size == 0:
        raise AudioError("AUDIO_DECODE_FAILED", "Audio bo'sh")
    if not np.all(np.isfinite(x)):
        x = np.nan_to_num(x)
    n_ch = x.shape[1]
    duration = x.shape[0] / float(sr)
    if sr < cfg.min_sample_rate:
        raise AudioError(
            "SAMPLE_RATE_TOO_LOW", f"Namuna chastotasi juda past ({sr} Hz < {cfg.min_sample_rate} Hz)"
        )
    if duration < cfg.min_duration_s:
        raise AudioError(
            "AUDIO_TOO_SHORT", f"Yozuv juda qisqa ({duration:.1f} s < {cfg.min_duration_s:.0f} s)"
        )
    return DecodedAudio(x=x, sr=int(sr), n_channels=n_ch, duration_s=duration)


def select_channel(x2d: np.ndarray) -> np.ndarray:
    """Mono: single channel as is; stereo -> channel with the highest low-band energy share."""
    if x2d.ndim == 1:
        return x2d
    if x2d.shape[1] == 1:
        return x2d[:, 0]
    energies = np.sqrt(np.mean(x2d**2, axis=0))
    # prefer the channel with the highest RMS but not clipped; fall back to mean
    clip = np.mean(np.abs(x2d) >= 0.99, axis=0)
    score = energies * (1.0 - clip)
    if np.max(score) <= 0:
        return np.mean(x2d, axis=1)
    return x2d[:, int(np.argmax(score))]


def split_windows(
    x: np.ndarray, sr: int, cfg: MLConfig = DEFAULT_CONFIG, max_windows: int = 6
) -> list[tuple[int, int]]:
    """Return (start, end) sample indices. Records <= max_duration are a single window."""
    n = len(x)
    if n / sr <= cfg.max_duration_s:
        return [(0, n)]
    w = int(cfg.window_s * sr)
    starts = np.linspace(0, n - w, num=min(max_windows, max(2, n // w))).astype(int)
    return [(int(s), int(s) + w) for s in starts]


# --------------------------------------------------------------------------- filters


def resample(x: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return x
    g = math.gcd(int(sr), int(target))
    return sig.resample_poly(x, int(target) // g, int(sr) // g)


def bandpass(x: np.ndarray, fs: float, low: float, high: float, order: int = 4) -> np.ndarray:
    high = min(high, 0.45 * fs)
    sos = sig.butter(order, [low, high], btype="band", fs=fs, output="sos")
    return sig.sosfiltfilt(sos, x)


def highpass(x: np.ndarray, fs: float, fc: float, order: int = 2) -> np.ndarray:
    sos = sig.butter(order, fc, btype="high", fs=fs, output="sos")
    return sig.sosfiltfilt(sos, x)


def notch(x: np.ndarray, fs: float, f0: float, q: float) -> np.ndarray:
    if f0 >= 0.45 * fs:
        return x
    b, a = sig.iirnotch(f0, q, fs=fs)
    return sig.filtfilt(b, a, x)


def despike(x: np.ndarray, fs: float, max_iter: int = 5) -> tuple[np.ndarray, float]:
    """Schmidt-style despike: remove impulsive artefacts. Returns (signal, artifact_ratio)."""
    x = x.copy()
    w = int(0.5 * fs)
    if w < 8 or len(x) < 2 * w:
        return x, 0.0
    n_frames = len(x) // w
    modified = np.zeros(len(x), dtype=bool)
    for _ in range(max_iter):
        frames = x[: n_frames * w].reshape(n_frames, w)
        maa = np.max(np.abs(frames), axis=1)
        med = np.median(maa)
        if med <= 0:
            break
        bad = np.where(maa > 3.0 * med)[0]
        if bad.size == 0:
            break
        i = int(bad[np.argmax(maa[bad])])
        seg = frames[i]
        # replace the artefact region (|x| > 2*median MAA) with a scaled-down copy
        mask = np.abs(seg) > 2.0 * med
        if not mask.any():
            break
        seg = np.where(mask, np.sign(seg) * med * 0.5, seg)
        x[i * w : (i + 1) * w] = seg
        modified[i * w : (i + 1) * w] = True
    return x, float(np.mean(modified))


def _spectral_gate(x: np.ndarray, fs: float) -> np.ndarray:
    """Mild spectral gating. Noise profile: 10th percentile of magnitude per frequency bin."""
    nper = 256
    f, t, Z = sig.stft(x, fs=fs, nperseg=nper, noverlap=nper * 3 // 4, boundary="zeros")
    mag = np.abs(Z)
    noise = np.percentile(mag, 10, axis=1, keepdims=True)
    gain = np.clip(1.0 - 1.0 * noise / (mag + 1e-12), 0.2, 1.0)
    _, y = sig.istft(Z * gain, fs=fs, nperseg=nper, noverlap=nper * 3 // 4)
    y = y[: len(x)]
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    return y


def _wavelet_denoise(x: np.ndarray) -> np.ndarray | None:
    try:
        import pywt  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    coeffs = pywt.wavedec(x, "db6", level=5)
    sigma = np.median(np.abs(coeffs[-1])) / 0.6745
    thr = sigma * math.sqrt(2 * math.log(max(len(x), 2)))
    for i in (-1, -2):  # d1, d2 only
        coeffs[i] = pywt.threshold(coeffs[i], thr, mode="soft")
    y = pywt.waverec(coeffs, "db6")
    return y[: len(x)]


def denoise(x: np.ndarray, fs: float) -> np.ndarray:
    y = _wavelet_denoise(x)
    if y is None:
        y = _spectral_gate(x, fs)
    return y


# --------------------------------------------------------------------------- main


def preprocess(
    x: np.ndarray,
    sr: int,
    cfg: MLConfig = DEFAULT_CONFIG,
    source: str = "audio",
    native_sr: float | None = None,
) -> Preprocessed:
    """doc 3.1. `native_sr` = true information bandwidth rate (images: pixels/s)."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        x = select_channel(x)
    x = np.nan_to_num(x)
    # clipping = many samples sitting exactly at the (flat) peak value
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    clip_ratio = float(np.mean(np.abs(x) >= 0.995 * peak)) if peak > 0.05 else 0.0
    if clip_ratio < 0.0005 or clip_ratio > 0.5:
        clip_ratio = 0.0
    x = x - np.mean(x)

    # doc 3.2: TARGET_SR = min(4000, sr)
    target = min(cfg.target_sr, sr) if source == "audio" else min(cfg.target_sr, max(int(sr), 1000))
    if source == "image":
        target = 1000
    xr = resample(x, sr, target)
    info_sr = float(native_sr) if native_sr else float(target)
    band_high = min(cfg.bp_high, 0.45 * min(info_sr, target))
    wide_high = min(cfg.wide_high, 0.45 * min(info_sr, target))

    xr = highpass(xr, target, cfg.baseline_hp)
    xn = notch(xr, target, cfg.notch_hz, cfg.notch_q)
    wide = bandpass(xn, target, cfg.wide_low, wide_high, cfg.bp_order)
    nar = bandpass(xn, target, cfg.bp_low, band_high, cfg.bp_order)
    artifact_ratio = 0.0
    if cfg.denoise:
        nar = denoise(nar, target)
    if cfg.despike:
        nar, artifact_ratio = despike(nar, target)
        wide, _ = despike(wide, target)
    scale = float(np.percentile(np.abs(nar), 99.5)) + 1e-9
    nar = np.clip(nar / scale, -1.5, 1.5)
    wide = np.clip(wide / (float(np.percentile(np.abs(wide), 99.5)) + 1e-9), -1.5, 1.5)
    return Preprocessed(
        x=nar,
        x_wide=wide,
        sr=target,
        duration_s=len(nar) / target,
        sr_orig=int(sr),
        clip_ratio=clip_ratio,
        artifact_ratio=artifact_ratio,
        band_high_hz=band_high,
        source=source,
    )

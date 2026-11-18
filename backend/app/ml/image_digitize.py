"""PCG image (printout / screenshot) -> 1D signal digitisation, basic path (doc 02, section 10).

Supports PNG/JPG/WEBP/BMP. PDF is NOT supported here (convert the page to PNG first).
Limitations (honest): the trace-follower assumes one dark continuous trace on a lighter
(possibly gridded) background; frequency content above ~half the pixel sampling rate is lost,
so murmur frequency features are marked invalid for image-sourced analyses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import DEFAULT_CONFIG, MLConfig
from .preprocess import AudioError


class ImageError(AudioError):
    pass


@dataclass
class DigitizedSignal:
    x: np.ndarray
    fs_eff: float  # effective sampling rate in "pixels per second"
    q_img: float
    px_per_mm: float
    calibration: str  # "manual" | "grid_auto"
    notes: list[str] = field(default_factory=list)


def _estimate_px_per_mm(img_bgr: np.ndarray, trace_mask: np.ndarray) -> float | None:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float64)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float64)
    # grid is the "ink" that is not the trace: use saturation if the image is coloured, else darkness
    chan = sat if sat.mean() > 12 else (255 - gray)
    chan = chan.copy()
    chan[trace_mask > 0] = np.median(chan)
    col = chan.mean(axis=0)
    col = col - col.mean()
    n = len(col)
    if n < 200 or np.allclose(col, 0):
        return None
    nfft = 1 << (2 * n - 1).bit_length()
    F = np.fft.rfft(col, nfft)
    ac = np.fft.irfft(F * np.conj(F))[:n]
    ac /= ac[0] + 1e-12
    lo, hi = 3, min(60, n // 2)
    seg = ac[lo:hi]
    if seg.size < 5:
        return None
    mx = float(seg.max())
    if mx < 0.15:
        return None
    # smallest lag with a strong peak = minor grid (1 mm)
    for i in range(1, len(seg) - 1):
        if seg[i] >= 0.5 * mx and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            return float(lo + i)
    return None


def digitize_image(
    data: bytes,
    *,
    paper_speed_mm_s: float = 25.0,
    px_per_mm: float | None = None,
    roi: tuple[int, int, int, int] | None = None,
    cfg: MLConfig = DEFAULT_CONFIG,
) -> DigitizedSignal:
    if len(data) > cfg.image_max_bytes:
        raise ImageError("IMAGE_TOO_LARGE", "Rasm 15 MB dan katta")
    if data[:4] == b"%PDF":
        raise ImageError("UNSUPPORTED_FORMAT", "PDF qo'llab-quvvatlanmaydi: sahifani PNG qilib yuklang")
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # decoding drops EXIF/metadata
    if img is None:
        raise ImageError("IMAGE_DECODE_FAILED", "Rasmni o'qib bo'lmadi")
    if roi is not None:
        x0, y0, w, h = roi
        img = img[max(y0, 0) : y0 + h, max(x0, 0) : x0 + w]
        if img.size == 0:
            raise ImageError("IMAGE_ROI_INVALID", "ROI noto'g'ri")
    elif img.shape[1] < cfg.image_min_width_px:
        raise ImageError(
            "IMAGE_TOO_SMALL", f"Rasm kengligi kamida {cfg.image_min_width_px} px bo'lishi kerak"
        )

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    otsu, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(np.clip(otsu, 60.0, 115.0))  # Otsu degenerates when the trace is a tiny pixel fraction
    mask = (v < thr).astype(np.uint8)
    # keep the widest connected component (the trace); drops text, dark grid residue
    n_lab, labels, stats_, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n_lab <= 1:
        raise ImageError("TRACE_NOT_FOUND", "Signal chizig'i topilmadi")
    widths = stats_[1:, cv2.CC_STAT_WIDTH]
    keep = 1 + int(np.argmax(widths))
    trace = (labels == keep).astype(np.uint8)
    W = img.shape[1]
    if stats_[keep, cv2.CC_STAT_WIDTH] < 0.4 * W:
        raise ImageError("TRACE_NOT_FOUND", "Signal chizig'i uzluksiz emas yoki juda qisqa")
    grid_residue = float(mask.sum() - trace.sum()) / float(max(mask.sum(), 1))

    ys = np.full(W, np.nan)
    cols = np.where(trace.any(axis=0))[0]
    for c in cols:
        rows = np.where(trace[:, c] > 0)[0]
        ys[c] = np.median(rows)
    valid = ~np.isnan(ys)
    first, last = int(cols.min()), int(cols.max())
    idx = np.arange(first, last + 1)
    ys = np.interp(idx, idx[valid[first : last + 1]], ys[first : last + 1][valid[first : last + 1]])
    gap_ratio = 1.0 - float(valid[first : last + 1].mean())
    sig_ = -(ys - np.median(ys))

    notes = ["Rasmdan olingan signal - taxminiy. Audio yozuv aniqroq."]
    calibration = "manual"
    if px_per_mm is None:
        est = _estimate_px_per_mm(img, trace)
        if est is None:
            raise ImageError("CALIBRATION_REQUIRED", "To'r masshtabini aniqlab bo'lmadi: px_per_mm kiriting")
        px_per_mm = est
        calibration = "grid_auto"
        notes.append(
            "Vaqt masshtabi to'rdan avtomatik aniqlandi; qog'oz tezligi foydalanuvchi bergan qiymat."
        )
    fs_eff = float(paper_speed_mm_s) * float(px_per_mm)
    if fs_eff < 120:
        notes.append("Piksel tezligi past: yuqori chastotali ma'lumot yo'qolgan")
    q = float(
        np.clip(1.0 - 2.5 * gap_ratio - 0.5 * grid_residue, 0, 1) * (1.0 if calibration == "manual" else 0.9)
    )
    return DigitizedSignal(
        x=sig_, fs_eff=fs_eff, q_img=q, px_per_mm=float(px_per_mm), calibration=calibration, notes=notes
    )

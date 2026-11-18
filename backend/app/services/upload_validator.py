"""Upload validation chain (doc 01 section 4). The first failing step aborts the upload."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from PIL import Image

from app.core.errors import AppError

AUDIO_EXTS = {"wav", "mp3", "flac"}
IMAGE_EXTS = {"png", "jpg", "jpeg"}
BLOCKED_EXTS = {
    "exe",
    "js",
    "html",
    "htm",
    "svg",
    "zip",
    "rar",
    "7z",
    "bat",
    "cmd",
    "sh",
    "php",
    "py",
    "dll",
    "com",
    "scr",
    "jar",
    "msi",
    "vbs",
    "ps1",
    "jsp",
    "asp",
    "aspx",
    "xml",
    "xhtml",
    "swf",
    "apk",
    "iso",
    "gz",
    "tar",
}
MIME_BY_EXT = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
Image.MAX_IMAGE_PIXELS = int(25e6)


@dataclass
class Limits:
    max_audio_mb: int = 25
    max_image_mb: int = 10
    min_duration_sec: float = 5
    max_duration_sec: float = 120


@dataclass
class ValidatedFile:
    kind: str  # audio | other_image
    ext: str
    mime: str
    path: Path
    size: int
    sha256: str
    safe_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def sanitize_filename(raw: str | None) -> tuple[str, str]:
    """Returns (safe_name, ext). Raises 415 on blocked/double extensions or unsupported types."""
    name = (raw or "").replace("\\", "/").split("/")[-1].strip().strip(".")
    if not name:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Fayl nomi bo'sh")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:255]
    parts = name.lower().split(".")
    if len(parts) < 2:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Fayl kengaytmasi yo'q")
    ext = parts[-1]
    if any(p in BLOCKED_EXTS for p in parts[1:]):
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Xavfli fayl turi/qo'sh kengaytma rad etildi")
    if ext not in AUDIO_EXTS | IMAGE_EXTS:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", f"Qo'llab-quvvatlanmaydigan kengaytma: .{ext}")
    return name, ext


def sniff(head: bytes) -> str | None:
    """Content-based type detection (magic bytes). Client Content-Type is never trusted."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


def check_content_type(path: Path, ext: str) -> str:
    with open(path, "rb") as f:
        head = f.read(16)
    detected = sniff(head)
    canon = "jpg" if ext == "jpeg" else ext
    if detected is None or detected != canon:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "Fayl mazmuni kengaytmaga mos kelmaydi",
            {"declared": ext, "detected": detected},
        )
    return MIME_BY_EXT[ext]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def analyze_audio(path: Path, limits: Limits) -> tuple[dict[str, Any], list[str]]:
    """Decode fully in blocks (bounded memory), compute quality stats. Raises 422 AUDIO_* errors."""
    warnings: list[str] = []
    try:
        info = sf.info(str(path))
    except Exception:
        raise AppError(422, "AUDIO_CORRUPT", "Audio fayl o'qilmadi yoki buzuq")
    sr, ch = int(info.samplerate), int(info.channels)
    if sr <= 0 or ch < 1:
        raise AppError(422, "AUDIO_CORRUPT", "Audio sarlavhasi noto'g'ri")
    if ch > 2:
        raise AppError(422, "AUDIO_CORRUPT", "Faqat mono yoki stereo audio qabul qilinadi")
    if sr > 96000:
        raise AppError(422, "AUDIO_CORRUPT", "Namuna chastotasi 96 kHz dan oshmasligi kerak")
    if sr < 2000:
        warnings.append(f"LOW_SAMPLE_RATE:{sr}")
    if info.frames and info.frames / sr > limits.max_duration_sec + 0.5:
        raise AppError(
            422, "AUDIO_TOO_LONG", f"Davomiylik {limits.max_duration_sec:.0f} s dan oshmasligi kerak"
        )

    max_frames = int((limits.max_duration_sec + 0.5) * sr)
    total = 0
    sumsq = 0.0
    sum_ = 0.0
    peak = 0.0
    clipped = 0
    frame_energy: list[float] = []
    hop = max(int(sr * 0.05), 1)
    carry = np.zeros(0, dtype=np.float32)
    try:
        for block in sf.blocks(str(path), blocksize=sr, dtype="float32", always_2d=True):
            mono = block.mean(axis=1) if block.shape[1] > 1 else block[:, 0]
            total += mono.shape[0]
            if total > max_frames:
                raise AppError(
                    422, "AUDIO_TOO_LONG", f"Davomiylik {limits.max_duration_sec:.0f} s dan oshmasligi kerak"
                )
            sumsq += float(np.dot(mono, mono))
            sum_ += float(mono.sum())
            a = np.abs(block)
            peak = max(peak, float(a.max()) if a.size else 0.0)
            clipped += int((a >= 0.999).any(axis=1).sum())
            buf = np.concatenate([carry, mono])
            n_full = buf.shape[0] // hop
            if n_full:
                fr = buf[: n_full * hop].reshape(n_full, hop)
                frame_energy.extend((fr * fr).mean(axis=1).tolist())
            carry = buf[n_full * hop :]
    except AppError:
        raise
    except Exception:
        raise AppError(
            422, "AUDIO_CORRUPT", "Audio fayl dekodlanmadi (buzuq yoki qo'llab-quvvatlanmaydigan kodek)"
        )

    if total == 0:
        raise AppError(422, "AUDIO_CORRUPT", "Audio bo'sh")
    duration = total / sr
    if duration < limits.min_duration_sec:
        raise AppError(
            422, "AUDIO_TOO_SHORT", f"Davomiylik kamida {limits.min_duration_sec:.0f} s bo'lishi kerak"
        )
    rms = (sumsq / total) ** 0.5
    rms_dbfs = 20 * np.log10(rms) if rms > 0 else -120.0
    if rms_dbfs < -60:
        raise AppError(422, "AUDIO_SILENT", "Audio deyarli jim (signal topilmadi)")
    clip_ratio = clipped / total
    if clip_ratio > 0.05:
        raise AppError(422, "AUDIO_CLIPPED", "Signal haddan tashqari kesilgan (klipping > 5%)")
    if clip_ratio > 0.01:
        warnings.append(f"CLIPPING:{clip_ratio:.3f}")

    fe = np.asarray(frame_energy) if frame_energy else np.asarray([rms * rms])
    p_hi = float(np.percentile(fe, 90)) + 1e-12
    p_lo = float(np.percentile(fe, 10)) + 1e-12
    snr_db = float(np.clip(10 * np.log10(p_hi / p_lo), 0, 60))
    quality = float(np.clip(snr_db / 30.0, 0, 1) * (1 - min(clip_ratio * 20, 0.5)))
    if quality < 0.3:
        warnings.append("LOW_QUALITY: signal sifati past, qayta yozish tavsiya etiladi")
    bit_depth = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "PCM_U8": 8, "FLOAT": 32, "DOUBLE": 64}.get(
        info.subtype or ""
    )
    codec = {"WAV": "pcm_" + (info.subtype or "").lower(), "FLAC": "flac", "MP3": "mp3", "MPEG": "mp3"}.get(
        info.format, info.format.lower()
    )
    meta = {
        "duration_sec": round(duration, 3),
        "sample_rate_hz": sr,
        "channels": ch,
        "bit_depth": bit_depth,
        "codec": codec,
        "snr_db": round(snr_db, 2),
        "quality_score": round(quality, 3),
        "rms_dbfs": round(float(rms_dbfs), 1),
        "clip_ratio": round(clip_ratio, 5),
        "dc_offset": round(sum_ / total, 6),
    }
    return meta, warnings


def process_image(path: Path, ext: str, out_path: Path) -> dict[str, Any]:
    """Verify with Pillow, re-encode (strips EXIF/metadata), protect against image bombs."""
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
            if w * h > Image.MAX_IMAGE_PIXELS:
                raise AppError(422, "IMAGE_TOO_LARGE", "Rasm o'lchami juda katta")
            fmt = "PNG" if ext == "png" else "JPEG"
            im2 = im.convert("RGB") if fmt == "JPEG" else im.copy()
            buf = BytesIO()
            im2.save(buf, fmt)
        out_path.write_bytes(buf.getvalue())
    except AppError:
        raise
    except Exception:
        raise AppError(422, "IMAGE_CORRUPT", "Rasm fayli buzuq")
    return {"width_px": w, "height_px": h}

"""Rhythm, intervals, extra sounds, murmur analysis and feature vector (doc 02, sections 6-8).

Everything is rule based and uncalibrated: thresholds come from `config.MLConfig`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import fft as sfft
from scipy import signal as sig
from scipy import stats

from .config import DEFAULT_CONFIG, MLConfig, hr_range_for_age
from .envelope import EPS, Envelope, _frame
from .segmentation import Cycle, Segmentation

BANDS = [(25, 50), (50, 100), (100, 200), (200, 400), (400, 800)]


# --------------------------------------------------------------------------- rhythm / intervals


def compute_rhythm(seg: Segmentation, age_years: float | None = None) -> dict[str, Any]:
    durs = np.array(seg.cycle_durations, dtype=float)
    valid_T = []
    for c in seg.cycles:
        if c.valid and c.next_s1_start_s is not None:
            valid_T.append(c.next_s1_start_s - c.s1_start_s)
    T = np.array(valid_T if len(valid_T) >= 2 else durs, dtype=float)
    out: dict[str, Any] = {
        "hr_bpm": None,
        "hr_std": None,
        "hr_min": None,
        "hr_max": None,
        "rhythm_irregular": bool(seg.rhythm_irregular),
        "cycle_cv": seg.cycle_cv,
        "category": "undetermined",
    }
    if T.size == 0:
        return out
    hr_i = 60.0 / T
    out.update(
        hr_bpm=float(60.0 / np.median(T)),
        hr_std=float(np.std(hr_i)),
        hr_min=float(np.min(hr_i)),
        hr_max=float(np.max(hr_i)),
    )
    lo, hi = hr_range_for_age(age_years)
    hr = out["hr_bpm"]
    if seg.rhythm_irregular:
        out["category"] = "irregular"
    elif hr < lo:
        out["category"] = "bradycardia"
    elif hr > hi:
        out["category"] = "tachycardia"
    else:
        out["category"] = "normal"
    return out


def compute_intervals(seg: Segmentation) -> dict[str, Any]:
    sys_, dia, sysdur, s1d, s2d, T = [], [], [], [], [], []
    for c in seg.cycles:
        if not c.valid:
            continue
        sys_.append(c.s2_start_s - c.s1_start_s)  # type: ignore[operator]
        sysdur.append(c.s2_end_s - c.s1_start_s)  # type: ignore[operator]
        dia.append(c.next_s1_start_s - c.s2_end_s)  # type: ignore[operator]
        s1d.append(c.s1_end_s - c.s1_start_s)
        s2d.append(c.s2_end_s - c.s2_start_s)  # type: ignore[operator]
        T.append(c.next_s1_start_s - c.s1_start_s)  # type: ignore[operator]
    if not sys_:
        return {
            "systole_ms": None,
            "diastole_ms": None,
            "sd_ratio": None,
            "sys_frac": None,
            "systole_corr_ms": None,
            "s1_dur_ms": None,
            "s2_dur_ms": None,
        }
    med = lambda a: float(np.median(a))  # noqa: E731
    systole = med(sysdur)
    diastole = med(dia)
    Tm = med(T)
    return {
        "systole_ms": systole * 1000,
        "diastole_ms": diastole * 1000,
        "sd_ratio": systole / diastole if diastole > 0 else None,
        "sys_frac": systole / Tm if Tm > 0 else None,
        "systole_corr_ms": systole * 1000 / math.sqrt(Tm) if Tm > 0 else None,  # Bazett-style
        "s1_dur_ms": med(s1d) * 1000,
        "s2_dur_ms": med(s2d) * 1000,
    }


# --------------------------------------------------------------------------- helpers


def _idx(env_t0: float, fs: float, t: float, n: int) -> int:
    return int(np.clip(round((t - env_t0) * fs), 0, n - 1))


def power_envelope(x: np.ndarray, sr: int, cfg: MLConfig) -> np.ndarray:
    win = max(int(cfg.env_win_s * sr), 4)
    hop = max(int(cfg.env_hop_s * sr), 1)
    xn = x / (np.max(np.abs(x)) + EPS)
    return np.mean(_frame(xn, win, hop) ** 2, axis=1)


def spectral_stats(xs: np.ndarray, sr: int) -> dict[str, float]:
    nper = int(min(256, len(xs)))
    if nper < 32:
        return {}
    f, p = sig.welch(xs, fs=sr, nperseg=nper, noverlap=nper // 2)
    m = (f >= 20) & (f <= min(800, 0.5 * sr))
    f, p = f[m], p[m]
    tot = float(np.sum(p)) + 1e-30
    cen = float(np.sum(f * p) / tot)
    bw = float(math.sqrt(np.sum((f - cen) ** 2 * p) / tot))
    cs = np.cumsum(p) / tot
    roll = float(f[int(np.searchsorted(cs, 0.85))]) if len(f) else 0.0
    flat = float(np.exp(np.mean(np.log(p + 1e-30))) / (np.mean(p) + 1e-30))
    out = {
        "f_peak": float(f[int(np.argmax(p))]),
        "f_centroid": cen,
        "bandwidth": bw,
        "rolloff85": roll,
        "flatness": flat,
    }
    for lo, hi in BANDS:
        out[f"band_{lo}_{hi}"] = float(np.sum(p[(f >= lo) & (f < hi)]) / tot)
    lo_e = float(np.sum(p[(f >= 25) & (f < 100)])) + 1e-30
    hi_e = float(np.sum(p[(f >= 100) & (f < 400)]))
    out["band_ratio_hl"] = hi_e / lo_e
    ok = (f > 0) & (p > 0)
    out["spectral_slope"] = float(np.polyfit(np.log(f[ok]), np.log(p[ok]), 1)[0]) if ok.sum() > 3 else 0.0
    return out


def freq_class(f_centroid: float) -> str:
    if f_centroid < 100:
        return "low"
    if f_centroid <= 300:
        return "medium"
    return "high"


def mfcc_stats(x: np.ndarray, sr: int, n_mfcc: int = 20, n_mels: int = 40) -> dict[str, float]:
    n_fft, hop = 256, 32
    if len(x) < n_fft * 2:
        return {}
    f, t, Z = sig.stft(x, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, boundary=None)
    P = np.abs(Z) ** 2
    fmin, fmax = 20.0, min(800.0, 0.5 * sr)
    mel = lambda hz: 2595 * np.log10(1 + hz / 700)  # noqa: E731
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)  # noqa: E731
    pts = imel(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    fb = np.zeros((n_mels, len(f)))
    for i in range(n_mels):
        lo_, c, r = pts[i], pts[i + 1], pts[i + 2]
        up = (f - lo_) / (c - lo_ + EPS)
        dn = (r - f) / (r - c + EPS)
        fb[i] = np.maximum(0, np.minimum(up, dn))
    S = np.log(fb @ P + 1e-10)
    C = sfft.dct(S, type=2, axis=0, norm="ortho")[:n_mfcc]
    out: dict[str, float] = {}
    for k in range(n_mfcc):
        out[f"mfcc_{k + 1}_mean"] = float(np.mean(C[k]))
        out[f"mfcc_{k + 1}_std"] = float(np.std(C[k]))
    return out


# --------------------------------------------------------------------------- murmur


@dataclass
class MurmurWindow:
    present: bool
    timing: str
    R_med: float
    frac: float
    shape: str
    spectral: dict[str, float]
    grade_est: str
    grade_confidence: float
    ratio_to_heart_sounds: float
    profile: np.ndarray | None = None


@dataclass
class MurmurResult:
    assessable: bool
    present: bool | None
    probability: float | None
    systolic: MurmurWindow | None
    diastolic: MurmurWindow | None
    p_sys: float = 0.0
    p_dia: float = 0.0
    extra: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _sigmoid(v: float) -> float:
    return float(1.0 / (1.0 + math.exp(-max(min(v, 30), -30))))


def _profile_shape(prof: np.ndarray) -> tuple[str, float, float]:
    """Return (shape, slope_norm, diamond_r2) from a per-window mean profile (power above floor)."""
    p = np.maximum(prof, 0)
    if p.max() <= 0 or np.mean(p) <= 0:
        return "plateau", 0.0, 0.0
    t = np.linspace(0, 1, len(p))
    pn = p / np.mean(p)
    slope = float(np.polyfit(t, pn, 1)[0])
    coef = np.polyfit(t, pn, 2)
    fit = np.polyval(coef, t)
    ss_res = float(np.sum((pn - fit) ** 2))
    ss_tot = float(np.sum((pn - pn.mean()) ** 2)) + EPS
    r2 = 1 - ss_res / ss_tot
    t_max = float(t[int(np.argmax(fit))])
    if coef[0] < 0 and r2 > 0.6 and 0.25 <= t_max <= 0.75 and (pn.max() / (pn.min() + 0.05)) > 2.0:
        return "crescendo_decrescendo", slope, r2
    if abs(slope) < 0.6:
        return "plateau", slope, r2
    return ("crescendo" if slope > 0 else "decrescendo"), slope, r2


def _timing_label(kind: str, coverage: float, tc: float) -> str:
    pre = "sys" if kind == "sys" else "dia"
    if coverage >= 0.8:
        return "holosystolic" if kind == "sys" else "holodiastolic"
    if tc < 1 / 3:
        return f"early_{pre}"
    if tc < 2 / 3:
        return f"mid_{pre}"
    return f"late_{pre}"


def analyze_murmur(
    pre_wide: np.ndarray,
    sr: int,
    env: Envelope,
    seg: Segmentation,
    cfg: MLConfig = DEFAULT_CONFIG,
    freq_valid: bool = True,
) -> tuple[MurmurResult, dict[str, float]]:
    """Returns (MurmurResult, per-cycle feature aggregates)."""
    feats: dict[str, float] = {}
    valid = [c for c in seg.cycles if c.valid]
    lw = power_envelope(pre_wide, sr, cfg)
    n = min(len(lw), len(env.t))
    lw = lw[:n]
    fs = env.fs
    t0 = float(env.t[0])
    if len(valid) < 3 or n < 50:
        return (
            MurmurResult(
                False,
                None,
                None,
                None,
                None,
                notes=["Murmur baholash uchun yaroqli sikllar yetarli emas (<3)"],
            ),
            feats,
        )

    # --- quiet floor: frames outside S1/S2 regions (dilated by 30 ms)
    mask = np.ones(n, dtype=bool)
    for c in seg.cycles:
        for a, b in ((c.s1_start_s, c.s1_end_s), (c.s2_start_s, c.s2_end_s)):
            if a is None or b is None:
                continue
            mask[_idx(t0, fs, a - 0.03, n) : _idx(t0, fs, b + 0.03, n) + 1] = False
    quiet = lw[mask]
    if quiet.size < 20:
        quiet = lw
    floor = float(np.percentile(quiet, 10)) + 1e-12

    # S1/S2 reference energy
    hs = []
    for c in valid:
        hs.append(np.mean(lw[_idx(t0, fs, c.s1_start_s, n) : _idx(t0, fs, c.s1_end_s, n) + 1]))
        hs.append(np.mean(lw[_idx(t0, fs, c.s2_start_s, n) : _idx(t0, fs, c.s2_end_s, n) + 1]))  # type: ignore[arg-type]
    hs_mean = float(np.mean(hs)) + 1e-12

    m = cfg.window_margin_s
    wins: dict[str, list[tuple[float, float]]] = {"sys": [], "dia": []}
    for c in valid:
        a, b = c.s1_end_s + m, c.s2_start_s - m  # type: ignore[operator]
        if b - a >= cfg.min_window_s:
            wins["sys"].append((a, b))
        a, b = c.s2_end_s + m, c.next_s1_start_s - m  # type: ignore[operator]
        if b - a >= cfg.min_window_s:
            wins["dia"].append((a, b))

    results: dict[str, MurmurWindow | None] = {"sys": None, "dia": None}
    p_win = {"sys": 0.0, "dia": 0.0}
    thr = {"sys": cfg.t_sys, "dia": cfg.t_dia}
    cycle_profiles: dict[str, np.ndarray] = {}
    for kind in ("sys", "dia"):
        ws = wins[kind]
        if len(ws) < 3:
            continue
        Rs, profs, segs_x = [], [], []
        for a, b in ws:
            i0, i1 = _idx(t0, fs, a, n), _idx(t0, fs, b, n) + 1
            seg_l = lw[i0:i1]
            if len(seg_l) < 3:
                continue
            # median (not mean): robust to S1/S2 tails leaking into the window edges
            Rs.append(float(np.median(seg_l) / floor))
            profs.append(np.interp(np.linspace(0, 1, 40), np.linspace(0, 1, len(seg_l)), seg_l))
            segs_x.append(pre_wide[int(a * sr) : int(b * sr)])
        if len(Rs) < 3:
            continue
        R_arr = np.array(Rs)
        R_med = float(np.median(R_arr))
        frac = float(np.mean(R_arr > thr[kind]))
        present = bool(R_med > thr[kind] and frac >= cfg.murmur_cycle_fraction)
        prof = np.mean(profs, axis=0)
        cycle_profiles[kind] = np.array(profs)
        shape, slope, r2 = _profile_shape(prof - floor)
        prof_R = prof / floor
        covered = prof_R > max(2.0, 0.3 * float(prof_R.max()))
        coverage = float(np.mean(covered))
        tgrid = np.linspace(0, 1, len(prof))
        pw = np.maximum(prof - floor, 0)
        tc = float(np.sum(tgrid * pw) / (np.sum(pw) + EPS)) if pw.sum() > 0 else 0.5
        timing = _timing_label(kind, coverage, tc) if present else "none"
        spec: dict[str, float] = {}
        if freq_valid and segs_x:
            spec = spectral_stats(np.concatenate(segs_x), sr)
        M = float(
            np.mean([np.median(lw[_idx(t0, fs, a, n) : _idx(t0, fs, b, n) + 1]) for a, b in ws]) / hs_mean
        )
        db = 10 * math.log10(M + 1e-12)
        if db > -3:
            grade, gconf = ">=4", 0.3
        elif db > -10:
            grade, gconf = "3", 0.4
        else:
            grade, gconf = "1-2", 0.4
        results[kind] = MurmurWindow(
            present, timing, R_med, frac, shape if present else "none", spec, grade, gconf, M, prof
        )
        p_win[kind] = (
            _sigmoid(2.2 * math.log(max(R_med, 1e-3) / thr[kind]))
            * min(1.0, frac / cfg.murmur_cycle_fraction) ** 0.5
        )
        feats[f"R_{kind}"] = R_med
        feats[f"M{kind}_ratio"] = M
        feats[f"env_slope_{kind}"] = slope
        if kind == "sys":
            feats["env_shape_r2_diamond"] = r2
        xs = np.concatenate(segs_x) if segs_x else np.array([0.0])
        feats[f"rms_{kind}"] = float(math.sqrt(np.mean(xs**2)))
        feats[f"zcr_{kind}"] = float(np.mean(np.abs(np.diff(np.sign(xs))) / 2)) if len(xs) > 2 else 0.0
        if kind == "sys":
            feats["kurtosis_sys"] = float(stats.kurtosis(xs))
            feats["skew_sys"] = float(stats.skew(xs))
            pe = np.maximum(prof, 1e-12)
            pe = pe / pe.sum()
            feats["shannon_entropy_sys"] = float(-np.sum(pe * np.log2(pe)))
        for kf, vf in spec.items():
            feats[f"{kf}_{kind}"] = vf

    # cycle-to-cycle repeatability (doc 8.4) on S1->next S1 envelope
    corr = _cycle_corr(lw, valid, t0, fs, n)
    if corr is not None:
        feats["cycle_corr"] = corr

    s, d = results["sys"], results["dia"]
    if s is None and d is None:
        return MurmurResult(False, None, None, None, None, notes=["Murmur oynalari juda qisqa"]), feats
    present = bool((s and s.present) or (d and d.present))
    prob = max(p_win["sys"], p_win["dia"])
    # repeatability / flatness soft modifiers (doc 6.4): non-repeating broad-band energy is likelier noise
    notes: list[str] = []
    if corr is not None and corr < 0.3 and present:
        prob *= 0.8
        notes.append("Sikllararo takrorlanuvchanlik past: shovqin/artefakt bo'lishi mumkin")
    return MurmurResult(
        True,
        present,
        float(np.clip(prob, 0, 1)),
        s,
        d,
        p_win["sys"],
        p_win["dia"],
        {"floor": floor, "hs_mean": hs_mean},
        notes,
    ), feats


def _cycle_corr(lw: np.ndarray, valid: list[Cycle], t0: float, fs: float, n: int) -> float | None:
    mats = []
    for c in valid:
        a, b = _idx(t0, fs, c.s1_start_s, n), _idx(t0, fs, c.next_s1_start_s, n)  # type: ignore[arg-type]
        if b - a < 8:
            continue
        mats.append(np.interp(np.linspace(0, 1, 100), np.linspace(0, 1, b - a), np.log(lw[a:b] + 1e-9)))
    if len(mats) < 3:
        return None
    C = np.corrcoef(np.array(mats))
    iu = np.triu_indices_from(C, k=1)
    v = C[iu]
    v = v[np.isfinite(v)]
    return float(np.mean(v)) if v.size else None


# --------------------------------------------------------------------------- extra sounds


def detect_extra_sounds(
    x: np.ndarray, x_wide: np.ndarray, sr: int, seg: Segmentation, freq_valid: bool = True
) -> list[dict[str, Any]]:
    """Heuristic S3/S4/split-S2/click detectors. LOW reliability by design (see limitations)."""
    valid = [c for c in seg.cycles if c.valid]
    base = [
        {"type": "s3", "present": False, "confidence": 0.0},
        {"type": "s4", "present": False, "confidence": 0.0},
        {"type": "s2_split_candidate", "present": False, "confidence": 0.0},
        {"type": "click", "present": False, "confidence": 0.0},
    ]
    if len(valid) < 3:
        return base
    sos = sig.butter(4, 60.0, btype="low", fs=sr, output="sos")
    low = sig.sosfiltfilt(sos, x)

    def en(sig_: np.ndarray, a: float, b: float) -> float:
        i0, i1 = max(int(a * sr), 0), min(int(b * sr), len(sig_))
        if i1 - i0 < 4:
            return 0.0
        return float(np.mean(sig_[i0:i1] ** 2))

    r3, r4, rc, split = [], [], [], 0
    hp = None
    if freq_valid:
        hp = sig.sosfiltfilt(sig.butter(4, 150.0, btype="high", fs=sr, output="sos"), x_wide)
    for c in valid:
        s1e = en(low, c.s1_start_s, c.s1_end_s) + 1e-12
        r3.append(en(low, c.s2_start_s + 0.12, c.s2_start_s + 0.18) / s1e)  # type: ignore[operator]
        r4.append(en(low, c.s1_start_s - 0.12, c.s1_start_s - 0.07) / s1e)
        if hp is not None:
            s2e = en(hp, c.s2_start_s, c.s2_end_s) + 1e-12  # type: ignore[arg-type]
            rc.append(en(hp, c.s2_start_s + 0.04, c.s2_start_s + 0.12) / s2e)  # type: ignore[operator]
        # S2 split: two Hilbert peaks 20-60 ms apart
        a, b = int((c.s2_start_s - 0.02) * sr), int((c.s2_end_s + 0.03) * sr)  # type: ignore[operator]
        if b - a > 20 and a >= 0 and b <= len(x):
            he = np.abs(sig.hilbert(x[a:b]))
            k = max(int(0.008 * sr), 3)
            he = np.convolve(he, np.ones(k) / k, mode="same")
            pk, _ = sig.find_peaks(he, prominence=0.3 * he.max(), distance=max(int(0.02 * sr), 1))
            if len(pk) >= 2 and 0.02 <= (pk[1] - pk[0]) / sr <= 0.06:
                split += 1

    def out(name: str, vals: list[float], thr: float) -> dict[str, Any]:
        if not vals:
            return {"type": name, "present": False, "confidence": 0.0}
        med = float(np.median(vals))
        frac = float(np.mean(np.array(vals) > thr))
        pres = med > thr and frac >= 0.6
        conf = float(np.clip(_sigmoid(2.0 * math.log(max(med, 1e-6) / thr)) * (0.5 + 0.5 * frac), 0, 1))
        return {"type": name, "present": bool(pres), "confidence": conf}

    res = [out("s3", r3, 0.25), out("s4", r4, 0.25)]
    sf = split / len(valid)
    res.append({"type": "s2_split_candidate", "present": sf >= 0.5, "confidence": float(sf)})
    res.append(out("click", rc, 0.5) if rc else {"type": "click", "present": False, "confidence": 0.0})
    return res


# --------------------------------------------------------------------------- feature vector


def build_features(
    rhythm: dict[str, Any],
    intervals: dict[str, Any],
    seg: Segmentation,
    murmur_feats: dict[str, float],
    pre_x_wide: np.ndarray,
    sr: int,
    quality: dict[str, float],
    freq_valid: bool,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    f: dict[str, float | None] = {}
    f["hr_bpm"] = rhythm.get("hr_bpm")
    f["cycle_cv"] = rhythm.get("cycle_cv")
    for k in (
        "systole_ms",
        "diastole_ms",
        "sd_ratio",
        "sys_frac",
        "systole_corr_ms",
        "s1_dur_ms",
        "s2_dur_ms",
    ):
        f[k] = intervals.get(k)
    valid = [c for c in seg.cycles if c.valid]
    if valid:
        s1a = float(np.median([c.s1_amp for c in valid]))
        s2a = float(np.median([c.s2_amp for c in valid]))
        f["s1_amp"], f["s2_amp"] = s1a, s2a
        f["s1_s2_amp_ratio"] = s1a / s2a if abs(s2a) > 1e-9 else None
    f.update(murmur_feats)
    f.update(quality)
    f["valid_cycle_ratio"] = seg.n_valid / max(seg.n_detected - 1, 1)
    missing = [
        "sample_entropy_sys",
        "scalogram_peak_freq_sys",
        "scalogram_energy_entropy",
        "spectral_contrast",
        "cycle_dtw",
    ]
    if freq_valid:
        for k, v in mfcc_stats(pre_x_wide, sr).items():
            f[k] = v
    else:
        missing.append("mfcc_*")
    for k in ("R_sys", "R_dia", "f_peak_sys", "f_centroid_sys"):
        if f.get(k) is None:
            missing.append(k)
    flags = {"missing": missing, "frequency_features_valid": bool(freq_valid)}
    return f, flags

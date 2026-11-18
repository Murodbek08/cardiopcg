"""S1/S2 segmentation from the Shannon envelope (doc 02, section 5, rule based)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from .config import DEFAULT_CONFIG, SEGMENTATION_METHOD, MLConfig
from .envelope import Envelope, autocorr_period


@dataclass
class Cycle:
    idx: int
    s1_start_s: float
    s1_end_s: float
    s2_start_s: float | None
    s2_end_s: float | None
    next_s1_start_s: float | None
    s1_peak_s: float
    s2_peak_s: float | None
    s1_amp: float = 0.0
    s2_amp: float = 0.0
    valid: bool = True

    @property
    def complete(self) -> bool:
        return self.s2_start_s is not None and self.next_s1_start_s is not None


@dataclass
class Segmentation:
    method: str
    cycles: list[Cycle]
    period_s: float | None
    r1: float
    confidence: float
    n_detected: int
    n_valid: int
    cycle_durations: list[float] = field(default_factory=list)
    rhythm_irregular: bool = False
    cycle_cv: float | None = None
    warnings: list[str] = field(default_factory=list)


def _bounds(
    e: np.ndarray, pk: int, fs: float, rel_height: float = 0.7, max_s: float = 0.16
) -> tuple[int, int]:
    """Peak extent at `rel_height` of its prominence (robust to a raised murmur plateau)."""
    try:
        _, _, left, right = sig.peak_widths(e, [pk], rel_height=rel_height)
        lo, hi = int(np.floor(left[0])), int(np.ceil(right[0]))
    except Exception:  # noqa: BLE001
        lo, hi = pk, pk
    m = int(max_s * fs)
    return max(lo, pk - m), min(hi, pk + m)


def find_candidate_peaks(env: Envelope, cfg: MLConfig = DEFAULT_CONFIG) -> np.ndarray:
    z = env.env
    fs = env.fs
    peaks, props = sig.find_peaks(z, height=0.3, distance=max(int(0.10 * fs), 1), prominence=0.3)
    if peaks.size == 0:
        return peaks
    widths = sig.peak_widths(z, peaks, rel_height=0.5)[0] / fs
    keep = (widths >= 0.015) & (widths <= 0.25)
    peaks = peaks[keep]
    # drop very weak peaks relative to the median strong one (spurious noise bumps)
    if peaks.size >= 4:
        h = z[peaks]
        peaks = peaks[h >= 0.25 * np.median(h)]
    return peaks


def _track(peaks: np.ndarray, times: np.ndarray, heights: np.ndarray, start: int, T: float, tol: float):
    """Walk the peak list assigning S1, S2, next-S1; returns list of (i_s1, i_s2|None) and next-S1 chain."""
    chain: list[tuple[int, int | None]] = []
    i = start
    n = len(peaks)
    while True:
        t1 = times[i]
        # S2: highest peak in (t1+0.10, t1+0.58T)
        mask = (times > t1 + 0.10) & (times < t1 + 0.58 * T)
        idxs = np.where(mask)[0]
        i2 = int(idxs[np.argmax(heights[idxs])]) if idxs.size else None
        ref_t = times[i2] if i2 is not None else t1 + 0.4 * T
        # next S1 around t1 + T (+-tol*T window), after S2
        lo = max(ref_t + 0.08, t1 + (1 - tol) * T)
        hi = t1 + (1 + tol) * T
        mask = (times > lo) & (times < hi)
        idxs = np.where(mask)[0]
        if idxs.size:
            # prefer closeness to expected position, then height
            score = heights[idxs] / (1.0 + 3.0 * np.abs(times[idxs] - (t1 + T)) / T)
            nxt = int(idxs[np.argmax(score)])
        else:
            nxt = None
        chain.append((i, i2))
        if nxt is None or nxt <= i:
            break
        i = nxt
        if i >= n:
            break
    return chain


def segment(env: Envelope, cfg: MLConfig = DEFAULT_CONFIG, hr_hint_bpm: float | None = None) -> Segmentation:
    fs = env.fs
    z = env.env
    warnings: list[str] = []
    period, r1 = autocorr_period(z, fs, 60.0 / cfg.max_hr_bpm, 60.0 / cfg.min_hr_bpm)
    hperiod, _ = autocorr_period(env.hilbert, fs, 60.0 / cfg.max_hr_bpm, 60.0 / cfg.min_hr_bpm)
    peaks = find_candidate_peaks(env, cfg)
    empty = Segmentation(SEGMENTATION_METHOD, [], period, r1, 0.0, 0, 0)
    if peaks.size < 3:
        empty.warnings.append("too_few_peaks")
        return empty
    times = env.t[peaks]
    heights = z[peaks]
    if period is None:
        gaps = np.diff(times)
        period = float(np.median(gaps) * 2.0)
        warnings.append("period_from_peak_gaps")
    agree = 1.0
    if hperiod is not None and period is not None and abs(hperiod - period) / period > 0.10:
        agree = 0.6
        warnings.append("envelope_methods_disagree")

    T = float(period)
    best = None
    for start in range(min(4, len(peaks))):
        chain = _track(peaks, times, heights, start, T, 0.40)
        complete = sum(1 for _, i2 in chain if i2 is not None)
        sys_d = [times[i2] - times[i1] for i1, i2 in chain if i2 is not None]
        dia_d = [
            times[chain[k + 1][0]] - times[chain[k][1]]
            for k in range(len(chain) - 1)
            if chain[k][1] is not None
        ]
        bonus = 0.5 if (sys_d and dia_d and np.median(sys_d) < np.median(dia_d)) else 0.0
        sc = complete + bonus - 0.01 * start
        if best is None or sc > best[0]:
            best = (sc, chain)
    assert best is not None
    chain = best[1]

    tt = env.t
    base = float(np.percentile(z, 10))
    e = z - base
    cycles: list[Cycle] = []
    for k, (i1, i2) in enumerate(chain):
        p1 = int(peaks[i1])
        a1, b1 = _bounds(e, p1, fs)
        if i2 is not None:
            p2 = int(peaks[i2])
            a2, b2 = _bounds(e, p2, fs)
            s2s, s2e, s2p, s2a = float(tt[a2]), float(tt[b2]), float(tt[p2]), float(z[p2])
        else:
            s2s = s2e = s2p = None
            s2a = 0.0
        nxt = None
        if k + 1 < len(chain):
            pn = int(peaks[chain[k + 1][0]])
            an, _ = _bounds(e, pn, fs)
            nxt = float(tt[an])
        cycles.append(
            Cycle(
                idx=k,
                s1_start_s=float(tt[a1]),
                s1_end_s=float(tt[b1]),
                s2_start_s=s2s,
                s2_end_s=s2e,
                next_s1_start_s=nxt,
                s1_peak_s=float(tt[p1]),
                s2_peak_s=s2p,
                s1_amp=float(z[p1]),
                s2_amp=s2a,
            )
        )

    # ---- cycle validation (doc 5.5) ----
    durs = np.array(
        [c2.s1_start_s - c1.s1_start_s for c1, c2 in zip(cycles[:-1], cycles[1:], strict=False)], dtype=float
    )
    cv = float(np.std(durs) / np.mean(durs)) if durs.size >= 3 and np.mean(durs) > 0 else None
    irregular = bool(cv is not None and cv > cfg.irregular_cv)
    med_T = float(np.median(durs)) if durs.size else T
    tol = 0.5 if irregular else cfg.cycle_tolerance
    s1lo, s1hi = cfg.s1_dur_range_ms
    s2lo, s2hi = cfg.s2_dur_range_ms
    for c in cycles:
        ok = c.complete
        if ok:
            d1 = (c.s1_end_s - c.s1_start_s) * 1000
            d2 = ((c.s2_end_s or 0) - (c.s2_start_s or 0)) * 1000
            Tc = c.next_s1_start_s - c.s1_start_s  # type: ignore[operator]
            ok = s1lo <= d1 <= s1hi and s2lo <= d2 <= s2hi and abs(Tc - med_T) <= tol * med_T
            ok = ok and (c.s2_start_s - c.s1_start_s) > 0.05  # type: ignore[operator]
        c.valid = bool(ok)
    n_valid = sum(1 for c in cycles if c.valid)
    valid_ratio = n_valid / max(len(cycles) - 1, 1)
    conf = float(np.clip(0.5 * min(valid_ratio, 1.0) + 0.3 * np.clip(r1 / 0.6, 0, 1) + 0.2 * agree, 0, 1))
    if irregular:
        warnings.append("rhythm_irregular")
    return Segmentation(
        method=SEGMENTATION_METHOD,
        cycles=cycles,
        period_s=T,
        r1=float(r1),
        confidence=conf,
        n_detected=len(cycles),
        n_valid=n_valid,
        cycle_durations=[float(d) for d in durs],
        rhythm_irregular=irregular,
        cycle_cv=cv,
        warnings=warnings,
    )

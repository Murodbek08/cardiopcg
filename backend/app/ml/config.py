"""Tunable constants for the PCG pipeline (doc 02, sections 3-8).

All thresholds are *initial, uncalibrated* values taken from the spec. They must be
re-calibrated on CirCor / CinC 2016 / own clinical data before any clinical claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PREPROCESS_VERSION = "pp-1.0"
SEGMENTATION_METHOD = "shannon_envelope_rules_v1"
MURMUR_RULE_VERSION = "murmur_rule_v1"
SCHEMA_VERSION = "pcg-analysis/1.0"


@dataclass(frozen=True)
class MLConfig:
    # --- audio validation (doc 2) ---
    max_bytes: int = 25 * 1024 * 1024
    min_duration_s: float = 5.0
    max_duration_s: float = 120.0
    window_s: float = 30.0
    min_sample_rate: int = 2000
    image_max_bytes: int = 15 * 1024 * 1024
    image_min_width_px: int = 800

    # --- preprocessing (doc 3) ---
    target_sr: int = 4000
    bp_low: float = 25.0
    bp_high: float = 400.0
    bp_order: int = 4
    wide_low: float = 20.0
    wide_high: float = 800.0
    baseline_hp: float = 20.0
    notch_hz: float = 50.0
    notch_q: float = 30.0
    denoise: bool = True
    despike: bool = True

    # --- envelope (doc 4) ---
    env_win_s: float = 0.020
    env_hop_s: float = 0.010
    env_smooth_s: float = 0.040

    # --- segmentation (doc 5) ---
    min_hr_bpm: float = 35.0
    max_hr_bpm: float = 190.0
    s1_dur_range_ms: tuple[float, float] = (40.0, 200.0)
    s2_dur_range_ms: tuple[float, float] = (30.0, 150.0)
    cycle_tolerance: float = 0.30
    irregular_cv: float = 0.15

    # --- SQI (doc 3.5) ---
    sqi_good: float = 0.70
    sqi_acceptable: float = 0.50
    sqi_poor: float = 0.30
    sqi_weights: tuple[float, ...] = (0.30, 0.25, 0.15, 0.15, 0.075, 0.075)

    # --- murmur (doc 6.4) ---
    t_sys: float = 3.0
    t_dia: float = 2.0
    murmur_cycle_fraction: float = 0.6
    window_margin_s: float = 0.020
    min_window_s: float = 0.030

    # --- ensemble (doc 9.3) ---
    w_rule: float = 0.4
    w_gbm: float = 0.6
    disagreement_threshold: float = 0.4
    abnormal_threshold: float = 0.5

    # --- artefacts ---
    make_png: bool = True
    make_scalogram: bool = True


DEFAULT_CONFIG = MLConfig()

# doc 6.1: heart-rate reference ranges by age (years) -> (low, high) bpm
HR_RANGES: list[tuple[float, tuple[float, float]]] = [
    (1.0, (100.0, 160.0)),
    (3.0, (90.0, 150.0)),
    (6.0, (80.0, 120.0)),
    (12.0, (70.0, 110.0)),
    (1000.0, (60.0, 100.0)),
]


def hr_range_for_age(age_years: float | None) -> tuple[float, float]:
    if age_years is None:
        return (60.0, 100.0)
    for upper, rng in HR_RANGES:
        if age_years < upper:
            return rng
    return (60.0, 100.0)


@dataclass
class Limitations:
    items: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        if text not in self.items:
            self.items.append(text)

"""Rule-based classifier + pluggable ML slot + ensemble (doc 02, sections 6.5, 9.3, 9.6).

The ML slot is OPTIONAL. With no model directory / registry / valid sha256 the classifier runs
rule-only and reports `ml_available=false`. No model weights ship with this repo.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

from .config import DEFAULT_CONFIG, MLConfig
from .features import MurmurResult
from .schemas import (
    Classification,
    DiastolicMurmur,
    LocationHint,
    MlModelRef,
    Murmur,
    PerModel,
    SystolicMurmur,
)

# --------------------------------------------------------------------------- ML slot


@runtime_checkable
class ProbModel(Protocol):
    name: str
    version: str
    sha256: str | None

    def predict(self, features: dict[str, float | None]) -> float | None:  # P(abnormal)
        ...


class OnnxFeatureModel:
    """Feature-vector ONNX classifier (e.g. GBM exported with skl2onnx/onnxmltools)."""

    def __init__(
        self,
        name: str,
        version: str,
        path: Path,
        sha256: str,
        feature_names: list[str],
        impute: dict[str, float] | None = None,
        temperature: float = 1.0,
        positive_index: int = 1,
    ):
        import onnxruntime as ort  # lazy: optional dependency at runtime

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        self.name, self.version, self.sha256 = name, version, sha256
        self.feature_names = feature_names
        self.impute = impute or {}
        self.temperature = temperature
        self.positive_index = positive_index
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, features: dict[str, float | None]) -> float | None:
        vec = []
        for k in self.feature_names:
            v = features.get(k)
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                v = self.impute.get(k, 0.0)
            vec.append(float(v))
        out = self.session.run(None, {self.input_name: np.asarray([vec], dtype=np.float32)})
        prob = _extract_prob(out, self.positive_index)
        if prob is None:
            return None
        if self.temperature and self.temperature != 1.0:  # temperature scaling (doc 9.5)
            p = min(max(prob, 1e-6), 1 - 1e-6)
            prob = 1 / (1 + math.exp(-math.log(p / (1 - p)) / self.temperature))
        return float(prob)


def _extract_prob(outputs: list[Any], pos: int) -> float | None:
    for o in outputs[::-1]:
        if isinstance(o, list) and o and isinstance(o[0], dict):  # zipmap
            d = o[0]
            return float(d.get(pos, d.get(str(pos), list(d.values())[-1])))
        arr = np.asarray(o)
        if arr.dtype.kind == "f":
            if arr.ndim == 2 and arr.shape[1] > pos:
                return float(arr[0, pos])
            if arr.size == 1:
                return float(arr.reshape(-1)[0])
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ModelRegistry:
    models: list[ProbModel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, model_dir: str | Path | None = None) -> ModelRegistry:
        """Load models/registry.json. Only models whose sha256 matches are loaded (doc 9.6)."""
        reg = cls()
        d = Path(model_dir or os.environ.get("CARDIOPCG_MODEL_DIR", "") or "models")
        rpath = d / "registry.json"
        if not rpath.is_file():
            return reg
        try:
            spec = json.loads(rpath.read_text(encoding="utf8"))
        except Exception as exc:  # noqa: BLE001
            reg.warnings.append(f"registry.json o'qilmadi: {exc}")
            return reg
        for m in spec.get("models", []):
            try:
                f = d / m["file"]
                if not f.is_file():
                    reg.warnings.append(f"model fayli yo'q: {m['file']}")
                    continue
                digest = _sha256_file(f)
                if digest != m.get("sha256"):
                    reg.warnings.append(f"sha256 mos kelmadi: {m.get('name')} (model yuklanmadi)")
                    continue
                if m.get("kind", "onnx") != "onnx":
                    reg.warnings.append(f"noma'lum model turi: {m.get('kind')}")
                    continue
                cal = m.get("calibrator") or {}
                reg.models.append(
                    OnnxFeatureModel(
                        m["name"],
                        str(m["version"]),
                        f,
                        digest,
                        list(m["feature_names"]),
                        impute=m.get("impute"),
                        temperature=float(cal.get("T", 1.0)),
                        positive_index=int(m.get("positive_index", 1)),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - never fail the pipeline on a broken model
                reg.warnings.append(f"model yuklanmadi ({m.get('name')}): {exc}")
        return reg


# --------------------------------------------------------------------------- location hints


def location_hints(site: str | None, murmur: Murmur, p_murmur: float) -> list[LocationHint]:
    if not murmur.present or site is None:
        return []
    out: list[LocationHint] = []
    s, d = murmur.systolic, murmur.diastolic

    def add(hyp: str, ev: list[str]) -> None:
        sup = float(np.clip((0.3 + 0.1 * len(ev)) * (0.5 + 0.5 * p_murmur), 0, 0.8))
        out.append(LocationHint(site=site, hypothesis=hyp, support=round(sup, 2), evidence=ev))

    if s and s.present:
        hf = s.frequency_class == "high"
        if (
            site in ("aortic", "pulmonic")
            and s.timing in ("mid_sys", "early_sys", "late_sys")
            and s.shape == "crescendo_decrescendo"
        ):
            add(
                "aortic_stenosis_pattern" if site == "aortic" else "pulmonic_stenosis_pattern",
                [s.timing, s.shape, f"recorded_at_{site}"],
            )
        elif site in ("aortic", "pulmonic") and s.timing in ("mid_sys", "early_sys"):
            add("flow_murmur_or_outflow_obstruction_pattern", [s.timing, f"recorded_at_{site}"])
        if site in ("mitral", "apex") and s.timing == "holosystolic":
            ev = (
                ["holosystolic", f"recorded_at_{site}"]
                + (["plateau"] if s.shape == "plateau" else [])
                + (["high_freq"] if hf else [])
            )
            add("mitral_regurgitation_pattern", ev)
        if site == "tricuspid" and s.timing == "holosystolic":
            add("tricuspid_regurgitation_pattern", ["holosystolic", "recorded_at_tricuspid"])
        if site == "erb" and s.timing == "holosystolic":
            add(
                "ventricular_septal_defect_pattern",
                ["holosystolic", "recorded_at_erb"] + (["high_freq"] if hf else []),
            )
    if d and d.present:
        if (
            site in ("apex", "mitral")
            and d.timing in ("mid_dia", "late_dia", "holodiastolic")
            and d.frequency_class in ("low", "medium")
        ):
            add(
                "mitral_stenosis_pattern",
                [d.timing, f"recorded_at_{site}"] + (["low_freq"] if d.frequency_class == "low" else []),
            )
        if (
            site in ("aortic", "erb")
            and d.timing in ("early_dia", "holodiastolic")
            and d.shape in ("decrescendo", "plateau")
        ):
            add("aortic_regurgitation_pattern", [d.timing, d.shape, f"recorded_at_{site}"])
    return out


def murmur_to_schema(mr: MurmurResult, site: str | None, freq_valid: bool) -> Murmur:
    if not mr.assessable or mr.present is None:
        return Murmur(present=None, probability=None, calibrated=False)

    def hz(v: float | None) -> float | None:
        return round(v, 1) if (v is not None and freq_valid) else None

    sy = di = None
    if mr.systolic is not None:
        w = mr.systolic
        sy = SystolicMurmur(
            present=w.present,
            timing=w.timing if w.present else "none",  # type: ignore[arg-type]
            grade_est=w.grade_est if w.present else None,  # type: ignore[arg-type]
            grade_confidence=w.grade_confidence if w.present else None,
            shape=w.shape if w.present else "none",  # type: ignore[arg-type]
            frequency_class=(_fc(w.spectral) if (w.present and freq_valid) else None),
            f_peak_hz=hz(w.spectral.get("f_peak")),
            f_centroid_hz=hz(w.spectral.get("f_centroid")),
            R_sys=round(w.R_med, 2),
        )
    if mr.diastolic is not None:
        w = mr.diastolic
        di = DiastolicMurmur(
            present=w.present,
            timing=w.timing if w.present else "none",  # type: ignore[arg-type]
            grade_est=w.grade_est if w.present else None,  # type: ignore[arg-type]
            shape=w.shape if w.present else "none",  # type: ignore[arg-type]
            frequency_class=(_fc(w.spectral) if (w.present and freq_valid) else None),
            f_peak_hz=hz(w.spectral.get("f_peak")),
            f_centroid_hz=hz(w.spectral.get("f_centroid")),
            R_dia=round(w.R_med, 2),
        )
    m = Murmur(
        present=mr.present,
        probability=round(float(mr.probability or 0.0), 3),
        calibrated=False,
        systolic=sy,
        diastolic=di,
    )
    m.location_hints = location_hints(site, m, float(mr.probability or 0.0))
    return m


def _fc(spec: dict[str, float]) -> str | None:
    c = spec.get("f_centroid")
    if c is None:
        return None
    return "low" if c < 100 else ("medium" if c <= 300 else "high")


# --------------------------------------------------------------------------- ensemble


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def rule_probability(mr: MurmurResult, rhythm: dict[str, Any], extras: list[dict[str, Any]]) -> float:
    parts = [float(mr.probability or 0.0) if mr.assessable else 0.0]
    if rhythm.get("rhythm_irregular"):
        parts.append(0.35)
    for e in extras:
        if e["type"] == "s3" and e["present"]:
            parts.append(0.4 * e["confidence"])
    keep = 1.0
    for p in parts:
        keep *= 1.0 - p
    return float(np.clip(1.0 - keep, 0.0, 1.0))


def classify(
    mr: MurmurResult,
    rhythm: dict[str, Any],
    extras: list[dict[str, Any]],
    features: dict[str, float | None],
    sqi: float,
    sqi_level: str,
    seg_conf: float,
    registry: ModelRegistry | None,
    allow_ml: bool = True,
    cfg: MLConfig = DEFAULT_CONFIG,
) -> tuple[Classification, list[MlModelRef], bool, list[str]]:
    notes: list[str] = []
    p_rule = rule_probability(mr, rhythm, extras)
    per: dict[str, float | None] = {"rule": p_rule, "gbm": None, "cnn": None}
    refs: list[MlModelRef] = []
    ml_used = False
    if allow_ml and registry is not None:
        for m in registry.models:
            try:
                p = m.predict(features)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"ML model xatosi ({m.name}): {type(exc).__name__}")
                continue
            if p is None:
                continue
            key = "cnn" if "cnn" in m.name.lower() else "gbm"
            per[key] = float(p)
            refs.append(MlModelRef(name=m.name, version=m.version, sha256=m.sha256))
            ml_used = True
    weights = {"rule": cfg.w_rule if per["gbm"] is not None else 1.0, "gbm": cfg.w_gbm, "cnn": 0.5}
    if per["cnn"] is not None:
        weights = {"rule": 0.2, "gbm": 0.3 if per["gbm"] is not None else 0.0, "cnn": 0.5}
    avail = {k: v for k, v in per.items() if v is not None and weights.get(k, 0) > 0}
    wsum = sum(weights[k] for k in avail)
    z = sum(weights[k] / wsum * _logit(v) for k, v in avail.items())
    p_final = 1.0 / (1.0 + math.exp(-z))
    vals = [v for v in per.values() if v is not None]
    disagree = bool(len(vals) > 1 and (max(vals) - min(vals)) > cfg.disagreement_threshold)

    unc = float(np.std(vals)) if len(vals) > 1 else 0.10 + 0.30 * (1.0 - sqi) + 0.15 * (1.0 - seg_conf)
    unc += 0.15 * (1.0 - abs(2 * p_final - 1.0))
    if disagree:
        unc += 0.15
    if sqi_level == "acceptable":
        unc /= 0.85  # doc 3.5: confidence x0.85 at "acceptable" quality
    unc = float(np.clip(unc, 0.0, 1.0))
    outcome = "undetermined" if unc > 0.5 else ("abnormal" if p_final >= cfg.abnormal_threshold else "normal")
    cl = Classification(
        outcome=outcome,  # type: ignore[arg-type]
        probability_abnormal=round(p_final, 3),
        uncertainty=round(unc, 3),
        ood_score=None,  # needs training-set statistics (Mahalanobis); not available without a trained model
        per_model=PerModel(
            rule=round(p_rule, 3),
            gbm=None if per["gbm"] is None else round(per["gbm"], 3),
            cnn=None if per["cnn"] is None else round(per["cnn"], 3),
        ),
        models_disagree=disagree,
    )
    return cl, refs, ml_used, notes

"""Deterministic local drug-safety layer (allergy / interaction / contraindication / dose checks).

Every drug proposed by the AI (or added manually) goes through this layer; LLM output is never trusted
on its own. Reference data: ``app/data/drug_interactions.json`` (v1, cardio-focused, requires clinical review).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent.parent / "data" / "drug_interactions.json"


@lru_cache
def _ref() -> dict[str, Any]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


@dataclass
class Item:
    key: str  # stable id (str(uuid))
    drug_name: str
    inn_code: str | None = None
    atc_code: str | None = None
    dose: str | None = None
    frequency: str | None = None

    @property
    def names(self) -> set[str]:
        return {n for n in (norm(self.inn_code), norm(self.drug_name)) if n}

    @property
    def atc(self) -> str:
        if self.atc_code:
            return self.atc_code.upper()
        for n in self.names:
            code = _ref()["atc_by_name"].get(n)
            if code:
                return code
        return ""


@dataclass
class SafetyResult:
    allergy_conflicts: list[dict[str, Any]] = field(default_factory=list)
    interactions: list[dict[str, Any]] = field(default_factory=list)
    contraindications: list[dict[str, Any]] = field(default_factory=list)
    dose_warnings: list[dict[str, Any]] = field(default_factory=list)


def _groups_of(names: set[str]) -> set[str]:
    out = set()
    for g, members in _ref()["groups"].items():
        if names & set(members):
            out.add(g)
    return out


def _tokens(item_names: set[str]) -> set[str]:
    return item_names | _groups_of(item_names)


def _allergen_classes(substance: str, code: str | None) -> list[str]:
    s, c = norm(substance), (code or "").upper()
    res = []
    for cls, spec in _ref()["allergy_classes"].items():
        if any(n in s or s in n for n in spec["names"] if s) or (
            c and any(c.startswith(a) for a in spec["atc"])
        ):
            res.append(cls)
    return res


def check_allergies(item: Item, allergies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    ref = _ref()["allergy_classes"]
    atc = item.atc
    for a in allergies:
        substance, code = a.get("substance", ""), a.get("substance_code")
        s, c = norm(substance), (code or "").upper()
        direct = bool(
            (s and s in item.names)
            or (c and (c == atc or (atc and atc.startswith(c)) or norm(code) in item.names))
        )
        cross = False
        if not direct:
            for cls in _allergen_classes(substance, code):
                spec = ref[cls]
                if item.names & set(spec["names"]) or (atc and any(atc.startswith(p) for p in spec["atc"])):
                    direct = True
                elif atc and any(atc.startswith(p) for p in spec["cross"]):
                    cross = True
        if direct or cross:
            conflicts.append(
                {
                    "item_id": item.key,
                    "drug": item.drug_name,
                    "allergen": substance,
                    "severity": a.get("severity"),
                    "cross_reactive": cross and not direct,
                }
            )
    return conflicts


def _pair_match(rule_a: str, rule_b: str, toks_x: set[str], toks_y: set[str]) -> bool:
    return (rule_a in toks_x and rule_b in toks_y) or (rule_a in toks_y and rule_b in toks_x)


def check_interactions(items: list[Item], current_meds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    seen: set[tuple[str, str, str]] = set()
    pool: list[tuple[str, set[str], bool]] = [(i.drug_name, _tokens(i.names), False) for i in items]
    pool += [
        (m.get("drug_name", ""), _tokens({norm(m.get("inn_code")), norm(m.get("drug_name"))} - {""}), True)
        for m in current_meds
    ]
    for ix in range(len(pool)):
        for iy in range(ix + 1, len(pool)):
            (na, ta, ca), (nb, tb, cb) = pool[ix], pool[iy]
            if ca and cb:
                continue  # current-vs-current is not our concern
            for rule in _ref()["interactions"]:
                if _pair_match(rule["a"], rule["b"], ta, tb):
                    key = (min(na, nb), max(na, nb), rule["level"])
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(
                        {
                            "items": [na, nb],
                            "level": rule["level"],
                            "note": rule["note"],
                            "with_current_med": ca or cb,
                        }
                    )
    return found


def check_contraindications(item: Item, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    toks = _tokens(item.names)
    out = []
    for rule in _ref()["contraindications"]:
        if not (toks & set(rule["groups"])):
            continue
        for h in history:
            if not h.get("is_active", True):
                continue
            code = (h.get("icd10_code") or "").upper()
            text = norm(f"{h.get('title', '')} {h.get('description', '')}")
            if any(code.startswith(p) for p in rule["icd10"] if code) or any(
                k in text for k in rule["keywords"]
            ):
                out.append(
                    {
                        "item_id": item.key,
                        "drug": item.drug_name,
                        "condition": h.get("title"),
                        "note": rule["note"],
                    }
                )
                break
    return out


_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")


def _times_per_day(freq: str | None) -> float | None:
    f = norm(freq)
    if not f:
        return None
    if any(k in f for k in ("qd", "once", "1 marta", "kuniga 1", "1x", "ertalab", "daily")) and not re.search(
        r"\b[2-9]\b", f
    ):
        return 1
    m = re.search(r"(\d+)\s*(?:marta|x|times|r/d|раз)", f) or re.search(
        r"(?:kuniga|daily|per day)\s*(\d+)", f
    )
    if m:
        return float(m.group(1))
    if "bid" in f:
        return 2
    if "tid" in f:
        return 3
    if "qid" in f:
        return 4
    return None


def check_dose(item: Item) -> list[dict[str, Any]]:
    limits = _ref()["max_daily_mg"]
    limit = next((limits[n] for n in item.names if n in limits), None)
    if limit is None or not item.dose:
        return []
    m = _NUM.search(item.dose)
    if not m:
        return []
    amount = float(m.group(1).replace(",", "."))
    d = norm(item.dose)
    if "mcg" in d or "µg" in d or "мкг" in d:
        amount /= 1000
    elif "g" in d.replace("mg", "") and "mg" not in d:
        amount *= 1000
    times = _times_per_day(item.frequency) or 1
    daily = amount * times
    if daily > limit:
        return [
            {
                "item_id": item.key,
                "drug": item.drug_name,
                "daily_mg": round(daily, 3),
                "max_daily_mg": limit,
                "note": "Sutkalik doza maksimal chegaradan oshgan",
            }
        ]
    return []


def run_checks(
    items: list[Item],
    allergies: list[dict[str, Any]],
    current_meds: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> SafetyResult:
    res = SafetyResult()
    for it in items:
        res.allergy_conflicts += check_allergies(it, allergies)
        res.contraindications += check_contraindications(it, history)
        res.dose_warnings += check_dose(it)
    res.interactions = check_interactions(items, current_meds)
    return res

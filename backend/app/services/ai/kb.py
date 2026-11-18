"""Local drug knowledge base: YAML loader + typed models (doc 02 section 15.2/15.4).

The KB is the single source of truth for drugs, doses, contraindications, allergies and
interactions. The LLM can only *choose among* KB candidates; it never adds drugs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _KB(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Indication(_KB):
    condition_code: str
    min_condition_prob: float = 0.30
    evidence_level: Literal["guideline", "expert", "limited"] = "limited"
    context_uz: str | None = None
    requires_flags_any: list[str] = Field(default_factory=list)
    dose_context: str | None = None


class RenalAdjust(_KB):
    egfr_lt: float
    action: Literal["reduce", "avoid", "may_need_higher_dose", "note"] = "note"
    factor: float | None = None
    note_uz: str | None = None


class Dose(_KB):
    population: Literal["adult", "elderly", "pediatric"] = "adult"
    indication_context: str | None = None
    route: Literal["po", "iv", "im", "sc"] = "po"
    dose_min: float | None = None
    dose_max: float | None = None
    unit: str
    frequency: str
    max_daily: float | None = None
    titration_uz: str | None = None
    weight_based: bool = False
    per_kg_min: float | None = None
    per_kg_max: float | None = None
    renal_adjust: list[RenalAdjust] = Field(default_factory=list)
    hepatic_adjust: list[dict[str, Any]] = Field(default_factory=list)


class Contraindication(_KB):
    kind: Literal["absolute", "relative"]
    code: str
    condition_expr: dict[str, Any] | None = None
    note_uz: str | None = None


class AllergyGroup(_KB):
    allergy_group: str
    cross_reactive_with: list[str] = Field(default_factory=list)
    strength: Literal["absolute", "relative"] = "absolute"


class Monitoring(_KB):
    parameter: str
    schedule_uz: str | None = None
    note_uz: str | None = None


class AdverseEffect(_KB):
    effect_uz: str
    frequency: str | None = None
    severity: str | None = None


class Drug(_KB):
    drug_id: str
    inn_en: str
    inn_uz: str | None = None
    aliases: list[str] = Field(default_factory=list)
    atc_code: str | None = None
    class_group: str
    drug_class: str
    interaction_classes: list[str] = Field(default_factory=list)
    forms: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = False
    kb_status: Literal["draft", "reviewed", "retired"] = "draft"
    sources: list[dict[str, Any]] = Field(default_factory=list)
    indications: list[Indication] = Field(default_factory=list)
    doses: list[Dose] = Field(default_factory=list)
    contraindications: list[Contraindication] = Field(default_factory=list)
    allergy_groups: list[AllergyGroup] = Field(default_factory=list)
    monitoring: list[Monitoring] = Field(default_factory=list)
    adverse_effects: list[AdverseEffect] = Field(default_factory=list)

    @property
    def tokens(self) -> set[str]:
        """Names usable in interaction rows: the drug id and its `class:` tokens."""
        return {self.drug_id, *(f"class:{c}" for c in self.interaction_classes)}


class Interaction(_KB):
    drug_a: str
    drug_b_or_class: str
    severity: Literal["minor", "moderate", "major", "contraindicated"]
    mechanism_uz: str | None = None
    effect_uz: str | None = None
    management_uz: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


def norm(s: str) -> str:
    s = s.strip().lower().replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", s)


class DrugKB:
    def __init__(
        self,
        drugs: list[Drug],
        interactions: list[Interaction],
        aliases: dict[str, Any],
        version: int,
        path: Path | None = None,
    ):
        self.drugs: dict[str, Drug] = {d.drug_id: d for d in drugs}
        self.interactions = interactions
        self.allergy_aliases: dict[str, str] = {
            norm(k): v for k, v in (aliases.get("allergy_aliases") or {}).items()
        }
        self.medication_classes: dict[str, list[str]] = {
            norm(k): list(v) for k, v in (aliases.get("medication_classes") or {}).items()
        }
        self.condition_aliases: dict[str, str] = {
            norm(k): v for k, v in (aliases.get("condition_aliases") or {}).items()
        }
        self.version = version
        self.path = path
        self._name_index: dict[str, str] = {}
        for d in drugs:
            for n in (d.drug_id, d.inn_en, d.inn_uz or "", *d.aliases):
                if n:
                    self._name_index[norm(n)] = d.drug_id
                    self._name_index[norm(n.split(" ")[0])] = self._name_index.get(
                        norm(n.split(" ")[0]), d.drug_id
                    )

    # ---- loading
    @classmethod
    def load(cls, directory: str | Path) -> DrugKB:
        d = Path(directory)
        meta = (
            yaml.safe_load((d / "_meta.yaml").read_text(encoding="utf8"))
            if (d / "_meta.yaml").is_file()
            else {}
        )
        version = int((meta or {}).get("kb_version", 1))
        aliases = (
            yaml.safe_load((d / "_aliases.yaml").read_text(encoding="utf8"))
            if (d / "_aliases.yaml").is_file()
            else {}
        )
        inter: list[Interaction] = []
        if (d / "_interactions.yaml").is_file():
            raw = yaml.safe_load((d / "_interactions.yaml").read_text(encoding="utf8")) or []
            inter = [Interaction(**r) for r in raw]
        drugs: list[Drug] = []
        for f in sorted(d.glob("*.yaml")):
            if f.name.startswith("_"):
                continue
            raw = yaml.safe_load(f.read_text(encoding="utf8")) or []
            if isinstance(raw, dict):
                raw = raw.get("drugs", [])
            drugs.extend(Drug(**r) for r in raw)
        ids = [x.drug_id for x in drugs]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate drug_id in KB")
        return cls(drugs, inter, aliases or {}, version, d)

    @classmethod
    def empty(cls) -> DrugKB:
        return cls([], [], {}, 0)

    # ---- lookups
    def get(self, drug_id: str) -> Drug | None:
        return self.drugs.get(drug_id)

    def resolve_med(self, name: str) -> tuple[str | None, set[str]]:
        """Patient medication name -> (kb drug_id or None, interaction tokens)."""
        n = norm(name)
        did = self._name_index.get(n)
        toks: set[str] = set()
        if did:
            toks |= self.drugs[did].tokens
        for c in self.medication_classes.get(n, []):
            toks.add(f"class:{c}")
        if not did and not toks:
            for k, cls_ in self.medication_classes.items():  # tolerant match: "ibuprofen 400 mg"
                if n.startswith(k):
                    toks |= {f"class:{c}" for c in cls_}
        toks.add(n)
        return did, toks

    def allergy_groups_for(self, allergies: list[str]) -> set[str]:
        groups: set[str] = set()
        for a in allergies:
            n = norm(a)
            if n in self.allergy_aliases:
                groups.add(self.allergy_aliases[n])
            else:
                for k, g in self.allergy_aliases.items():
                    if k in n:
                        groups.add(g)
        return groups

    def condition_flags_for(self, conditions: list[str]) -> set[str]:
        flags: set[str] = set()
        for c in conditions:
            n = norm(c)
            slug = re.sub(r"[^a-z0-9_]+", "_", n).strip("_")
            flags.add(slug)
            if n in self.condition_aliases:
                flags.add(self.condition_aliases[n])
            else:
                for k, g in self.condition_aliases.items():
                    if len(k) > 3 and k in n:
                        flags.add(g)
        return flags

    def status_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.drugs.values():
            out[d.kb_status] = out.get(d.kb_status, 0) + 1
        return out

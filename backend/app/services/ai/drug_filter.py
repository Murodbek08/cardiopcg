"""Deterministic KB safety filter (doc 02 section 15.3). Runs BEFORE the LLM and again AFTER it.

No eval(): contraindication expressions are a tiny JSON DSL:
  {"field": "potassium_mmol_l", "op": ">", "value": 5.5}
  {"all": [expr, ...]} | {"any": [expr, ...]} | {"not": expr}
Evaluation yields True / False / None (None = required field unknown).
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Any

from .kb import Dose, Drug, DrugKB, Indication, norm
from .schemas import AllergyCheck, ContraCheck, InteractionCheck

_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}
SEV_ORDER = {"none": 0, "minor": 1, "moderate": 2, "major": 3, "contraindicated": 4}


def eval_expr(expr: dict[str, Any] | None, fields: dict[str, Any]) -> bool | None:
    if not expr:
        return None
    if "all" in expr:
        res = [eval_expr(e, fields) for e in expr["all"]]
        if any(r is False for r in res):
            return False
        return None if any(r is None for r in res) else True
    if "any" in expr:
        res = [eval_expr(e, fields) for e in expr["any"]]
        if any(r is True for r in res):
            return True
        return None if any(r is None for r in res) else False
    if "not" in expr:
        r = eval_expr(expr["not"], fields)
        return None if r is None else (not r)
    f, op, val = expr.get("field"), expr.get("op"), expr.get("value")
    if f is None or op not in _OPS:
        raise ValueError(f"invalid KB expression: {expr!r}")
    cur = fields.get(f)
    if cur is None:
        return None
    try:
        return bool(_OPS[op](cur, val))
    except TypeError:
        return None


def expr_fields(expr: dict[str, Any] | None) -> set[str]:
    if not expr:
        return set()
    out: set[str] = set()
    for k in ("all", "any"):
        for e in expr.get(k, []):
            out |= expr_fields(e)
    if "not" in expr:
        out |= expr_fields(expr["not"])
    if "field" in expr:
        out.add(expr["field"])
    return out


@dataclass
class PatientView:
    age: float | None
    weight_kg: float | None
    egfr: float | None
    pregnancy: bool | None
    allergy_groups: set[str]
    allergy_names: set[str]
    meds: list[tuple[str, str | None, set[str]]]  # (original name, kb drug_id, tokens)
    flags: set[str]
    fields: dict[str, Any]

    @classmethod
    def from_safety(cls, safety: dict[str, Any], kb: DrugKB) -> PatientView:
        allergies = list(safety.get("allergies") or [])
        meds = []
        for m in safety.get("current_medications") or []:
            did, toks = kb.resolve_med(m.get("inn", ""))
            meds.append((m.get("inn", ""), did, toks))
        flags = kb.condition_flags_for(list(safety.get("conditions") or []))
        if safety.get("pregnancy"):
            flags.add("pregnancy")
        if safety.get("lactation"):
            flags.add("lactation")
        groups = kb.allergy_groups_for(allergies)
        if "sulfonamides_nonantibiotic" in groups:
            flags.add("sulfonamide_allergy")
        if "penicillins" in groups:
            # a penicillin allergy label is not necessarily anaphylaxis; only an explicit flag is
            pass
        fields = dict(safety)
        return cls(
            age=safety.get("age_years"),
            weight_kg=safety.get("weight_kg"),
            egfr=safety.get("egfr_ml_min"),
            pregnancy=safety.get("pregnancy"),
            allergy_groups=groups,
            allergy_names={norm(a) for a in allergies},
            meds=meds,
            flags=flags,
            fields=fields,
        )

    @property
    def population(self) -> str:
        if self.age is None:
            return "adult"
        if self.age < 18:
            return "pediatric"
        if self.age >= 65:
            return "elderly"
        return "adult"


@dataclass
class Candidate:
    drug: Drug
    linked_conditions: list[str]
    evidence_level: str
    dose_context: str | None
    allowed_dose: dict[str, Any]
    contraindications: list[ContraCheck] = field(default_factory=list)
    interactions: list[InteractionCheck] = field(default_factory=list)
    allergy: AllergyCheck = field(default_factory=lambda: AllergyCheck(status="clear", note_uz=""))
    cautions: list[str] = field(default_factory=list)
    max_interaction: str = "none"


@dataclass
class BlockedEntry:
    drug_id: str
    reasons: list[str]


@dataclass
class CandidateSet:
    candidates: list[Candidate]
    blocked: list[BlockedEntry]
    kb_version: int
    note: str | None = None

    def by_id(self) -> dict[str, Candidate]:
        return {c.drug.drug_id: c for c in self.candidates}

    def blocked_ids(self) -> set[str]:
        return {b.drug_id for b in self.blocked}

    def to_llm(self) -> dict[str, Any]:
        """JSON for <KB_CANDIDATES>."""
        return {
            "kb_version": self.kb_version,
            "candidates": [
                {
                    "drug_id": c.drug.drug_id,
                    "inn": c.drug.inn_en,
                    "class": c.drug.drug_class,
                    "linked_condition_codes": c.linked_conditions,
                    "evidence_level": c.evidence_level,
                    "allowed_dose_range": c.allowed_dose,
                    "contraindications_checked": [x.model_dump() for x in c.contraindications],
                    "interactions_checked": [x.model_dump(by_alias=True) for x in c.interactions],
                    "allergy_check": c.allergy.model_dump(),
                    "cautions": c.cautions,
                    "monitoring_uz": [
                        f"{m.parameter}: {m.schedule_uz or ''}".strip(": ") for m in c.drug.monitoring
                    ],
                    "adverse_effects_uz": [a.effect_uz for a in c.drug.adverse_effects],
                }
                for c in self.candidates
            ],
            "blocked": [{"drug_id": b.drug_id, "blocked_by": b.reasons} for b in self.blocked],
        }


def _pick_dose(drug: Drug, population: str, ctxs: list[str]) -> Dose | None:
    order = [population] if population != "elderly" else ["elderly", "adult"]
    for pop in order:
        for d in drug.doses:
            if d.population == pop and (d.indication_context in ctxs or d.indication_context is None):
                return d
    return None


def _apply_renal(
    dose: Dose, pv: PatientView, lo: float | None, hi: float | None, notes: list[str]
) -> tuple[float | None, float | None, str | None]:
    """Returns (lo, hi, block_reason)."""
    if not dose.renal_adjust:
        return lo, hi, None
    if pv.egfr is None:
        notes.append("eGFR ma'lum emas: buyrak funksiyasiga ko'ra doza tuzatish baholanmadi")
        return lo, hi, None
    hits = [r for r in dose.renal_adjust if pv.egfr < r.egfr_lt]
    if not hits:
        return lo, hi, None
    r = min(hits, key=lambda x: x.egfr_lt)
    if r.action == "avoid":
        return lo, hi, f"renal:avoid(egfr<{r.egfr_lt:g})"
    if r.action == "reduce" and r.factor:
        lo = None if lo is None else round(lo * r.factor, 3)
        hi = None if hi is None else round(hi * r.factor, 3)
    if r.note_uz:
        notes.append(r.note_uz)
    return lo, hi, None


def build_candidates(
    kb: DrugKB,
    safety: dict[str, Any],
    differential: list[dict[str, Any]],
    allow_draft: bool = False,
) -> CandidateSet:
    pv = PatientView.from_safety(safety, kb)
    probs = {d["condition_code"]: float(d["probability"]) for d in differential}
    cands: list[Candidate] = []
    blocked: list[BlockedEntry] = []
    n_skipped_status = 0
    for drug in kb.drugs.values():
        if not drug.enabled or drug.kb_status == "retired":
            continue
        if drug.kb_status != "reviewed" and not allow_draft:
            n_skipped_status += 1
            continue
        # 1) indications
        active: list[Indication] = []
        for ind in drug.indications:
            if ind.requires_flags_any:
                if pv.flags & set(ind.requires_flags_any):
                    active.append(ind)
            elif probs.get(ind.condition_code, 0.0) >= ind.min_condition_prob and ind.condition_code in probs:
                active.append(ind)
        if not active:
            continue
        reasons: list[str] = []
        cautions: list[str] = []
        contra: list[ContraCheck] = []

        # 2) allergy
        allergy = AllergyCheck(status="clear", note_uz="")
        for ag in drug.allergy_groups:
            if ag.allergy_group in pv.allergy_groups:
                if ag.strength == "absolute":
                    reasons.append(f"allergy:{ag.allergy_group}")
                    allergy = AllergyCheck(
                        status="blocked",
                        note_uz=f"Bemorda {ag.allergy_group} guruhiga allergiya qayd etilgan",
                    )
                else:
                    cautions.append(f"allergy_relative:{ag.allergy_group}")
                    if allergy.status != "blocked":
                        allergy = AllergyCheck(
                            status="cross_reactivity_possible",
                            note_uz=f"{ag.allergy_group} guruhiga allergiya: kross-reaktivlik ehtimoli",
                        )
            for cr in ag.cross_reactive_with:
                if cr in pv.allergy_groups and allergy.status == "clear":
                    cautions.append(f"cross_reactivity:{cr}")
                    allergy = AllergyCheck(
                        status="cross_reactivity_possible",
                        note_uz=f"{cr} ga allergiya: kross-reaktivlik ehtimoli",
                    )
        for nm in (drug.inn_en, drug.inn_uz or "", drug.drug_id, *drug.aliases):
            if nm and norm(nm) in pv.allergy_names:
                reasons.append("allergy:direct")
                allergy = AllergyCheck(
                    status="blocked", note_uz="Bemorda shu dorining o'ziga allergiya qayd etilgan"
                )
                break

        # 3) contraindications
        for c in drug.contraindications:
            if c.condition_expr:
                r = eval_expr(c.condition_expr, pv.fields)
                if r is True:
                    trig = True
                elif r is None:
                    trig = c.code in pv.flags
                    miss = sorted(f for f in expr_fields(c.condition_expr) if pv.fields.get(f) is None)
                    if not trig and miss:
                        cautions.append(f"data_missing:{','.join(miss)}")
                        contra.append(
                            ContraCheck(item=f"{c.code} (ma'lumot yo'q: {', '.join(miss)})", status="caution")
                        )
                        continue
                else:
                    trig = c.code in pv.flags
            else:
                trig = c.code in pv.flags
            if trig:
                if c.kind == "absolute":
                    reasons.append(f"contraindication:{c.code}")
                    contra.append(ContraCheck(item=c.code, status="blocked"))
                else:
                    cautions.append(f"relative_contraindication:{c.code}")
                    contra.append(ContraCheck(item=c.code, status="caution"))
            else:
                contra.append(ContraCheck(item=c.code, status="clear"))

        # 4) interactions with current medications
        inter: list[InteractionCheck] = []
        max_sev = "none"
        for name, did, toks in pv.meds:
            if did == drug.drug_id:
                cautions.append("already_on_drug")
            for row in kb.interactions:
                hit = (row.drug_a in drug.tokens and row.drug_b_or_class in toks) or (
                    row.drug_b_or_class in drug.tokens and row.drug_a in toks
                )
                if hit:
                    inter.append(
                        InteractionCheck(
                            **{"with": name or row.drug_b_or_class},
                            severity=row.severity,
                            note_uz=f"{row.effect_uz or ''} {('- ' + row.management_uz) if row.management_uz else ''}".strip(),
                        )
                    )
                    if SEV_ORDER[row.severity] > SEV_ORDER[max_sev]:
                        max_sev = row.severity
                    if row.severity == "contraindicated":
                        reasons.append(f"interaction:contraindicated:{name}")
                    elif row.severity == "major":
                        cautions.append(f"interaction:major:{name}")

        # 5) dose
        ctxs = [x for x in {*(i.dose_context or i.condition_code for i in active)} if x]
        dose = _pick_dose(drug, pv.population, ctxs)
        allowed: dict[str, Any] = {}
        dnotes: list[str] = []
        if dose is None:
            reasons.append(f"no_dose_for_population:{pv.population}")
        else:
            lo, hi = dose.dose_min, dose.dose_max
            if dose.weight_based:
                if pv.weight_kg is None:
                    reasons.append("weight_required")
                else:
                    lo = round((dose.per_kg_min or 0) * pv.weight_kg, 1)
                    hi = round((dose.per_kg_max or 0) * pv.weight_kg, 1)
                    if dose.max_daily is not None:
                        lo, hi = min(lo, dose.max_daily), min(hi, dose.max_daily)
            lo, hi, rb = _apply_renal(dose, pv, lo, hi, dnotes)
            if rb:
                reasons.append(rb)
            if pv.age is None:
                dnotes.append("Bemor yoshi ma'lum emas: kattalar dozasi referens sifatida")
            allowed = {
                "min": lo,
                "max": hi,
                "unit": dose.unit,
                "frequency": dose.frequency,
                "route": dose.route,
                "max_daily": dose.max_daily,
                "population": dose.population,
                "titration_uz": dose.titration_uz,
                "notes_uz": dnotes,
            }
        cautions.extend(dnotes)

        if reasons:
            blocked.append(BlockedEntry(drug.drug_id, sorted(set(reasons))))
            continue
        ev = max(
            (i.evidence_level for i in active), key=lambda e: {"limited": 0, "expert": 1, "guideline": 2}[e]
        )
        cands.append(
            Candidate(
                drug=drug,
                linked_conditions=sorted({i.condition_code for i in active}),
                evidence_level=ev,
                dose_context=ctxs[0] if ctxs else None,
                allowed_dose=allowed,
                contraindications=contra,
                interactions=inter,
                allergy=allergy,
                cautions=cautions,
                max_interaction=max_sev,
            )
        )
    note = None
    if n_skipped_status:
        note = f"{n_skipped_status} ta dori KB da kb_status!=reviewed bo'lgani uchun taklif doirasidan chiqarildi"
    return CandidateSet(cands, blocked, kb.version, note)

"""Post-LLM hallucination guard for drug proposals (doc 02 section 15.6 / 16).

The KB is authoritative. Whatever the LLM claims about allergies, contraindications and
interactions is OVERWRITTEN with the deterministic result; unknown/blocked drugs are removed;
doses outside the KB range are rejected (strict) or clamped.
"""

from __future__ import annotations

import re

from .drug_filter import SEV_ORDER, Candidate, CandidateSet
from .kb import DrugKB
from .schemas import BlockedDrug, DoseOut, DrugProposal, DrugProposalsResult, LLMDrugProposals

NO_SAFE_PROPOSAL_UZ = "AI xavfsiz taklif topa olmadi; shifokor mustaqil qaror qiladi."

# imperative / guarantee tone that must not appear in "information only" proposals (doc 15.6-6)
_TONE = re.compile(
    r"(?i)\b(albatta|kafolat\w*|retsept\w*|ichishni\s+boshlang|ichishni\s+boshlash\s+kerak|darhol\s+(iching|boshlang)|"
    r"shart\s+ravishda|so['’`]zsiz|must\s+take|prescribe[sd]?|guarantee\w*)\b"
)
NEUTRAL_UZ = "Qaror shifokor tomonidan qabul qilinadi."
_EPS = 1e-6


def _neutralise(text: str, events: list[str], drug_id: str) -> str:
    if not text or not _TONE.search(text):
        return text
    events.append(f"tone_rewritten:{drug_id}")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not _TONE.search(s)]
    out = " ".join(kept).strip()
    return (out + " " + NEUTRAL_UZ).strip() if out else NEUTRAL_UZ


def validate_drug_proposals(
    llm: LLMDrugProposals | None,
    cset: CandidateSet,
    kb: DrugKB,
    *,
    strict: bool = True,
    model: str | None = None,
    prompt_version: str | None = None,
    cache_hit: bool = False,
) -> DrugProposalsResult:
    events: list[str] = []
    excluded: list[BlockedDrug] = [
        BlockedDrug(drug_id=b.drug_id, reasons=b.reasons, source="kb_filter") for b in cset.blocked
    ]
    if llm is None:
        return DrugProposalsResult(
            status="unavailable",
            excluded=excluded,
            kb_version=cset.kb_version,
            message_uz=NO_SAFE_PROPOSAL_UZ,
            kb_status_note=cset.note,
        )
    cands = cset.by_id()
    blocked_ids = cset.blocked_ids()
    kept: list[tuple[DrugProposal, Candidate]] = []
    seen: set[str] = set()

    for p in llm.proposals:
        did = p.drug_id
        # 1) closed set
        if did in blocked_ids:
            events.append(f"blocked_drug_leak:{did}")
            continue
        cand = cands.get(did)
        if cand is None:
            events.append(f"unknown_drug:{did}")
            continue
        if did in seen:
            events.append(f"duplicate_proposal:{did}")
            continue
        allowed = cand.allowed_dose
        # 2) dose range / unit / route
        if p.dose.unit.strip().lower() != str(
            allowed.get("unit", "")
        ).strip().lower() or p.dose.route != allowed.get("route"):
            events.append(f"dose_unit_or_route_mismatch:{did}")
            continue
        lo, hi = allowed.get("min"), allowed.get("max")
        dmin, dmax = p.dose.min, p.dose.max
        if lo is not None and hi is not None and (dmin < lo - _EPS or dmax > hi + _EPS):
            if strict:
                events.append(f"dose_out_of_range:{did}")
                continue
            dmin, dmax = min(max(dmin, lo), hi), min(max(dmax, lo), hi)
            events.append(f"dose_clamped:{did}")
        # 3) KB overrides the LLM's own safety claims
        kb_has_issue = (
            cand.allergy.status != "clear"
            or any(c.status != "clear" for c in cand.contraindications)
            or cand.max_interaction in ("moderate", "major", "contraindicated")
        )
        llm_clear = (
            p.allergy_check.status == "clear"
            and all(c.status == "clear" for c in p.contraindications_checked)
            and all(SEV_ORDER[i.severity] <= 1 for i in p.interactions_checked)
        )
        if kb_has_issue and llm_clear:
            events.append(f"llm_kb_mismatch:{did}")
        # 4) text hygiene
        indication = _neutralise(p.indication_uz, events, did)
        adj = _neutralise(p.dose.adjustment_applied_uz, events, did)
        drug = cand.drug
        evidence = cand.evidence_level  # LLM may not upgrade evidence
        low_conf = (p.confidence < 0.5) or (evidence == "limited" and p.confidence < 0.5)
        if low_conf:
            events.append(f"low_confidence:{did}")
        if drug.kb_status != "reviewed":
            events.append(f"kb_draft_entry:{did}")
        dose = DoseOut(
            min=dmin,
            max=dmax,
            unit=allowed.get("unit", p.dose.unit),
            frequency=allowed.get("frequency") or p.dose.frequency,
            route=allowed.get("route", p.dose.route),
            duration_uz=p.dose.duration_uz,
            adjustment_applied_uz=adj,
        )
        if (allowed.get("frequency") or "") != p.dose.frequency:
            events.append(f"frequency_from_kb:{did}")
        prop = DrugProposal(
            drug_id=did,
            inn=drug.inn_en,
            inn_uz=drug.inn_uz,
            atc_code=drug.atc_code,
            drug_class=drug.drug_class,
            class_group=drug.class_group,
            indication_uz=indication,
            linked_condition_codes=cand.linked_conditions,
            dose=dose,
            kb_allowed_range={k: v for k, v in allowed.items() if k != "notes_uz"},
            contraindications_checked=cand.contraindications,
            interactions_checked=cand.interactions,
            allergy_check=cand.allergy,
            monitoring_uz=[
                f"{m.parameter}" + (f" - {m.schedule_uz}" if m.schedule_uz else "") for m in drug.monitoring
            ],
            adverse_effects_uz=[a.effect_uz for a in drug.adverse_effects],
            evidence_level=evidence,
            confidence=round(p.confidence, 3),
            low_confidence=low_conf,
            kb_status=drug.kb_status,
            kb_version=kb.version,
            sources=drug.sources,
            warnings_uz=list(
                dict.fromkeys(
                    allowed.get("notes_uz", [])
                    + [f"Ehtiyot: {c}" for c in cand.cautions if not c.startswith("data_missing")]
                )
            ),
        )
        seen.add(did)
        kept.append((prop, cand))

    # 5) intra-proposal conflicts / same-class duplicates (higher confidence wins)
    final_pairs: list[tuple[DrugProposal, Candidate]] = []
    for prop, cand in sorted(kept, key=lambda t: -t[0].confidence):
        drop = False
        for other, ocand in final_pairs:
            if other.drug_class == prop.drug_class:
                events.append(f"class_duplicate:{prop.drug_id}~{other.drug_id}")
                drop = True
                break
            for row in kb.interactions:
                a, b = row.drug_a, row.drug_b_or_class
                linked = (a in cand.drug.tokens and b in ocand.drug.tokens) or (
                    b in cand.drug.tokens and a in ocand.drug.tokens
                )
                if linked and SEV_ORDER[row.severity] >= SEV_ORDER["major"]:
                    events.append(f"proposal_interaction:{prop.drug_id}~{other.drug_id}:{row.severity}")
                    drop = True
                    break
            if drop:
                break
        if drop:
            excluded.append(
                BlockedDrug(
                    drug_id=prop.drug_id, reasons=["guard:class_duplicate_or_interaction"], source="guard"
                )
            )
        else:
            final_pairs.append((prop, cand))
    final = [p for p, _ in final_pairs]

    # LLM-excluded drugs (only for ids that really exist in the KB)
    for ex in llm.excluded:
        if kb.get(ex.drug_id) is not None and ex.drug_id not in {e.drug_id for e in excluded}:
            excluded.append(
                BlockedDrug(drug_id=ex.drug_id, reasons=[ex.reason_uz[:300]], source="llm_excluded")
            )

    measures = [_neutralise(m, events, "non_drug") for m in llm.non_drug_measures_uz]
    msg = None if final else NO_SAFE_PROPOSAL_UZ
    return DrugProposalsResult(
        status="ok",
        proposals=final,
        excluded=excluded,
        non_drug_measures_uz=measures,
        kb_version=cset.kb_version,
        kb_status_note=cset.note,
        guard_events=events,
        message_uz=msg,
        model=model,
        prompt_version=prompt_version,
        cache_hit=cache_hit,
    )

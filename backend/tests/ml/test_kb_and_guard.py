"""Local drug KB: loader, deterministic filter (allergy/contraindication/interaction/dose) and the
post-LLM hallucination guard."""

from __future__ import annotations

import pytest
from ai_helpers import drug_item, load_kb

from app.services.ai.deidentify import build_context
from app.services.ai.drug_filter import build_candidates, eval_expr
from app.services.ai.drug_guard import NO_SAFE_PROPOSAL_UZ, validate_drug_proposals
from app.services.ai.kb import DrugKB
from app.services.ai.schemas import LLMDrugProposals

KB = load_kb()
HF = [
    {"condition_code": "heart_failure", "probability": 0.5},
    {"condition_code": "other_undetermined", "probability": 0.5},
]


def safety(**kw):
    base = {
        "age": 54,
        "sex": "male",
        "weight_kg": 82,
        "labs": {"egfr_ml_min": 62, "potassium_mmol_l": 4.6},
        "hr_bpm": 72,
    }
    base.update(kw)
    return build_context(base).safety


def ids(cs):
    return {c.drug.drug_id for c in cs.candidates}


def blocked(cs):
    return {b.drug_id: b.reasons for b in cs.blocked}


# --------------------------------------------------------------- KB / DSL


def test_kb_loads_with_draft_status_and_interactions():
    assert KB.version >= 1 and len(KB.drugs) >= 12 and len(KB.interactions) >= 20
    assert all(d.kb_status == "draft" for d in KB.drugs.values())  # nothing is clinically reviewed
    assert KB.get("furosemide").enabled and not KB.get("amiodarone").enabled


def test_expression_dsl():
    f = {"k": 6.0, "egfr": 20}
    assert eval_expr({"field": "k", "op": ">", "value": 5.5}, f) is True
    assert (
        eval_expr(
            {"all": [{"field": "k", "op": ">", "value": 5.5}, {"field": "egfr", "op": "<", "value": 30}]}, f
        )
        is True
    )
    assert (
        eval_expr(
            {"any": [{"field": "k", "op": "<", "value": 3}, {"field": "egfr", "op": ">", "value": 60}]}, f
        )
        is False
    )
    assert eval_expr({"not": {"field": "k", "op": "<", "value": 3}}, f) is True
    assert eval_expr({"field": "missing", "op": ">", "value": 1}, f) is None
    with pytest.raises(ValueError):
        eval_expr({"field": "k", "op": "__import__('os')", "value": 1}, f)  # no eval()


def test_reviewed_gate_excludes_draft_by_default():
    cs = build_candidates(KB, safety(), HF, allow_draft=False)
    assert cs.candidates == [] and "kb_status" in (cs.note or "")
    cs2 = build_candidates(KB, safety(), HF, allow_draft=True)
    assert {"furosemide", "enalapril", "metoprolol_succinate"} <= ids(cs2)


def test_reviewed_entries_pass_without_draft_flag():
    kb = DrugKB.load(KB.path)
    kb.drugs["furosemide"] = kb.drugs["furosemide"].model_copy(update={"kb_status": "reviewed"})
    cs = build_candidates(kb, safety(), HF, allow_draft=False)
    assert ids(cs) == {"furosemide"}


def test_indication_probability_threshold():
    low = [
        {"condition_code": "heart_failure", "probability": 0.1},
        {"condition_code": "other_undetermined", "probability": 0.9},
    ]
    assert build_candidates(KB, safety(), low, allow_draft=True).candidates == []


# --------------------------------------------------------------- contraindications / allergy / interactions


def test_pregnancy_blocks_ace_and_arb():
    cs = build_candidates(KB, safety(pregnancy=True, sex="female"), HF, allow_draft=True)
    b = blocked(cs)
    assert "contraindication:pregnancy" in b["enalapril"] and "contraindication:pregnancy" in b["losartan"]
    assert "enalapril" not in ids(cs)


def test_hyperkalemia_blocks_spironolactone_and_ace():
    cs = build_candidates(KB, safety(labs={"egfr_ml_min": 62, "potassium_mmol_l": 5.9}), HF, allow_draft=True)
    b = blocked(cs)
    assert (
        "contraindication:hyperkalemia" in b["spironolactone"]
        and "contraindication:hyperkalemia" in b["enalapril"]
    )


def test_egfr_25_blocks_spironolactone_and_halves_ace_dose():
    cs = build_candidates(KB, safety(labs={"egfr_ml_min": 25, "potassium_mmol_l": 4.5}), HF, allow_draft=True)
    assert "spironolactone" in blocked(cs)
    en = cs.by_id()["enalapril"]
    assert en.allowed_dose["max"] == pytest.approx(10.0) and en.allowed_dose["min"] == pytest.approx(1.25)
    assert any("Past dozadan" in n for n in en.allowed_dose["notes_uz"])


def test_bradycardia_blocks_beta_blockers():
    cs = build_candidates(KB, safety(hr_bpm=45), HF, allow_draft=True)
    b = blocked(cs)
    assert "contraindication:severe_bradycardia" in b["metoprolol_succinate"]
    assert "bisoprolol" in b and "carvedilol" in b


def test_verapamil_contraindicated_with_beta_blocker():
    s = safety(current_medications=[{"inn": "verapamil", "dose_mg": 120}])
    cs = build_candidates(KB, s, HF, allow_draft=True)
    assert any(r.startswith("interaction:contraindicated") for r in blocked(cs)["metoprolol_succinate"])


def test_major_interactions_are_cautions_not_blocks():
    s = safety(current_medications=[{"inn": "spironolactone"}, {"inn": "ibuprofen"}])
    cs = build_candidates(KB, s, HF, allow_draft=True)
    en = cs.by_id()["enalapril"]
    assert en.max_interaction == "major"
    assert {i.severity for i in en.interactions} >= {"major", "moderate"}
    assert any(c.startswith("interaction:major") for c in en.cautions)
    # ACEi + ARB (class based): losartan flagged when patient is on enalapril
    cs2 = build_candidates(KB, safety(current_medications=[{"inn": "enalapril"}]), HF, allow_draft=True)
    assert cs2.by_id()["losartan"].max_interaction == "major"
    assert "already_on_drug" in cs2.by_id()["enalapril"].cautions


def test_missing_labs_become_cautions_not_silent_clear():
    cs = build_candidates(KB, build_context({"age": 54, "weight_kg": 80}).safety, HF, allow_draft=True)
    en = cs.by_id()["enalapril"]
    assert any(c.startswith("data_missing") for c in en.cautions)
    assert any("ma'lumot yo'q" in c.item for c in en.contraindications)
    assert any("eGFR ma'lum emas" in n for n in en.allowed_dose["notes_uz"])


def test_ie_prophylaxis_needs_high_risk_flag_and_respects_penicillin_allergy():
    diff = [{"condition_code": "infective_endocarditis", "probability": 0.05}]
    assert (
        build_candidates(KB, safety(), diff, allow_draft=True).candidates == []
    )  # no flag -> no prophylaxis
    s = safety(conditions=["sun'iy qopqoq"], allergies=["penitsillin"])
    cs = build_candidates(KB, s, diff, allow_draft=True)
    assert "allergy:penicillins" in blocked(cs)["amoxicillin_ie_prophylaxis"]
    assert "azithromycin_ie_prophylaxis" in ids(cs)
    cs2 = build_candidates(KB, safety(conditions=["prosthetic valve"]), diff, allow_draft=True)
    assert {"amoxicillin_ie_prophylaxis", "azithromycin_ie_prophylaxis"} <= ids(cs2)


def test_cephalosporin_allergy_cross_reactivity_caution_on_amoxicillin():
    s = safety(conditions=["prosthetic valve"], allergies=["sefalosporin"])
    cs = build_candidates(KB, s, [], allow_draft=True)
    am = cs.by_id()["amoxicillin_ie_prophylaxis"]
    assert am.allergy.status == "cross_reactivity_possible"


def test_valve_anticoagulation_rules():
    diff = [{"condition_code": "arrhythmia_suspected", "probability": 0.2}]
    s = safety(conditions=["atrial fibrillation", "mexanik qopqoq"])
    cs = build_candidates(KB, s, diff, allow_draft=True)
    assert "contraindication:mechanical_valve" in blocked(cs)["apixaban"]
    assert "warfarin" in ids(cs)  # VKA stays possible
    s2 = safety(conditions=["atrial fibrillation"])
    cs2 = build_candidates(KB, s2, diff, allow_draft=True)
    assert "apixaban" in ids(cs2)
    # without confirmed AF flag PCG alone is NOT an anticoagulation indication
    assert build_candidates(KB, safety(), diff, allow_draft=True).candidates == []
    # NSAID + warfarin
    s3 = safety(
        conditions=["atrial fibrillation", "mexanik qopqoq"], current_medications=[{"inn": "diclofenac"}]
    )
    w = build_candidates(KB, s3, diff, allow_draft=True).by_id()["warfarin"]
    assert w.max_interaction == "major"


def test_pediatric_weight_based_dose_and_missing_weight():
    base = dict(conditions=["prosthetic valve"])
    cs = build_candidates(KB, safety(age=8, weight_kg=25, **base), [], allow_draft=True)
    am = cs.by_id()["amoxicillin_ie_prophylaxis"]
    assert am.allowed_dose["min"] == am.allowed_dose["max"] == pytest.approx(1250.0)
    cs2 = build_candidates(
        KB, build_context({"age": 8, "conditions": ["prosthetic valve"]}).safety, [], allow_draft=True
    )
    assert "weight_required" in blocked(cs2)["amoxicillin_ie_prophylaxis"]
    cs3 = build_candidates(KB, safety(age=8, weight_kg=25), HF, allow_draft=True)
    assert all(
        r[0].startswith("no_dose_for_population") for r in blocked(cs3).values()
    )  # adults-only KB doses


def test_sulfonamide_allergy_is_caution_for_furosemide():
    cs = build_candidates(KB, safety(allergies=["sulfanilamid"]), HF, allow_draft=True)
    f = cs.by_id()["furosemide"]
    assert f.allergy.status == "cross_reactivity_possible"


def test_llm_payload_shape():
    cs = build_candidates(KB, safety(), HF, allow_draft=True)
    p = cs.to_llm()
    assert p["kb_version"] == KB.version and p["candidates"]
    c0 = p["candidates"][0]
    assert {
        "drug_id",
        "allowed_dose_range",
        "contraindications_checked",
        "interactions_checked",
        "allergy_check",
    } <= set(c0)


# --------------------------------------------------------------- guard


def proposals(*items):
    return LLMDrugProposals.model_validate(
        {"proposals": list(items), "excluded": [], "non_drug_measures_uz": [], "disclaimer_uz": ""}
    )


def cset(**kw):
    return build_candidates(KB, safety(**kw), HF, allow_draft=True)


def test_guard_removes_hallucinated_and_blocked_drugs():
    cs = cset(pregnancy=True, sex="female")
    llm = proposals(
        drug_item(),
        drug_item("sildenafil", "sildenafil", "pde5"),
        drug_item("enalapril", "enalapril", "ace_inhibitor", 2.5, 10, freq="bid"),
    )
    res = validate_drug_proposals(llm, cs, KB)
    assert [p.drug_id for p in res.proposals] == ["furosemide"]
    assert "unknown_drug:sildenafil" in res.guard_events and "blocked_drug_leak:enalapril" in res.guard_events


def test_guard_dose_strict_rejects_and_lenient_clamps():
    cs = cset()
    bad = proposals(drug_item(dmin=20, dmax=400))
    strict = validate_drug_proposals(bad, cs, KB, strict=True)
    assert strict.proposals == [] and "dose_out_of_range:furosemide" in strict.guard_events
    assert strict.message_uz == NO_SAFE_PROPOSAL_UZ
    lenient = validate_drug_proposals(bad, cs, KB, strict=False)
    assert lenient.proposals[0].dose.max == 80 and "dose_clamped:furosemide" in lenient.guard_events


def test_guard_rejects_unit_or_route_mismatch():
    cs = cset()
    res = validate_drug_proposals(proposals(drug_item(unit="g")), cs, KB)
    assert res.proposals == [] and "dose_unit_or_route_mismatch:furosemide" in res.guard_events
    res = validate_drug_proposals(proposals(drug_item(route="iv")), cs, KB)
    assert res.proposals == []


def test_guard_kb_overrides_llm_safety_claims_and_text():
    cs = cset(current_medications=[{"inn": "spironolactone"}])
    en = drug_item(
        "enalapril",
        "enalapril",
        "ace_inhibitor",
        2.5,
        20,
        freq="bid",
        interactions_checked=[{"with": "spironolactone", "severity": "none", "note_uz": "xavfsiz"}],
        indication_uz="Albatta ichishni boshlang. Retsept: kunda 2 mahal. Yurak yetishmovchiligida qo'llaniladi.",
        evidence_level="guideline",
        confidence=0.9,
    )
    res = validate_drug_proposals(proposals(en), cs, KB)
    p = res.proposals[0]
    assert p.interactions_checked and p.interactions_checked[0].severity == "major"  # KB, not LLM
    assert p.monitoring_uz and "LLM" not in " ".join(p.monitoring_uz)
    assert "llm_kb_mismatch:enalapril" in res.guard_events or any(
        i.severity == "major" for i in p.interactions_checked
    )
    assert "tone_rewritten:enalapril" in res.guard_events
    assert "Albatta" not in p.indication_uz and "Retsept" not in p.indication_uz


def test_guard_forces_draft_and_doctor_approval_and_kb_evidence():
    cs = cset()
    res = validate_drug_proposals(proposals(drug_item(evidence_level="guideline", conf=0.3)), cs, KB)
    p = res.proposals[0]
    assert p.status == "draft" and p.requires_doctor_approval is True and p.kb_status == "draft"
    assert p.low_confidence is True and "kb_draft_entry:furosemide" in res.guard_events
    assert p.kb_allowed_range["max"] == 80 and p.sources


def test_guard_class_duplicate_and_ace_arb_conflict():
    cs = cset()
    ace2 = proposals(
        drug_item("enalapril", "enalapril", "ace_inhibitor", 2.5, 20, freq="bid", conf=0.8),
        drug_item("ramipril", "ramipril", "ace_inhibitor", 1.25, 10, freq="qd-bid", conf=0.6),
    )
    r = validate_drug_proposals(ace2, cs, KB)
    assert [p.drug_id for p in r.proposals] == ["enalapril"]
    assert any(e.startswith("class_duplicate") for e in r.guard_events)
    mix = proposals(
        drug_item("enalapril", "enalapril", "ace_inhibitor", 2.5, 20, freq="bid", conf=0.8),
        drug_item("losartan", "losartan", "angiotensin_receptor_blocker", 25, 100, freq="qd", conf=0.7),
    )
    r2 = validate_drug_proposals(mix, cs, KB)
    assert [p.drug_id for p in r2.proposals] == ["enalapril"]
    assert any(e.startswith("proposal_interaction") for e in r2.guard_events)
    assert any(x.source == "guard" for x in r2.excluded)


def test_guard_none_and_empty():
    cs = cset()
    r = validate_drug_proposals(None, cs, KB)
    assert r.status == "unavailable" and r.proposals == []
    r2 = validate_drug_proposals(proposals(), cs, KB)
    assert r2.status == "ok" and r2.message_uz == NO_SAFE_PROPOSAL_UZ
    assert any(
        b.source == "kb_filter"
        for b in validate_drug_proposals(proposals(), cset(pregnancy=True), KB).excluded
    )


def test_guard_duplicate_proposal_ids():
    cs = cset()
    r = validate_drug_proposals(proposals(drug_item(), drug_item()), cs, KB)
    assert len(r.proposals) == 1 and "duplicate_proposal:furosemide" in r.guard_events

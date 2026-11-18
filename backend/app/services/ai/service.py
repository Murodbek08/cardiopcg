"""`AnalysisService`: signal pipeline + DeepSeek clinical reasoning + KB-grounded drug proposals."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.ml.classifier import ModelRegistry
from app.ml.pipeline import analyze_recording
from app.ml.schemas import PcgAnalysisResult

from . import prompts
from .clinical_guard import guard_assessment, template_assessment
from .config import AISettings
from .deepseek_client import (
    AIBreakerOpen,
    AIBudgetExceeded,
    AIDisabled,
    AIError,
    AIRateLimited,
    DeepSeekClient,
)
from .deidentify import DeidResult, assert_no_pii, build_context, canonical_json, sha256_hex
from .drug_filter import CandidateSet, build_candidates
from .drug_guard import NO_SAFE_PROPOSAL_UZ, validate_drug_proposals
from .kb import DrugKB
from .schemas import (
    AiAssessmentResult,
    AiCallRecord,
    AnalysisOptions,
    AnalysisOutput,
    ClinicalAssessment,
    DeidInfo,
    DrugProposalsResult,
    LLMDrugProposals,
)

log = logging.getLogger("cardiopcg.ai.service")

_STATUS_MAP: list[tuple[type[AIError], str, str]] = [
    (AIRateLimited, "rate_limited", "rate_limited"),
    (AIBudgetExceeded, "budget_exceeded", "budget"),
]


def _safety_for_llm(safety: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "age_years",
        "weight_kg",
        "sex",
        "pregnancy",
        "lactation",
        "egfr_ml_min",
        "creatinine_umol_l",
        "alt",
        "child_pugh",
        "potassium_mmol_l",
        "allergies",
        "current_medications",
        "conditions",
        "bp_sys",
        "hr_bpm",
    )
    out = {k: safety[k] for k in keys if safety.get(k) is not None}
    if isinstance(out.get("age_years"), (int, float)) and out["age_years"] >= 90:
        out["age_years"] = "90+"  # doc 14.1
    return out


class AnalysisService:
    """Implements `AnalysisPort`. One instance per process (holds the KB, ML registry and HTTP client)."""

    def __init__(
        self,
        settings: AISettings | None = None,
        *,
        client: DeepSeekClient | None = None,
        kb: DrugKB | None = None,
        registry: ModelRegistry | None = None,
        model_dir: str | Path | None = None,
    ):
        self.settings = settings or AISettings.from_env()
        self.client = client or DeepSeekClient(self.settings)
        if kb is not None:
            self.kb = kb
        else:
            try:
                self.kb = DrugKB.load(self.settings.kb_dir)
            except Exception:  # noqa: BLE001 - AI must still work without a KB (no drug proposals)
                log.exception("drug KB failed to load; drug proposals disabled")
                self.kb = DrugKB.empty()
        self.registry = registry if registry is not None else ModelRegistry.load(model_dir)
        for w in self.registry.warnings:
            log.warning("ml.registry: %s", w)

    # ------------------------------------------------------------------ public API

    async def analyze(
        self,
        audio: bytes | str | os.PathLike[str],
        context: Mapping[str, Any] | None = None,
        options: AnalysisOptions | Mapping[str, Any] | None = None,
    ) -> AnalysisOutput:
        opts = self._opts(options)
        ctx = dict(context or {})
        age = ctx.get("age_years", ctx.get("age"))
        try:
            age_f = float(age) if age is not None else None
        except (TypeError, ValueError):
            age_f = None
        src: Any = bytes(audio) if isinstance(audio, (bytes, bytearray)) else str(audio)
        pcg, arts = await asyncio.to_thread(
            analyze_recording,
            src,
            source=opts.source,
            site=opts.site,
            age_years=age_f,
            registry=self.registry,
            paper_speed_mm_s=opts.paper_speed_mm_s,
            px_per_mm=opts.px_per_mm,
            image_roi=opts.image_roi,
        )
        pcg.recording_id = opts.recording_id
        pcg.analysis_id = opts.analysis_id
        out = await self._ai_stage(pcg, ctx, opts)
        out.artifacts = arts
        return out

    async def regenerate_ai(
        self,
        pcg: PcgAnalysisResult,
        context: Mapping[str, Any] | None = None,
        options: AnalysisOptions | Mapping[str, Any] | None = None,
    ) -> AnalysisOutput:
        return await self._ai_stage(pcg, dict(context or {}), self._opts(options))

    async def aclose(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _opts(options: AnalysisOptions | Mapping[str, Any] | None) -> AnalysisOptions:
        if isinstance(options, AnalysisOptions):
            return options
        return AnalysisOptions(**dict(options or {}))

    async def _ai_stage(
        self, pcg: PcgAnalysisResult, ctx: dict[str, Any], opts: AnalysisOptions
    ) -> AnalysisOutput:
        request_ref = "r-" + secrets.token_hex(6)
        calls: list[AiCallRecord] = []
        kb_version = self.kb.version or None
        base = dict(pcg=pcg, kb_version=kb_version, prompt_version=prompts.PROMPT_VERSION)

        def finish(
            ai: AiAssessmentResult, drugs: DrugProposalsResult, deid: DeidResult | None = None
        ) -> AnalysisOutput:
            urgent = bool(ai.assessment and ai.assessment.risk.level in ("high", "urgent"))
            return AnalysisOutput(
                ai=ai,
                drugs=drugs,
                disclaimers=prompts.build_disclaimers(urgent=urgent),
                ai_calls=calls,
                deid=None
                if deid is None
                else DeidInfo(
                    input_hash=deid.input_hash,
                    input_fields=deid.input_fields,
                    dropped_fields=deid.dropped_fields,
                    flags=deid.flags.as_dict(),
                    request_ref=request_ref,
                ),
                **base,
            )

        empty_drugs = DrugProposalsResult(status="skipped", kb_version=kb_version)
        if not opts.run_ai:
            return finish(AiAssessmentResult(status="skipped"), empty_drugs)
        if not opts.ai_consent:  # doc 14.3: patients.ai_consent=false -> no external AI call
            return finish(
                AiAssessmentResult(status="consent_missing", message_uz="Bemor AI uchun rozilik bermagan"),
                empty_drugs,
            )
        if pcg.status != "ok" or pcg.quality is None or pcg.quality.sqi < self.settings.min_sqi_for_ai:
            return finish(
                AiAssessmentResult(
                    status="blocked_low_quality",
                    message_uz="Signal sifati past: AI izoh va dori moduli chaqirilmadi, qayta yozing",
                ),
                empty_drugs,
            )

        deid = build_context(ctx)  # allow-list + sanitiser + PII guard (raises PIIGuardError on leak)
        pcg_payload = prompts.pcg_for_llm(pcg)
        assert_no_pii(pcg_payload)
        low_conf = bool(
            pcg.quality.sqi < 0.7
            or pcg.source == "image"
            or (pcg.classification and (pcg.classification.uncertainty or 0) > 0.3)
        )
        template = template_assessment(pcg)

        def fallback(
            status: str, call_status: str, err: str, guard: str
        ) -> tuple[AiAssessmentResult, DrugProposalsResult]:
            calls.append(
                AiCallRecord(
                    call_type="clinical_assessment",
                    model=self.settings.model_chat,
                    prompt_version=prompts.PROMPT_VERSION,
                    input_hash=deid.input_hash,
                    input_fields=deid.input_fields,
                    status="fallback" if call_status == "ok" else call_status,  # type: ignore[arg-type]
                    error=err[:300],
                )
            )
            ai = AiAssessmentResult(
                status=status,
                source="rule_template",
                assessment=template,
                prompt_version=prompts.PROMPT_VERSION,  # type: ignore[arg-type]
                guard_events=[guard],
                low_confidence_mode=low_conf,
                message_uz="AI izoh vaqtincha mavjud emas, keyinroq qayta urinib ko'ring (signal natijalari to'liq)",
            )
            drugs = DrugProposalsResult(
                status=status,
                kb_version=kb_version,  # type: ignore[arg-type]
                message_uz="AI mavjud emas: dori taklifi berilmaydi (shifokor mustaqil qaror qiladi)",
            )
            return ai, drugs

        if not self.client.available:
            ai, drugs = fallback("unavailable", "fallback", "no api key", "ai_disabled")
            return finish(ai, drugs, deid)

        # ---------------- Call A: clinical assessment
        model_a = self.settings.model_chat
        if (
            self.settings.use_reasoner_on_disagree
            and pcg.classification
            and pcg.classification.models_disagree
        ):
            model_a = self.settings.model_reasoner
        user_a = prompts.build_clinical_user_prompt(deid.llm_context, pcg_payload, low_conf)
        try:
            res_a = await self.client.complete_json(
                prompts.CLINICAL_SYSTEM_PROMPT,
                user_a,
                ClinicalAssessment,
                model=model_a,
                prompt_version=prompts.PROMPT_VERSION,
                user_id=opts.user_id,
                max_tokens=self.settings.max_tokens_a,
            )
        except AIError as e:
            st = "unavailable"
            cs = (
                "timeout"
                if e.code == "AI_TIMEOUT"
                else ("schema_error" if e.code == "AI_SCHEMA_ERROR" else "error")
            )
            for exc_t, status, call_status in _STATUS_MAP:
                if isinstance(e, exc_t):
                    st, cs = status, call_status
            if isinstance(e, AIDisabled | AIBreakerOpen):
                cs = "fallback"
            ai, drugs = fallback(st, cs, str(e), e.code.lower())
            return finish(ai, drugs, deid)

        assessment, guard_events, verified = guard_assessment(res_a.parsed, pcg, low_confidence=low_conf)  # type: ignore[arg-type]
        calls.append(
            AiCallRecord(
                call_type="clinical_assessment",
                model=res_a.model,
                prompt_version=prompts.PROMPT_VERSION,
                input_hash=deid.input_hash,
                input_fields=deid.input_fields,
                output_hash=sha256_hex(res_a.raw_text),
                cache_hit=res_a.cache_hit,
                tokens_in=res_a.usage.get("prompt_tokens"),
                tokens_out=res_a.usage.get("completion_tokens"),
                cost_usd=round(res_a.cost_usd, 5),
                latency_ms=res_a.latency_ms,
                status="ok",
                validation={
                    "schema_ok": True,
                    "retries": max(res_a.attempts - 1, 0),
                    "repaired": res_a.repaired,
                    "guard_events": guard_events,
                },
                input_payload={"patient_context": deid.llm_context, "pcg_analysis": pcg_payload},
                output_raw=res_a.raw_text,
            )
        )
        ai = AiAssessmentResult(
            status="ok",
            source="llm",
            assessment=assessment,
            model=res_a.model,
            prompt_version=prompts.PROMPT_VERSION,
            numeric_verified=verified,
            guard_events=guard_events,
            low_confidence_mode=low_conf,
            cache_hit=res_a.cache_hit,
        )

        # ---------------- Call B: drug proposals (closed set from the local KB)
        drugs = await self._drug_stage(assessment, deid, opts, calls, kb_version)
        return finish(ai, drugs, deid)

    async def _drug_stage(
        self,
        assessment: ClinicalAssessment,
        deid: DeidResult,
        opts: AnalysisOptions,
        calls: list[AiCallRecord],
        kb_version: int | None,
    ) -> DrugProposalsResult:
        diff = [d.model_dump() for d in assessment.differential]
        cset: CandidateSet = build_candidates(
            self.kb, deid.safety, diff, allow_draft=self.settings.kb_allow_draft
        )
        if not cset.candidates:
            res = validate_drug_proposals(LLMDrugProposals(), cset, self.kb, strict=self.settings.dose_strict)
            res.message_uz = (
                "KB da mos (xavfsiz) dori nomzodi yo'q; shifokor mustaqil qaror qiladi."
                if not cset.note
                else f"{NO_SAFE_PROPOSAL_UZ} ({cset.note})"
            )
            return res
        safety_llm = _safety_for_llm(deid.safety)
        kb_payload = cset.to_llm()
        assert_no_pii(safety_llm)
        user_b = prompts.build_drug_user_prompt(assessment.model_dump(mode="json"), safety_llm, kb_payload)
        extra = f"kb{self.kb.version}:{sha256_hex(canonical_json(kb_payload))[:16]}"
        try:
            res_b = await self.client.complete_json(
                prompts.DRUG_SYSTEM_PROMPT,
                user_b,
                LLMDrugProposals,
                model=self.settings.model_chat,
                prompt_version=prompts.PROMPT_VERSION,
                user_id=opts.user_id,
                cache_ttl_s=self.settings.drug_cache_ttl_s,
                cache_extra=extra,
                max_tokens=self.settings.max_tokens_b,
            )
        except AIError as e:
            calls.append(
                AiCallRecord(
                    call_type="drug_proposals",
                    model=self.settings.model_chat,
                    prompt_version=prompts.PROMPT_VERSION,
                    kb_version=kb_version,
                    input_hash=sha256_hex(user_b),
                    input_fields=sorted(safety_llm),
                    status="error",
                    error=str(e)[:300],
                )
            )
            res = validate_drug_proposals(None, cset, self.kb)
            res.message_uz = "AI dori taklifi vaqtincha mavjud emas; shifokor mustaqil qaror qiladi"
            return res
        res = validate_drug_proposals(
            res_b.parsed,
            cset,
            self.kb,
            strict=self.settings.dose_strict,
            model=res_b.model,  # type: ignore[arg-type]
            prompt_version=prompts.PROMPT_VERSION,
            cache_hit=res_b.cache_hit,
        )
        calls.append(
            AiCallRecord(
                call_type="drug_proposals",
                model=res_b.model,
                prompt_version=prompts.PROMPT_VERSION,
                kb_version=kb_version,
                input_hash=sha256_hex(user_b),
                input_fields=sorted(safety_llm),
                output_hash=sha256_hex(res_b.raw_text),
                cache_hit=res_b.cache_hit,
                tokens_in=res_b.usage.get("prompt_tokens"),
                tokens_out=res_b.usage.get("completion_tokens"),
                cost_usd=round(res_b.cost_usd, 5),
                latency_ms=res_b.latency_ms,
                status="ok",
                validation={
                    "schema_ok": True,
                    "retries": max(res_b.attempts - 1, 0),
                    "repaired": res_b.repaired,
                    "guard_events": res.guard_events,
                },
                input_payload={"patient_safety": safety_llm, "kb_candidates": kb_payload},
                output_raw=res_b.raw_text,
            )
        )
        return res


_singleton: AnalysisService | None = None


def get_analysis_service() -> AnalysisService:
    """Process-wide instance (settings from env)."""
    global _singleton
    if _singleton is None:
        _singleton = AnalysisService()
    return _singleton

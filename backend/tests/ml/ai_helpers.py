"""Shared helpers for AI-layer tests. The real DeepSeek API is NEVER called: all HTTP goes
through `httpx.MockTransport`. The key below is an obvious placeholder, not a credential."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from app.services.ai.config import AISettings, default_kb_dir
from app.services.ai.kb import DrugKB

FAKE_KEY = "unit-test-placeholder-key"


def make_settings(**kw: Any) -> AISettings:
    base = dict(api_key=FAKE_KEY, backoff_s=(0.0, 0.0), kb_allow_draft=True, kb_dir=default_kb_dir())
    base.update(kw)
    return AISettings(**base)


def load_kb() -> DrugKB:
    return DrugKB.load(default_kb_dir())


def completion(content: Any, prompt_tokens: int = 1000, completion_tokens: int = 500) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(
        200,
        json={
            "id": "x",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def clinical_json(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "summary_uz": "Sistolik shovqin aniqlandi; mitral regurgitatsiya naqshiga mos.",
        "signal_interpretation_uz": "Ritm tekis, S1/S2 aniq ajratilgan.",
        "differential": [
            {
                "condition_code": "heart_failure",
                "name_uz": "Yurak yetishmovchiligi",
                "probability": 0.40,
                "supporting_findings": ["nafas qisilishi"],
                "against_findings": [],
            },
            {
                "condition_code": "mitral_regurgitation",
                "name_uz": "Mitral regurgitatsiya (MR)",
                "probability": 0.35,
                "supporting_findings": ["holosistolik timing"],
                "against_findings": [],
            },
            {
                "condition_code": "other_undetermined",
                "name_uz": "Boshqa/aniqlanmagan",
                "probability": 0.25,
                "supporting_findings": [],
                "against_findings": [],
            },
        ],
        "risk": {"level": "moderate", "rationale_uz": "Simptomatik bemor.", "red_flags": []},
        "recommended_tests": [
            {
                "test": "echo",
                "priority": "high",
                "name_uz": "Ekokardiografiya",
                "reason_uz": "Qopqoq baholash",
                "labs": [],
            }
        ],
        "missing_information_uz": ["Boshqa nuqtalar yozuvi"],
        "confidence": {"overall": 0.62, "limiting_factors": ["bitta nuqta"]},
        "reasoning_uz": "1) ... 2) ...",
        "disclaimer_uz": "AI yordamchi xulosa.",
    }
    d.update(over)
    return d


def drug_item(
    drug_id="furosemide",
    inn="furosemide",
    cls="loop_diuretic",
    dmin=20,
    dmax=40,
    unit="mg",
    freq="qd-bid",
    route="po",
    conf=0.7,
    **over: Any,
) -> dict[str, Any]:
    d = {
        "drug_id": drug_id,
        "inn": inn,
        "class": cls,
        "indication_uz": "Yurak yetishmovchiligi belgilarida ma'lumot uchun.",
        "linked_condition_codes": ["heart_failure"],
        "dose": {
            "min": dmin,
            "max": dmax,
            "unit": unit,
            "frequency": freq,
            "route": route,
            "duration_uz": "shifokor belgilaydi",
            "adjustment_applied_uz": "",
        },
        "contraindications_checked": [{"item": "anuria", "status": "clear"}],
        "interactions_checked": [],
        "allergy_check": {"status": "clear", "note_uz": ""},
        "monitoring_uz": ["LLM monitoring (e'tiborga olinmaydi)"],
        "adverse_effects_uz": ["LLM nojo'ya ta'sir"],
        "evidence_level": "guideline",
        "confidence": conf,
        "requires_doctor_approval": True,
    }
    d.update(over)
    return d


def drug_json(items: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    d = {
        "proposals": items,
        "excluded": [],
        "non_drug_measures_uz": ["Tuz va suyuqlikni cheklash"],
        "disclaimer_uz": "Ma'lumot uchun.",
    }
    d.update(over)
    return d


class MockDeepSeek:
    """Scriptable mock transport. `route(system_prompt_kind, request_json)` decides the reply."""

    def __init__(self, responder: Callable[[dict[str, Any], int], httpx.Response] | None = None):
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []
        self.responder = responder
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(request)
        self.bodies.append(body)
        assert request.url.host == "api.deepseek.com"
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"].startswith("Bearer ")
        if self.responder is None:
            raise AssertionError("no responder")
        return self.responder(body, len(self.bodies))

    @staticmethod
    def kind(body: dict[str, Any]) -> str:
        sysmsg = body["messages"][0]["content"]
        return "drug" if "klinik farmakologiya" in sysmsg else "clinical"

    @property
    def all_text(self) -> str:
        return json.dumps(self.bodies, ensure_ascii=False)


def happy_responder(drug_items: list[dict[str, Any]] | None = None, clinical: dict[str, Any] | None = None):
    def r(body: dict[str, Any], n: int) -> httpx.Response:
        if MockDeepSeek.kind(body) == "clinical":
            return completion(clinical or clinical_json())
        return completion(drug_json(drug_items if drug_items is not None else [drug_item()]))

    return r

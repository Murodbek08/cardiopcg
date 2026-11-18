"""DeepSeek client: mocked transport only (the real API is never called)."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from ai_helpers import FAKE_KEY, MockDeepSeek, clinical_json, completion, make_settings

from app.services.ai.deepseek_client import (
    AIBreakerOpen,
    AIBudgetExceeded,
    AIDisabled,
    AIHttpError,
    AIRateLimited,
    AISchemaError,
    AITimeout,
    DeepSeekClient,
    SlidingWindowLimiter,
)
from app.services.ai.schemas import ClinicalAssessment


def client_for(mock, sleeps=None, clock=None, **settings_kw):
    async def sleep(d):
        if sleeps is not None:
            sleeps.append(d)

    kw = dict(transport=mock.transport, sleep=sleep)
    if clock:
        kw["clock"] = clock
    return DeepSeekClient(make_settings(**settings_kw), **kw)


def call(c, user="u1", **kw):
    return asyncio.run(
        c.complete_json("SYS json", f"USER {kw.pop('tag', 'a')}", ClinicalAssessment, user_id=user, **kw)
    )


def ok(body, n):
    return completion(clinical_json())


def test_no_key_means_disabled_and_no_http():
    m = MockDeepSeek(ok)
    c = DeepSeekClient(make_settings(api_key=None), transport=m.transport)
    assert c.available is False
    with pytest.raises(AIDisabled):
        call(c)
    assert m.requests == []


def test_success_request_shape_and_validation():
    m = MockDeepSeek(ok)
    c = client_for(m)
    r = call(c)
    assert isinstance(r.parsed, ClinicalAssessment) and r.attempts == 1 and not r.cache_hit
    body = m.bodies[0]
    assert body["model"] == "deepseek-chat" and body["response_format"] == {"type": "json_object"}
    assert body["temperature"] <= 0.2 and body["stream"] is False
    assert m.requests[0].headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert r.usage["prompt_tokens"] == 1000 and r.cost_usd > 0
    assert sum(d.probability for d in r.parsed.differential) == pytest.approx(1.0, abs=1e-3)


def test_probabilities_are_renormalised_and_sorted():
    bad = clinical_json()
    for d, p in zip(bad["differential"], (0.2, 0.9, 0.5)):
        d["probability"] = p
    m = MockDeepSeek(lambda b, n: completion(bad))
    r = call(client_for(m))
    probs = [d.probability for d in r.parsed.differential]
    assert sum(probs) == pytest.approx(1.0, abs=1e-3) and probs == sorted(probs, reverse=True)


def test_fenced_json_is_accepted():
    m = MockDeepSeek(lambda b, n: completion("```json\n" + json.dumps(clinical_json()) + "\n```"))
    assert call(client_for(m)).attempts == 1


def test_retry_on_5xx_with_backoff():
    sleeps = []
    m = MockDeepSeek(lambda b, n: httpx.Response(503) if n == 1 else completion(clinical_json()))
    r = call(client_for(m, sleeps, backoff_s=(1.0, 3.0)))
    assert r.attempts == 2 and len(m.requests) == 2
    assert m.bodies[1]["temperature"] == 0.0
    assert sleeps and 0.5 < sleeps[0] < 1.5


def test_repair_prompt_after_invalid_json():
    m = MockDeepSeek(lambda b, n: completion("this is not json") if n == 1 else completion(clinical_json()))
    r = call(client_for(m))
    assert r.repaired is True and r.attempts == 2
    last = m.bodies[1]["messages"][-1]["content"]
    assert "Oldingi javob yaroqsiz" in last


def test_schema_error_after_retries_raises():
    bad = clinical_json()
    bad["extra_key"] = 1  # extra=forbid
    m = MockDeepSeek(lambda b, n: completion(bad))
    with pytest.raises(AISchemaError):
        call(client_for(m))
    assert len(m.requests) == 2  # attempt + one repair, then stop


def test_enum_violation_is_a_schema_error():
    bad = clinical_json()
    bad["differential"][0]["condition_code"] = "made_up_disease"
    m = MockDeepSeek(lambda b, n: completion(bad))
    with pytest.raises(AISchemaError):
        call(client_for(m))


def test_timeout_raises_ait_timeout():
    def boom(body, n):
        raise httpx.ReadTimeout("slow")

    m = MockDeepSeek(boom)
    with pytest.raises(AITimeout):
        call(client_for(m))
    assert len(m.requests) == 2


def test_429_honours_retry_after():
    sleeps = []
    m = MockDeepSeek(
        lambda b, n: (
            httpx.Response(429, headers={"Retry-After": "2"}) if n == 1 else completion(clinical_json())
        )
    )
    r = call(client_for(m, sleeps))
    assert r.attempts == 2 and sleeps[0] == 2.0


def test_4xx_is_not_retried_and_does_not_leak_key():
    m = MockDeepSeek(lambda b, n: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(AIHttpError) as e:
        call(client_for(m))
    assert len(m.requests) == 1
    assert FAKE_KEY not in str(e.value)


def test_cache_hit_skips_http_and_does_not_count_for_rate_limit():
    m = MockDeepSeek(ok)
    c = client_for(m, rate_limit_per_user_per_hour=1)
    a = call(c)
    b = call(c)  # identical prompt -> cache; would be rate limited otherwise
    assert b.cache_hit and len(m.requests) == 1 and b.parsed == a.parsed
    with pytest.raises(AIRateLimited):
        call(c, tag="different")


def test_cache_key_depends_on_model_prompt_version_and_extra():
    c = client_for(MockDeepSeek(ok))
    k = c.cache_key("deepseek-chat", "v1", "s", "u")
    assert k != c.cache_key("deepseek-reasoner", "v1", "s", "u")
    assert k != c.cache_key("deepseek-chat", "v2", "s", "u")
    assert k != c.cache_key("deepseek-chat", "v1", "s", "u", extra="kb2")


def test_per_user_rate_limit_is_per_user():
    m = MockDeepSeek(ok)
    c = client_for(m, rate_limit_per_user_per_hour=1)
    call(c, user="a", tag="1")
    with pytest.raises(AIRateLimited):
        call(c, user="a", tag="2")
    call(c, user="b", tag="3")


def test_sliding_window_expires():
    t = [0.0]
    lim = SlidingWindowLimiter(2, 10.0, clock=lambda: t[0])

    async def go():
        r = [await lim.allow("k"), await lim.allow("k"), await lim.allow("k")]
        t[0] = 11.0
        return r + [await lim.allow("k")]

    assert asyncio.run(go()) == [True, True, False, True]


def test_daily_budget_blocks_further_calls():
    m = MockDeepSeek(lambda b, n: completion(clinical_json(), 2_000_000, 1_000_000))
    c = client_for(m, daily_budget_usd=1.0)
    call(c, tag="1")  # ~$1.64 spent
    with pytest.raises(AIBudgetExceeded):
        call(c, tag="2")
    assert len(m.requests) == 1


def test_circuit_breaker_opens_and_recovers():
    t = [0.0]
    state = {"fail": True}
    m = MockDeepSeek(lambda b, n: httpx.Response(500) if state["fail"] else completion(clinical_json()))
    c = client_for(m, clock=lambda: t[0], breaker_threshold=2, breaker_open_s=60.0)
    for tag in ("1", "2"):
        with pytest.raises(AIHttpError):
            call(c, tag=tag)
    n_before = len(m.requests)
    with pytest.raises(AIBreakerOpen):
        call(c, tag="3")
    assert len(m.requests) == n_before  # fail fast, no HTTP
    t[0] = 61.0
    state["fail"] = False
    assert call(c, tag="4").attempts == 1


def test_host_allow_list_blocks_ssrf():
    with pytest.raises(ValueError):
        DeepSeekClient(make_settings(base_url="https://evil.example.com"))
    with pytest.raises(ValueError):
        DeepSeekClient(make_settings(base_url="http://169.254.169.254"))
    DeepSeekClient(make_settings(base_url="https://api.deepseek.com"))


def test_reasoner_model_skips_json_mode_and_temperature():
    m = MockDeepSeek(ok)
    call(client_for(m), model="deepseek-reasoner")
    b = m.bodies[0]
    assert b["model"] == "deepseek-reasoner" and "response_format" not in b and "temperature" not in b


def test_secret_never_in_repr_or_logs(caplog):
    s = make_settings()
    assert FAKE_KEY not in repr(s) and FAKE_KEY not in str(s)
    m = MockDeepSeek(lambda b, n: httpx.Response(500))
    with caplog.at_level(logging.DEBUG), pytest.raises(AIHttpError) as e:
        call(client_for(m))
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in str(e.value)


def test_settings_from_env(monkeypatch):
    from app.services.ai.config import AISettings

    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env-placeholder")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/")
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "2.5")
    s = AISettings.from_env()
    assert (
        s.api_key == "from-env-placeholder"
        and s.base_url == "https://api.deepseek.com"
        and s.daily_budget_usd == 2.5
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert AISettings.from_env().api_key is None

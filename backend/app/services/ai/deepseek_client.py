"""DeepSeek (OpenAI-compatible) JSON client over httpx (doc 02 section 12).

Features: host allow-list (SSRF), timeout, retry with jitter + Retry-After, one repair attempt,
Pydantic-validated structured output, response cache, per-user sliding-window rate limit,
daily USD budget, circuit breaker, concurrency semaphore.

The API key comes from settings (env `DEEPSEEK_API_KEY`) and is only ever placed in the
Authorization header of the outgoing request. It is never logged and never part of an error text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from .config import AISettings
from .deidentify import canonical_json, sha256_hex

log = logging.getLogger("cardiopcg.ai")
T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- errors


class AIError(Exception):
    code = "AI_UNAVAILABLE"
    http_status = 503

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)


class AIDisabled(AIError):
    code = "AI_DISABLED"


class AIRateLimited(AIError):
    code = "AI_RATE_LIMIT"
    http_status = 429


class AIBudgetExceeded(AIError):
    code = "AI_BUDGET_EXCEEDED"
    http_status = 429


class AIBreakerOpen(AIError):
    code = "AI_CIRCUIT_OPEN"


class AITimeout(AIError):
    code = "AI_TIMEOUT"


class AISchemaError(AIError):
    code = "AI_SCHEMA_ERROR"


class AIHttpError(AIError):
    code = "AI_HTTP_ERROR"


# --------------------------------------------------------------------------- pluggable pieces


class AICache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...


class InMemoryTTLCache:
    def __init__(self, max_items: int = 512, clock: Callable[[], float] = time.monotonic):
        self._d: dict[str, tuple[float, str]] = {}
        self._max = max_items
        self._clock = clock

    async def get(self, key: str) -> str | None:
        v = self._d.get(key)
        if not v:
            return None
        if v[0] < self._clock():
            self._d.pop(key, None)
            return None
        return v[1]

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        if len(self._d) >= self._max:
            self._d.pop(next(iter(self._d)))
        self._d[key] = (self._clock() + ttl_s, value)


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool: ...


class SlidingWindowLimiter:
    """Per-user sliding window (doc 12.6: 30 calls / hour). Replace with a Redis one in production."""

    def __init__(self, limit: int, window_s: float = 3600.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self._clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str) -> bool:
        now = self._clock()
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


class DailyBudget:
    def __init__(self, limit_usd: float):
        self.limit = limit_usd
        self._day = ""
        self.spent = 0.0

    def _roll(self) -> None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        if day != self._day:
            self._day, self.spent = day, 0.0

    def exceeded(self) -> bool:
        self._roll()
        return self.spent >= self.limit

    def add(self, usd: float) -> None:
        self._roll()
        self.spent += usd


@dataclass
class ClientResult:
    parsed: BaseModel
    raw_text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    attempts: int = 0
    repaired: bool = False
    input_hash: str = ""
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- client

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def _extract_json(text: str) -> Any:
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            return json.loads(t[a : b + 1])
        raise


class DeepSeekClient:
    def __init__(
        self,
        settings: AISettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: AICache | None = None,
        rate_limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.s = settings or AISettings.from_env()
        host = urlparse(self.s.base_url).hostname or ""
        if host not in self.s.allowed_hosts:  # SSRF allow-list (doc 21)
            raise ValueError(f"DeepSeek base URL host not allowed: {host!r}")
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self.cache: AICache = cache or InMemoryTTLCache()
        self.limiter: RateLimiter = rate_limiter or SlidingWindowLimiter(self.s.rate_limit_per_user_per_hour)
        self.budget = DailyBudget(self.s.daily_budget_usd)
        self._sleep = sleep
        self._clock = clock
        self._sem = asyncio.Semaphore(self.s.max_concurrency)
        self._fail_streak = 0
        self._open_until = 0.0

    # -- state
    @property
    def available(self) -> bool:
        return bool(self.s.api_key)

    def breaker_open(self) -> bool:
        return self._clock() < self._open_until

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.s.base_url,
                timeout=httpx.Timeout(self.s.timeout_s),
                transport=self._transport,
                follow_redirects=False,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _cost(self, usage: dict[str, int]) -> float:
        return (
            usage.get("prompt_tokens", 0) * self.s.price_in_per_m
            + usage.get("completion_tokens", 0) * self.s.price_out_per_m
        ) / 1e6

    def cache_key(self, model: str, prompt_version: str, system: str, user: str, extra: str = "") -> str:
        return sha256_hex(
            canonical_json({"m": model, "pv": prompt_version, "s": sha256_hex(system), "u": user, "x": extra})
        )

    # -- main entry
    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        model: str | None = None,
        prompt_version: str = "v1",
        user_id: str | None = None,
        cache_ttl_s: int | None = None,
        cache_extra: str = "",
        max_tokens: int = 2500,
        use_cache: bool = True,
    ) -> ClientResult:
        if not self.available:
            raise AIDisabled("DEEPSEEK_API_KEY not configured")
        model = model or self.s.model_chat
        ck = self.cache_key(model, prompt_version, system, user, cache_extra)
        t0 = self._clock()

        if use_cache:
            hit = await self.cache.get(ck)
            if hit is not None:
                try:
                    parsed = schema.model_validate(json.loads(hit))
                    return ClientResult(parsed, hit, model, cache_hit=True, input_hash=ck, latency_ms=0)
                except (ValueError, ValidationError):
                    pass  # corrupt cache entry: ignore

        if self.breaker_open():
            raise AIBreakerOpen("circuit breaker open")
        if self.budget.exceeded():
            raise AIBudgetExceeded("daily AI budget exceeded")
        if user_id is not None and not await self.limiter.allow(user_id):
            raise AIRateLimited("per-user AI rate limit reached")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        attempts = max(1, self.s.max_retries)
        errors: list[str] = []
        repaired = False
        last_exc: AIError | None = None
        async with self._sem:
            for attempt in range(1, attempts + 1):
                if self._clock() - t0 > self.s.total_timeout_s:
                    last_exc = AITimeout("total timeout exceeded")
                    break
                temp = 0.2 if attempt == 1 else 0.0
                try:
                    text, usage = await self._post(model, messages, temp, max_tokens)
                except AIRateLimited as e:  # HTTP 429 from provider
                    last_exc = e
                    errors.append("http_429")
                    await self._backoff(attempt, getattr(e, "retry_after", None))
                    continue
                except _NoRetry as e:
                    last_exc = e
                    errors.append(str(e))
                    break
                except AIError as e:
                    last_exc = e
                    errors.append(e.code)
                    await self._backoff(attempt)
                    continue
                try:
                    data = _extract_json(text)
                    parsed = schema.model_validate(data)
                except (ValueError, ValidationError) as e:
                    err = _short_err(e)
                    errors.append(f"schema:{err}")
                    last_exc = AISchemaError(err)
                    messages = messages[:2] + [
                        {"role": "assistant", "content": text[:4000]},
                        {
                            "role": "user",
                            "content": f"Oldingi javob yaroqsiz: {err}. Faqat sxemaga mos bitta JSON obyekt (json) qaytar.",
                        },
                    ]
                    repaired = True
                    await self._backoff(attempt)
                    continue
                # success
                self._fail_streak = 0
                cost = self._cost(usage)
                self.budget.add(cost)
                canon = json.dumps(parsed.model_dump(mode="json", by_alias=True), ensure_ascii=False)
                if use_cache:
                    await self.cache.set(ck, canon, cache_ttl_s or self.s.cache_ttl_s)
                return ClientResult(
                    parsed=parsed,
                    raw_text=text,
                    model=model,
                    usage=usage,
                    cost_usd=cost,
                    latency_ms=int((self._clock() - t0) * 1000),
                    attempts=attempt,
                    repaired=repaired,
                    input_hash=ck,
                    errors=errors,
                )
        # all attempts failed
        self._fail_streak += 1
        if self._fail_streak >= self.s.breaker_threshold:
            self._open_until = self._clock() + self.s.breaker_open_s
            self._fail_streak = 0
            log.warning("ai.breaker_open", extra={"for_s": self.s.breaker_open_s})
        assert last_exc is not None
        last_exc.args = (f"{last_exc} (errors={errors})",)
        raise last_exc

    async def _backoff(self, attempt: int, retry_after: float | None = None) -> None:
        if attempt >= max(1, self.s.max_retries):
            return
        base = self.s.backoff_s[min(attempt - 1, len(self.s.backoff_s) - 1)]
        delay = min(retry_after, 30.0) if retry_after else base * (0.8 + 0.4 * random.random())
        await self._sleep(delay)

    async def _post(
        self, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> tuple[str, dict[str, int]]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if "reasoner" not in model:  # reasoner ignores temperature / JSON mode (doc 12.2 warning)
            body["response_format"] = {"type": "json_object"}
            body["temperature"] = min(temperature, 0.2)
            body["top_p"] = 0.9
        headers = {"Authorization": f"Bearer {self.s.api_key}", "Content-Type": "application/json"}
        try:
            r = await self._client().post("/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise AITimeout("request timeout") from e
        except httpx.HTTPError as e:
            raise AIHttpError(f"transport error: {type(e).__name__}") from e
        if r.status_code == 429:
            exc = AIRateLimited("provider 429")
            try:
                exc.retry_after = float(r.headers.get("Retry-After", ""))  # type: ignore[attr-defined]
            except ValueError:
                exc.retry_after = None  # type: ignore[attr-defined]
            raise exc
        if r.status_code >= 500:
            raise AIHttpError(f"provider {r.status_code}")
        if r.status_code >= 400:
            # 4xx other than 429 will not heal by retrying; do not echo the body (may contain the request)
            raise _NoRetry(f"provider {r.status_code}")
        try:
            j = r.json()
            text = j["choices"][0]["message"]["content"] or ""
            usage = j.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise AIHttpError("malformed provider response") from e
        return text, {k: int(v) for k, v in usage.items() if isinstance(v, (int, float))}


class _NoRetry(AIHttpError):
    pass


def _short_err(e: Exception) -> str:
    if isinstance(e, ValidationError):
        errs = e.errors()[:3]
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in errs)[:300]
    return str(e)[:300]

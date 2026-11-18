"""AI layer settings, read from environment (doc 02 section 12.1).

The API key is read ONLY from the `DEEPSEEK_API_KEY` env var, never from code or files, and is
never logged or included in repr().
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def default_kb_dir() -> Path:
    # backend/app/services/ai/config.py -> backend/data/drugs
    return Path(__file__).resolve().parents[3] / "data" / "drugs"


@dataclass
class AISettings:
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.deepseek.com"
    model_chat: str = "deepseek-chat"
    model_reasoner: str = "deepseek-reasoner"
    timeout_s: float = 45.0
    total_timeout_s: float = 70.0
    max_retries: int = 2  # attempt 1 + attempt 2 (+ one repair prompt)
    backoff_s: tuple[float, ...] = (1.0, 3.0)
    daily_budget_usd: float = 5.0
    rate_limit_per_user_per_hour: int = 30
    max_concurrency: int = 4
    breaker_threshold: int = 5
    breaker_open_s: float = 60.0
    cache_ttl_s: int = 7 * 24 * 3600
    drug_cache_ttl_s: int = 24 * 3600
    # approximate list prices (USD per 1M tokens); only used for the budget guard / audit estimate
    price_in_per_m: float = 0.27
    price_out_per_m: float = 1.10
    allowed_hosts: tuple[str, ...] = ("api.deepseek.com",)
    max_tokens_a: int = 2500
    max_tokens_b: int = 2500
    use_reasoner_on_disagree: bool = False
    kb_dir: Path = field(default_factory=default_kb_dir)
    kb_allow_draft: bool = False  # doc 15: only kb_status=reviewed may reach the LLM/doctor
    dose_strict: bool = True  # out-of-range LLM dose -> reject (False: clamp)
    min_sqi_for_ai: float = 0.50  # doc 16: poor/unusable -> LLM not called

    @classmethod
    def from_env(cls) -> AISettings:
        hosts = os.environ.get("DEEPSEEK_ALLOWED_HOSTS", "api.deepseek.com")
        return cls(
            api_key=(os.environ.get("DEEPSEEK_API_KEY") or None),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model_chat=os.environ.get("DEEPSEEK_MODEL_CHAT", "deepseek-chat"),
            model_reasoner=os.environ.get("DEEPSEEK_MODEL_REASONER", "deepseek-reasoner"),
            timeout_s=_f("DEEPSEEK_TIMEOUT_S", 45.0),
            max_retries=_i("DEEPSEEK_MAX_RETRIES", 2),
            daily_budget_usd=_f("AI_DAILY_BUDGET_USD", 5.0),
            rate_limit_per_user_per_hour=_i("AI_RATE_LIMIT_PER_USER_PER_HOUR", 30),
            allowed_hosts=tuple(h.strip() for h in hosts.split(",") if h.strip()),
            price_in_per_m=_f("AI_PRICE_IN_PER_M", 0.27),
            price_out_per_m=_f("AI_PRICE_OUT_PER_M", 1.10),
            use_reasoner_on_disagree=_b("AI_USE_REASONER_ON_DISAGREE", False),
            kb_dir=Path(os.environ.get("CARDIOPCG_KB_DIR") or default_kb_dir()),
            kb_allow_draft=_b("CARDIOPCG_KB_ALLOW_DRAFT", False),
            dose_strict=_b("CARDIOPCG_DOSE_STRICT", True),
        )

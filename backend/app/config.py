"""Application settings loaded from environment (pydantic-settings). No secrets in code."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cloudflare published ranges (verify periodically: https://www.cloudflare.com/ips/)
_DEFAULT_TRUSTED_PROXIES = (
    "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,"
    "173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,"
    "108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,"
    "162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22"
)

_INSECURE_MARKERS = ("change", "placeholder", "secret", "example", "<")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_version: str = "1.0.0"
    git_commit: str = "unknown"
    public_url: str = "http://localhost:5173"
    allowed_origins: str = "http://localhost:5173"
    allowed_hosts: str = "*"
    log_level: str = "info"
    docs_enabled: bool = False

    database_url: str = "postgresql+asyncpg://cardiopcg:cardiopcg@localhost:5432/cardiopcg"
    db_null_pool: bool = False
    db_pool_size: int = 10

    redis_url: str = ""  # empty -> in-process fallback (dev/tests only; not for multi-worker prod)
    celery_broker_url: str = ""
    job_runner: Literal["celery", "inline", "none"] = "inline"

    # storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./storage"
    s3_endpoint: str = ""
    s3_bucket_audio: str = "pcg-audio"
    s3_bucket_reports: str = "pcg-reports"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    # auth
    jwt_secret: str = "dev-only-jwt-secret-not-for-production-use-0123456789"
    jwt_alg: Literal["HS256"] = "HS256"
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 7
    session_max_days: int = 30
    jwt_issuer: str = "cardiopcg"
    jwt_audience: str = "cardiopcg-web"
    cookie_secure: bool = False
    cookie_samesite: Literal["strict", "lax", "none"] = "strict"
    password_pepper: str = ""
    pii_encryption_key: str = ""  # base64 of 32 bytes (AES-256-GCM)
    pii_hash_pepper: str = ""

    # rate limiting
    rate_limit_enabled: bool = True
    rate_limit_login_ip: int = 10
    rate_limit_login_user: int = 5
    rate_limit_refresh_ip: int = 30
    rate_limit_api_user: int = 300
    rate_limit_upload_user: int = 30
    rate_limit_ai_user: int = 20
    rate_limit_export_user: int = 10
    rate_limit_password: int = 5
    trusted_proxies: str = _DEFAULT_TRUSTED_PROXIES

    # uploads / antivirus
    max_json_body_bytes: int = 1_000_000
    clamav_host: str = ""
    clamav_port: int = 3310
    clamav_required: bool = False

    # analysis integration
    analysis_service_impl: str = (
        "app.services.ai_adapter:build"  # dotted "pkg.module:factory" returning an AnalysisService
    )
    analysis_retry_backoff_sec: str = "10,30,90"
    analytics_cache_ttl: int = 60
    csv_sync_max_rows: int = 10000

    deepseek_api_key: str = ""  # consumed by app/services/ai only; never logged

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def hosts(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"

    @property
    def backoff_schedule(self) -> list[float]:
        return [float(x) for x in self.analysis_retry_backoff_sec.split(",") if x.strip()]

    @property
    def aes_key(self) -> bytes:
        if self.pii_encryption_key:
            raw = base64.b64decode(self.pii_encryption_key)
            if len(raw) != 32:
                raise ValueError("PII_ENCRYPTION_KEY must be base64 of 32 bytes")
            return raw
        return hashlib.sha256(b"pii-enc|" + self.jwt_secret.encode()).digest()

    @property
    def hash_key(self) -> bytes:
        return (self.pii_hash_pepper or "pii-hash|" + self.jwt_secret).encode()

    @model_validator(mode="after")
    def _prod_guard(self) -> Settings:
        if self.app_env == "production":
            problems = []
            if (
                len(self.jwt_secret) < 32
                or any(m in self.jwt_secret.lower() for m in _INSECURE_MARKERS)
                or self.jwt_secret.startswith("dev-only")
            ):
                problems.append("JWT_SECRET is missing/weak")
            if not self.pii_encryption_key:
                problems.append("PII_ENCRYPTION_KEY is required")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()

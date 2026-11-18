"""structlog JSON logging; secrets and PHI keys masked."""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.context import get_request_info

_MASK_KEYS = {
    "password",
    "new_password",
    "current_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "secret",
    "api_key",
    "deepseek_api_key",
    "national_id",
    "phone",
    "first_name",
    "last_name",
    "address",
}


def _mask(_, __, event_dict):
    for k in list(event_dict):
        if k.lower() in _MASK_KEYS:
            event_dict[k] = "***"
    return event_dict


def _ctx(_, __, event_dict):
    info = get_request_info()
    if info.request_id:
        event_dict.setdefault("request_id", info.request_id)
    if info.user_id:
        event_dict.setdefault("user_id", info.user_id)
        event_dict.setdefault("role", info.role)
    return event_dict


def configure_logging(level: str = "info") -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=lvl, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _ctx,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mask,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        cache_logger_on_first_use=False,
    )

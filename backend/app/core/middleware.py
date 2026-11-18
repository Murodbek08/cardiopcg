"""Pure-ASGI middleware: request id/context, client IP, security headers, JSON body size limit."""

from __future__ import annotations

import ipaddress
import time
from collections import deque

import orjson
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.core.context import RequestInfo, reset_request_info, set_request_info
from app.core.errors import AppError
from app.db.base import new_id

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"permissions-policy", b"microphone=(self), camera=()"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]

# rolling latency samples (seconds) for /analytics/admin/system p50/p95
LATENCIES: deque[float] = deque(maxlen=5000)

_nets_cache: tuple[str, list] | None = None


def _trusted_nets() -> list:
    global _nets_cache
    raw = get_settings().trusted_proxies
    if _nets_cache is None or _nets_cache[0] != raw:
        nets = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                nets.append(ipaddress.ip_network(part, strict=False))
        _nets_cache = (raw, nets)
    return _nets_cache[1]


def client_ip(scope: Scope, headers: dict[bytes, bytes]) -> str | None:
    peer = (scope.get("client") or (None, None))[0]
    if peer is None:
        return None
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return None
    if any(peer_ip in n for n in _trusted_nets()):
        cf = headers.get(b"cf-connecting-ip") or headers.get(b"x-real-ip")
        if cf:
            try:
                return str(ipaddress.ip_address(cf.decode().strip()))
            except ValueError:
                pass
    return str(peer_ip)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        rid = headers.get(b"x-request-id", b"").decode()[:40] or str(new_id()).replace("-", "")[:26].upper()
        info = RequestInfo(
            request_id=rid,
            ip=client_ip(scope, headers),
            user_agent=headers.get(b"user-agent", b"").decode(errors="replace")[:300] or None,
            method=scope.get("method"),
            path=scope.get("path"),
        )
        token = set_request_info(info)
        scope.setdefault("state", {})["request_info"] = info
        started = time.perf_counter()
        is_http = scope["type"] == "http"

        # JSON body size limit (multipart uploads are limited in the upload service)
        limit = get_settings().max_json_body_bytes
        ctype = headers.get(b"content-type", b"")
        enforce = (
            is_http
            and not ctype.startswith(b"multipart/")
            and scope.get("method") in ("POST", "PUT", "PATCH")
        )
        if enforce:
            cl = headers.get(b"content-length")
            if cl and cl.isdigit() and int(cl) > limit:
                await self._reject_413(send, rid)
                reset_request_info(token)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if enforce and msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise AppError(413, "FILE_TOO_LARGE", "So'rov hajmi juda katta")
            return msg

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                hdrs.append((b"x-request-id", rid.encode()))
                hdrs.extend(_SECURITY_HEADERS)
                if not any(k.lower() == b"cache-control" for k, _ in hdrs):
                    hdrs.append((b"cache-control", b"no-store"))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, limited_receive if enforce else receive, send_wrapper if is_http else send)
        finally:
            if is_http:
                LATENCIES.append(time.perf_counter() - started)
            reset_request_info(token)

    @staticmethod
    async def _reject_413(send: Send, rid: str) -> None:
        body = orjson.dumps(
            {"error": {"code": "FILE_TOO_LARGE", "message": "So'rov hajmi juda katta", "request_id": rid}}
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"x-request-id", rid.encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

"""ClamAV (clamd INSTREAM) scanner. Without a configured host the scan is reported as 'skipped'."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

from app.config import get_settings
from app.core.errors import AppError

CHUNK = 64 * 1024


async def scan_file(path: Path, timeout: float = 5.0) -> str:
    """Returns clean | infected | skipped | error. Raises 503 when CLAMAV_REQUIRED and the scanner is down."""
    s = get_settings()
    if not s.clamav_host:
        if s.clamav_required:
            raise AppError(503, "SERVICE_UNAVAILABLE", "Antivirus xizmati sozlanmagan")
        return "skipped"
    try:
        return await asyncio.wait_for(_instream(path, s.clamav_host, s.clamav_port), timeout)
    except Exception:
        if s.clamav_required:
            raise AppError(503, "SERVICE_UNAVAILABLE", "Antivirus xizmati javob bermadi")
        return "error"


async def _instream(path: Path, host: str, port: int) -> str:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(b"zINSTREAM\0")
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK):
                writer.write(struct.pack("!I", len(chunk)) + chunk)
                await writer.drain()
        writer.write(struct.pack("!I", 0))
        await writer.drain()
        resp = (await reader.read(1024)).decode(errors="replace").strip("\0\n ")
    finally:
        writer.close()
    if resp.endswith("OK"):
        return "clean"
    if "FOUND" in resp:
        return "infected"
    return "error"

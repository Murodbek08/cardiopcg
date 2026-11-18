"""Storage abstraction: S3/MinIO (boto3) or local disk (dev fallback). DB stores keys only."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

import orjson

from app.config import Settings, get_settings
from app.core.errors import AppError

CHUNK = 1024 * 256


class Storage(Protocol):
    async def put_file(self, key: str, path: Path, content_type: str) -> None: ...
    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get_bytes(self, key: str) -> bytes: ...
    async def download_to(self, key: str, path: Path) -> None: ...
    def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]: ...
    async def size(self, key: str) -> int: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...
    async def ping(self) -> bool: ...


def _safe_key(key: str) -> str:
    if key.startswith("/") or ".." in key.split("/") or "\\" in key or "\x00" in key:
        raise ValueError("unsafe storage key")
    return key


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / _safe_key(key)).resolve()
        if self.root not in p.parents:
            raise ValueError("unsafe storage key")
        return p

    async def put_file(self, key: str, path: Path, content_type: str) -> None:
        def _do() -> None:
            dst = self._p(key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".part")
            with open(path, "rb") as fi, open(tmp, "wb") as fo:
                while chunk := fi.read(CHUNK):
                    fo.write(chunk)
            tmp.replace(dst)

        await asyncio.to_thread(_do)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        def _do() -> None:
            dst = self._p(key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dst)

        await asyncio.to_thread(_do)

    async def get_bytes(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._p(key).read_bytes)
        except FileNotFoundError:
            raise AppError(404, "NOT_FOUND", "Fayl topilmadi")

    async def download_to(self, key: str, path: Path) -> None:
        data = await self.get_bytes(key)
        await asyncio.to_thread(path.write_bytes, data)

    async def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        p = self._p(key)
        remaining = end - start + 1
        with open(p, "rb") as f:
            f.seek(start)
            while remaining > 0:
                chunk = await asyncio.to_thread(f.read, min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    async def size(self, key: str) -> int:
        try:
            return (await asyncio.to_thread(self._p(key).stat)).st_size
        except FileNotFoundError:
            raise AppError(404, "NOT_FOUND", "Fayl topilmadi")

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._p(key).exists)

    async def delete(self, key: str) -> None:
        def _do() -> None:
            with contextlib.suppress(FileNotFoundError):
                self._p(key).unlink()

        await asyncio.to_thread(_do)

    async def ping(self) -> bool:
        return self.root.exists()


class S3Storage:
    def __init__(self, s: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.audio_bucket = s.s3_bucket_audio
        self.reports_bucket = s.s3_bucket_reports
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint or None,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
            region_name=s.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _b(self, key: str) -> str:
        return self.reports_bucket if key.startswith(("exports/", "reports/")) else self.audio_bucket

    async def ensure_buckets(self) -> None:
        def _do() -> None:
            for b in {self.audio_bucket, self.reports_bucket}:
                try:
                    self.client.head_bucket(Bucket=b)
                except Exception:
                    self.client.create_bucket(Bucket=b)

        await asyncio.to_thread(_do)

    async def put_file(self, key: str, path: Path, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.upload_file,
            str(path),
            self._b(key),
            _safe_key(key),
            {"ContentType": content_type},
        )

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self._b(key),
            Key=_safe_key(key),
            Body=data,
            ContentType=content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        def _do() -> bytes:
            try:
                return self.client.get_object(Bucket=self._b(key), Key=_safe_key(key))["Body"].read()
            except self.client.exceptions.NoSuchKey:
                raise AppError(404, "NOT_FOUND", "Fayl topilmadi")

        return await asyncio.to_thread(_do)

    async def download_to(self, key: str, path: Path) -> None:
        await asyncio.to_thread(self.client.download_file, self._b(key), _safe_key(key), str(path))

    async def iter_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        obj = await asyncio.to_thread(
            self.client.get_object, Bucket=self._b(key), Key=_safe_key(key), Range=f"bytes={start}-{end}"
        )
        body = obj["Body"]
        while True:
            chunk = await asyncio.to_thread(body.read, CHUNK)
            if not chunk:
                break
            yield chunk

    async def size(self, key: str) -> int:
        def _do() -> int:
            try:
                return int(self.client.head_object(Bucket=self._b(key), Key=_safe_key(key))["ContentLength"])
            except Exception:
                raise AppError(404, "NOT_FOUND", "Fayl topilmadi")

        return await asyncio.to_thread(_do)

    async def exists(self, key: str) -> bool:
        try:
            await self.size(key)
            return True
        except AppError:
            return False

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self._b(key), Key=_safe_key(key))

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.audio_bucket)
            return True
        except Exception:
            return False


_storage: Storage | None = None


def init_storage(settings: Settings | None = None) -> Storage:
    global _storage
    s = settings or get_settings()
    _storage = S3Storage(s) if s.storage_backend == "s3" else LocalStorage(s.storage_local_dir)
    return _storage


def get_storage() -> Storage:
    if _storage is None:
        init_storage()
    assert _storage is not None
    return _storage


def set_storage(storage: Storage | None) -> None:
    global _storage
    _storage = storage


# ---- signed download tokens (used for export files; HMAC, 15 min) ----
def sign_download(key: str, filename: str, content_type: str, ttl: int = 900) -> str:
    payload = orjson.dumps({"k": key, "f": filename, "t": content_type, "e": int(time.time()) + ttl})
    sig = hmac.new(get_settings().hash_key, b"dl|" + payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def verify_download(token: str) -> dict:
    try:
        p, s = token.split(".")
        payload = base64.urlsafe_b64decode(p.encode())
        sig = base64.urlsafe_b64decode(s.encode())
        expected = hmac.new(get_settings().hash_key, b"dl|" + payload, hashlib.sha256).digest()
        data = orjson.loads(payload)
    except Exception:
        raise AppError(403, "FORBIDDEN", "Havola yaroqsiz")
    if not hmac.compare_digest(sig, expected) or data["e"] < time.time():
        raise AppError(403, "FORBIDDEN", "Havola yaroqsiz yoki muddati tugagan")
    return data

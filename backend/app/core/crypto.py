"""PII protection: AES-256-GCM field encryption + HMAC-SHA256 lookup hash."""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def encrypt_pii(plaintext: str) -> bytes:
    key = get_settings().aes_key
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), b"pii-v1")
    return b"\x01" + nonce + ct


def decrypt_pii(blob: bytes) -> str:
    key = get_settings().aes_key
    if blob[:1] != b"\x01":
        raise ValueError("unknown PII blob version")
    nonce, ct = blob[1:13], blob[13:]
    return AESGCM(key).decrypt(nonce, ct, b"pii-v1").decode()


def hmac_hash(value: str) -> str:
    return hmac.new(get_settings().hash_key, value.encode(), hashlib.sha256).hexdigest()


def mask_national_id(value: str | None) -> str | None:
    if not value:
        return None
    return "****"

"""Authenticated secret storage; key generation belongs only to initialization."""

import base64
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def load_key(path: Path) -> bytes:
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("master key must contain exactly 32 bytes")
    return key


def encrypt(value: str, key: bytes) -> str:
    nonce = secrets.token_bytes(12)
    return base64.urlsafe_b64encode(
        nonce + AESGCM(key).encrypt(nonce, value.encode(), None)
    ).decode()


def decrypt(value: str, key: bytes) -> str:
    try:
        raw = base64.urlsafe_b64decode(value.encode())
        return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()
    except Exception:
        raise ValueError("encrypted data cannot be read") from None

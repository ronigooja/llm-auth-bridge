import base64
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def load_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("master key must contain exactly 32 bytes")
    return key

def encrypt(value: str, key: bytes) -> str:
    nonce = secrets.token_bytes(12)
    return base64.urlsafe_b64encode(nonce + AESGCM(key).encrypt(nonce, value.encode(), None)).decode()

def decrypt(value: str, key: bytes) -> str:
    raw = base64.urlsafe_b64decode(value.encode())
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


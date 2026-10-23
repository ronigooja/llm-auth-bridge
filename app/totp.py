"""RFC 6238 TOTP; secrets never appear in validation errors."""
import base64
import hashlib
import hmac
import re
import struct
import time


class TOTPError(ValueError):
    pass


def generate_code(secret: str, at: float | None = None, *, period: int = 30, digits: int = 6) -> str:
    if period <= 0 or digits not in (6, 8):
        raise TOTPError("Invalid TOTP parameters")
    try:
        normalized = re.sub(r"\s", "", secret).upper().rstrip("=")
        if not normalized or not re.fullmatch(r"[A-Z2-7]+", normalized):
            raise ValueError
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8))
        instant = time.time() if at is None else at
        if instant < 0:
            raise ValueError
        digest = hmac.new(key, struct.pack(">Q", int(instant // period)), hashlib.sha1).digest()
        offset = digest[-1] & 15
        value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
        return str(value % 10 ** digits).zfill(digits)
    except (ValueError, TypeError, OverflowError, struct.error):
        raise TOTPError("Invalid TOTP secret") from None


def seconds_remaining(at: float | None = None, period: int = 30) -> float:
    instant = time.time() if at is None else at
    return period - instant % period

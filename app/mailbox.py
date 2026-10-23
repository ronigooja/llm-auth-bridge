"""Conservative mailbox primitives. Unknown mailbox UIs require human review."""

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit


class MailboxError(ValueError):
    pass


def validate_mailbox_url(url: str, *, allow_http: bool = False) -> str:
    """Reject credentials, local networks, and any DNS answer that is not global.

    Call for every navigation/redirect in any future mailbox adapter. DNS checks
    alone are not a DNS-rebinding defense; automatic mailbox adapters must pin
    the checked address or enforce egress filtering before being enabled.
    """
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in (("https", "http") if allow_http else ("https",)):
            raise ValueError
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        answers = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        if not answers or any(
            not ipaddress.ip_address(a[4][0]).is_global for a in answers
        ):
            raise ValueError
    except (ValueError, OSError, TypeError):
        raise MailboxError(
            "Mailbox URL must resolve only to public addresses over an allowed protocol"
        ) from None
    return url


@dataclass(frozen=True)
class Message:
    id: str
    sender: str
    recipient: str
    purpose: str
    timestamp: float
    code: str


def select_code(
    messages: list[Message],
    *,
    baseline_ids: set[str],
    recipient: str,
    requested_at: float,
    now: float,
    allowed_senders: set[str],
    purpose: str = "openai_login",
    max_age: int = 300,
) -> str | None:
    """Accept exactly one fresh matching message; ambiguity fails closed."""
    matches = [
        m
        for m in messages
        if m.id not in baseline_ids
        and m.sender.casefold() in {s.casefold() for s in allowed_senders}
        and m.recipient.casefold() == recipient.casefold()
        and m.purpose == purpose
        and requested_at <= m.timestamp <= now
        and now - m.timestamp <= max_age
        and m.code.isascii()
        and m.code.isdigit()
        and len(m.code) == 6
    ]
    return matches[0].code if len(matches) == 1 else None

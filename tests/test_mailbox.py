import socket
import pytest
from app.mailbox import MailboxError, Message, select_code, validate_mailbox_url


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.1"]
)
def test_private_resolution_rejected(monkeypatch, address):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (address, 443))]
    )
    with pytest.raises(MailboxError):
        validate_mailbox_url("https://mail.example/inbox")


def test_mixed_dns_and_http(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (0, 0, 0, "", ("8.8.8.8", 443)),
            (0, 0, 0, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(MailboxError):
        validate_mailbox_url("https://mail.example")
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 443))]
    )
    with pytest.raises(MailboxError):
        validate_mailbox_url("http://mail.example")
    assert validate_mailbox_url("http://mail.example", allow_http=True)


def test_matching_requires_new_unambiguous_message():
    good = Message(
        "new",
        "noreply@openai.com",
        "synthetic@example.com",
        "openai_login",
        105,
        "123456",
    )
    criteria = dict(
        baseline_ids={"old"},
        recipient="synthetic@example.com",
        requested_at=100,
        now=110,
        allowed_senders={"noreply@openai.com"},
    )
    assert select_code([good], **criteria) == "123456"
    assert select_code([good, good], **criteria) is None
    assert (
        select_code(
            [Message("old", good.sender, good.recipient, good.purpose, 105, good.code)],
            **criteria,
        )
        is None
    )
    assert (
        select_code(
            [
                Message(
                    "new",
                    good.sender,
                    "other@example.com",
                    good.purpose,
                    105,
                    good.code,
                )
            ],
            **criteria,
        )
        is None
    )
    assert (
        select_code(
            [Message("new", good.sender, good.recipient, good.purpose, 99, good.code)],
            **criteria,
        )
        is None
    )

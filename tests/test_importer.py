from app.importer import parse_line, preview
import pytest


def test_mailbox_is_fourth_field():
    r = parse_line("a----p----t----https://mail.example/inbox")
    assert r.mailbox_url.startswith("https://")


def test_proxy_like_fourth_field_rejected():
    with pytest.raises(ValueError):
        parse_line("a----p----t----socks5://host:1")


def test_preview_duplicates_and_missing():
    result = preview("a----p----t\na----p----t\ninvalid")
    assert result[1]["duplicate"] is True
    assert result[2]["valid"] is False

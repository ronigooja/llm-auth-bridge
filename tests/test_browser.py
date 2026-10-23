import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit
import pytest
from app.browser import (BrowserError, REDIRECT_URI, authorization_url, oauth_result,
                         pkce_pair, session_result, validate_callback)


def token(claims):
    return "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode() + ".signature"


def test_pkce_and_authorization():
    verifier, challenge = pkce_pair()
    assert len(verifier) >= 43
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = parse_qs(urlsplit(authorization_url("synthetic-state", challenge)).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == ["synthetic-state"]
    assert "offline_access" in params["scope"][0]


@pytest.mark.parametrize("url", [REDIRECT_URI + "?state=wrong&code=secret", REDIRECT_URI + "?state=state&code=a&code=b", REDIRECT_URI + "?state=state&code=a&state=state", "http://evil.example/auth/callback?state=state&code=a", REDIRECT_URI + "?state=state&code=a&error=denied", REDIRECT_URI + "?state=state&code=a#fragment"])
def test_oauth_rejects_invalid_callback(url):
    with pytest.raises(BrowserError, match="^OAuth callback validation failed$"):
        validate_callback(url, "state")


def test_oauth_valid_and_identity():
    assert validate_callback(REDIRECT_URI + "?state=state&code=synthetic", "state") == "synthetic"
    data = {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh", "id_token": token({"email": "synthetic@example.com"}), "expires_in": 3600}
    assert oauth_result(data, "synthetic@example.com")["credential_type"] == "codex_oauth"
    with pytest.raises(BrowserError, match="identity does not match"):
        oauth_result(data, "different@example.com")
    with pytest.raises(BrowserError):
        oauth_result({**data, "refresh_token": ""}, "synthetic@example.com")


def test_browser_session_identity_and_expiry():
    data = {"user": {"email": "synthetic@example.com"}, "accessToken": token({"exp": time.time() + 300})}
    result = session_result(data, "SYNTHETIC@example.com")
    assert result["credential_type"] == "chatgpt_web"
    assert set(result["credential"]) == {"access_token"}
    with pytest.raises(BrowserError, match="identity does not match"):
        session_result(data, "other@example.com")
    data["accessToken"] = token({"exp": 1})
    with pytest.raises(BrowserError):
        session_result(data, "synthetic@example.com")


@pytest.mark.parametrize("maintenance", [False, True])
def test_manual_resume_reuses_browser_and_delegates_state(monkeypatch, maintenance):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import app.browser as module
    import playwright.sync_api
    events = []

    class Page:
        url = "https://chatgpt.com/auth/login"
        def goto(self, *a, **k):
            pass
        def wait_for_timeout(self, *a):
            pass

    page = Page()
    class Context:
        def new_page(self):
            return page
        def route(self, *a):
            pass
        def set_default_timeout(self, *a):
            pass
        def storage_state(self):
            return {"cookies": [], "origins": []}

    context = Context()
    class Browser:
        def new_context(self, **kwargs):
            events.append(("context", kwargs))
            return context
        def close(self):
            events.append("closed")

    browser = Browser()
    class Chromium:
        def launch(self, **kwargs):
            events.append(("launch", kwargs))
            return browser

    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(chromium=Chromium())

    @contextmanager
    def fake_route(account):
        yield SimpleNamespace(playwright_proxy=None, session=None)

    result = {"credential_type": "chatgpt_web", "credential": {"access_token": "synthetic"}, "identity": "synthetic@example.com", "expires_at": None}
    resumed = False
    class Control:
        def checkpoint(self):
            pass
        def phase(self, *args):
            pass
        def save_state(self, state):
            events.append(("saved", state))
        def browser_ready(self, port):
            events.append(("ready", port))
        def browser_closed(self):
            events.append("control_closed")
        def wait_human(self, reason):
            nonlocal resumed
            events.append("manual")
            resumed = True
            return None

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_playwright)
    monkeypatch.setattr(module, "account_route", fake_route)
    monkeypatch.setattr(module, "detect_state", lambda p: "unknown")
    monkeypatch.setattr(module, "_get_session", lambda *a: result if resumed else None)
    moments = iter([0, 10, 10])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(moments))
    account = {"username": "synthetic@example.com", "password": "synthetic", "_maintenance": maintenance}
    if maintenance:
        with pytest.raises(module.ReauthenticationRequired, match="^reauth_required$"):
            module.run_login(account, {"kind": "chatgpt-web-voice"}, Control())
    else:
        assert module.run_login(account, {"kind": "chatgpt-web-voice"}, Control()) == result
    assert sum(isinstance(e, tuple) and e[0] == "launch" for e in events) == 1
    assert sum(isinstance(e, tuple) and e[0] == "context" for e in events) == 1
    assert ("manual" in events) is not maintenance
    assert events[-2:] == ["closed", "control_closed"]
    launch = next(e[1] for e in events if isinstance(e, tuple) and e[0] == "launch")
    assert "--no-proxy-server" in launch["args"]


def test_cancellation_is_not_converted_to_login_error():
    from app.browser import run_login
    class Cancelled(Exception):
        pass
    class Control:
        def checkpoint(self):
            raise Cancelled("synthetic cancellation")
    with pytest.raises(Cancelled):
        run_login({"username": "synthetic@example.com"}, {"kind": "cliproxyapi"}, Control())

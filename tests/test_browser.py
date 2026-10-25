import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit
import pytest
from app.browser import (
    BrowserError,
    REDIRECT_URI,
    authorization_url,
    oauth_result,
    pkce_pair,
    session_result,
    validate_callback,
)


def token(claims):
    return (
        "header."
        + base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        + ".signature"
    )


def test_pkce_and_authorization():
    verifier, challenge = pkce_pair()
    assert len(verifier) >= 43
    assert (
        challenge
        == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = parse_qs(urlsplit(authorization_url("synthetic-state", challenge)).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == ["synthetic-state"]
    assert "offline_access" in params["scope"][0]


@pytest.mark.parametrize(
    "url",
    [
        REDIRECT_URI + "?state=wrong&code=secret",
        REDIRECT_URI + "?state=state&code=a&code=b",
        REDIRECT_URI + "?state=state&code=a&state=state",
        "http://evil.example/auth/callback?state=state&code=a",
        REDIRECT_URI + "?state=state&code=a&error=denied",
        REDIRECT_URI + "?state=state&code=a#fragment",
    ],
)
def test_oauth_rejects_invalid_callback(url):
    with pytest.raises(BrowserError, match="^OAuth callback validation failed$"):
        validate_callback(url, "state")


def test_oauth_valid_and_identity():
    assert (
        validate_callback(REDIRECT_URI + "?state=state&code=synthetic", "state")
        == "synthetic"
    )
    data = {
        "access_token": "synthetic-access",
        "refresh_token": "synthetic-refresh",
        "id_token": token(
            {
                "email": "synthetic@example.com",
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "synthetic-account"
                },
            }
        ),
        "expires_in": 3600,
    }
    assert (
        oauth_result(data, "synthetic@example.com")["credential_type"] == "codex_oauth"
    )
    with pytest.raises(BrowserError, match="identity does not match"):
        oauth_result(data, "different@example.com")
    with pytest.raises(BrowserError):
        oauth_result({**data, "refresh_token": ""}, "synthetic@example.com")


def test_browser_session_identity_and_expiry():
    data = {
        "user": {"email": "synthetic@example.com"},
        "accessToken": token({"exp": time.time() + 300}),
    }
    result = session_result(data, "SYNTHETIC@example.com")
    assert result["credential_type"] == "chatgpt_web"
    assert set(result["credential"]) == {"access_token"}
    with pytest.raises(BrowserError, match="identity does not match"):
        session_result(data, "other@example.com")
    data["accessToken"] = token({"exp": 1})
    with pytest.raises(BrowserError):
        session_result(data, "synthetic@example.com")


@pytest.mark.parametrize("mode", ["manual", "maintenance", "cancel"])
@pytest.mark.parametrize("route_type", ["direct", "proxy"])
@pytest.mark.parametrize("restored", [False, True])
def test_manual_resume_reuses_browser_and_delegates_state(monkeypatch, mode, route_type, restored):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import app.browser as module
    import playwright.sync_api

    events = []

    class Page:
        url = "https://chatgpt.com/auth/login"

        def goto(self, *a, **k):
            events.append("navigation")

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

        def storage_state(self, *, indexed_db):
            assert indexed_db is True
            return {"cookies": [], "origins": []}

        def close(self):
            events.append("closed")

    context = Context()

    class Chromium:
        def launch_persistent_context(self, **kwargs):
            events.append(("launch", kwargs))
            return context

    @contextmanager
    def fake_device(account, control):
        from pathlib import Path
        try:
            yield SimpleNamespace(path=Path("/synthetic-device"), restored=restored)
        finally:
            events.append("device_snapshot")

    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(chromium=Chromium())

    @contextmanager
    def fake_route(account):
        yield SimpleNamespace(playwright_proxy=None if route_type == "direct" else {"server": "http://127.0.0.1:1234"}, session="synthetic-route-session")

    result = {
        "credential_type": "chatgpt_web",
        "credential": {"access_token": "synthetic"},
        "identity": "synthetic@example.com",
        "expires_at": None,
    }
    resumed = False

    class Cancelled(Exception):
        pass

    class Control:
        def checkpoint(self):
            if mode == "cancel" and any(
                isinstance(e, tuple) and e[0] == "ready" for e in events
            ):
                raise Cancelled("synthetic cancellation")

        def phase(self, *args):
            pass

        def update_timezone(self, value):
            events.append(("timezone", value))

        def save_state(self, state):
            events.append(("saved", state))

        def browser_ready(self, port):
            events.append(("ready", port))

        def browser_closed(self):
            events.append("control_closed")

        def wait_human(self, reason, **kwargs):
            nonlocal resumed
            events.append("manual")
            resumed = True
            return None

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_playwright)
    monkeypatch.setattr(module, "account_route", fake_route)
    monkeypatch.setattr(module, "device_directory", fake_device)
    def timezone(session):
        assert route_type == "proxy", "Direct routing must retain stored timezone"
        assert session == "synthetic-route-session"
        events.append("timezone_lookup")
        return "Europe/Paris"

    monkeypatch.setattr(module, "resolve_timezone", timezone)
    migrations = []
    monkeypatch.setattr(module, "_restore_legacy_state", lambda context, state: migrations.append(state))
    monkeypatch.setattr(module, "detect_state", lambda p: "unknown")
    monkeypatch.setattr(module, "_get_session", lambda *a: result if resumed else None)
    moments = iter([0, 31, 31])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(moments))
    from app.browser_identity import generate_profile
    profile = generate_profile(set())
    account = {
        "_browser_profile": profile,
        "route_type": route_type,
        "username": "synthetic@example.com",
        "password": "synthetic",
        "_maintenance": mode == "maintenance",
    }
    if mode == "maintenance":
        with pytest.raises(module.ReauthenticationRequired, match="^reauth_required$"):
            module.run_login(account, {"kind": "chatgpt-web-voice"}, Control(), {"cookies": [], "origins": []})
    elif mode == "cancel":
        with pytest.raises(Cancelled):
            module.run_login(account, {"kind": "chatgpt-web-voice"}, Control(), {"cookies": [], "origins": []})
    else:
        assert (
            module.run_login(account, {"kind": "chatgpt-web-voice"}, Control(), {"cookies": [], "origins": []})
            == result
        )
    assert sum(isinstance(e, tuple) and e[0] == "launch" for e in events) == 1
    assert ("manual" in events) == (mode == "manual")
    assert events[-3:] == ["closed", "control_closed", "device_snapshot"]
    launch = next(e[1] for e in events if isinstance(e, tuple) and e[0] == "launch")
    options = launch
    assert launch["user_data_dir"] == "/synthetic-device"
    assert "storage_state" not in launch
    assert all(options[key] == value for key, value in profile["context"].items())
    assert "identity_seed" not in options
    assert events.index(next(e for e in events if isinstance(e, tuple) and e[0] == "launch")) < events.index("navigation")
    assert migrations == ([] if restored else [{"cookies": [], "origins": []}])
    assert ("--no-proxy-server" in launch["args"]) == (route_type == "direct")
    if route_type == "proxy":
        assert events.index("timezone_lookup") < events.index("navigation")
        assert ("timezone", "Europe/Paris") in events
        assert options["timezone_id"] == "Europe/Paris"
    else:
        assert "timezone_lookup" not in events
        assert options["timezone_id"] == "UTC"
    assert launch["chromium_sandbox"] is True
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in launch["args"]


def test_cancellation_is_not_converted_to_login_error():
    from app.browser import run_login

    class Cancelled(Exception):
        pass

    class Control:
        def checkpoint(self):
            raise Cancelled("synthetic cancellation")

    with pytest.raises(Cancelled):
        run_login(
            {"username": "synthetic@example.com"}, {"kind": "cliproxyapi"}, Control()
        )


@pytest.mark.parametrize("state", [
    [], {"cookies": "invalid"}, {"cookies": [{}]},
    {"origins": [{"origin": "https://example.test/path", "localStorage": []}]},
    {"origins": [{"origin": "https://user@example.test", "localStorage": []}]},
    {"origins": [{"origin": "https://example.test", "localStorage": [{"name": "x", "value": 1}]}]},
    {"origins": [{"origin": "https://example.test", "localStorage": []}] * 101},
])
def test_legacy_state_rejects_invalid_shape_before_browser_mutation(state):
    from types import SimpleNamespace
    from app.browser import _restore_legacy_state
    context = SimpleNamespace(
        add_cookies=lambda value: pytest.fail("invalid state mutated cookies"),
        add_init_script=lambda value: pytest.fail("invalid state installed script"),
    )
    with pytest.raises(BrowserError, match="^Saved browser session is invalid$"):
        _restore_legacy_state(context, state)

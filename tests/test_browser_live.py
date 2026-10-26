"""Synthetic network/browser acceptance. Never contacts a real provider.

The root CI host can only launch Chromium with its sandbox disabled. This test
setting is not used by run_login, which requires the production sandbox.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import json
import shutil
import threading
import time
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import sync_playwright

from app.browser import BROWSER_ARGS, detect_state, _submit
from app.routing import account_route


@contextmanager
def fixture_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            pages = {
                "/email": '<form action="/password"><input name="username" type="email"><button type="submit">Continue</button></form>',
                "/password": '<form action="/code"><input name="password" type="password"><button type="submit">Continue</button></form>',
                "/code": '<form action="/consent"><p>Authentication app</p><input autocomplete="one-time-code" name="code"><button type="submit">Continue</button></form>',
                "/consent": '<form action="/done"><p>Authorize application</p><button type="submit">Continue</button></form>',
                "/done": "<p>Complete</p>",
            }
            body = pages.get(
                urlsplit(self.path).path, "<p>Unknown fixture</p>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def real_browser():
    executable = os.getenv("BRIDGE_TEST_CHROMIUM") or shutil.which("chromium")
    with sync_playwright() as playwright:
        if not executable and not os.path.exists(playwright.chromium.executable_path):
            pytest.skip("Chromium is not installed")
        browser = playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            chromium_sandbox=os.geteuid() != 0,
            args=BROWSER_ARGS + ["--no-proxy-server"],
        )
        try:
            yield browser
        finally:
            browser.close()


def test_real_chromium_detects_and_submits_synthetic_login(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    with fixture_server() as origin, real_browser() as browser:
        context = browser.new_context(service_workers="block")
        # Virtual provider host is fully intercepted. Fixture bytes come from
        # the real local HTTP server, never the provider or an external network.
        with httpx.Client(trust_env=False) as client:

            def intercept(route):
                response = client.get(origin + urlsplit(route.request.url).path)
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    content_type="text/html",
                )

            context.route("https://auth.openai.com/**", intercept)
            page = context.new_page()
            page.goto("https://auth.openai.com/email")
            assert detect_state(page) == "email"
            page.locator('input[name="username"]').fill("synthetic@example.com")
            _submit(page)
            page.wait_for_url("**/password*")
            assert detect_state(page) == "password"
            page.locator('input[name="password"]').fill("synthetic-password")
            _submit(page)
            page.wait_for_url("**/code*")
            assert detect_state(page) == "totp"
            page.locator('input[name="code"]').fill("123456")
            _submit(page)
            page.wait_for_url("**/consent*")
            assert detect_state(page) == "consent"
            _submit(page)
            page.wait_for_url("**/done*")
            assert detect_state(page) == "unknown"
        context.close()


def test_explicit_direct_route_reaches_real_fixture_despite_proxy_environment(
    monkeypatch,
):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with fixture_server() as origin, account_route({"route_type": "direct"}) as route:
        response = route.session.get(origin + "/email")
        assert response.status_code == 200
        assert 'name="username"' in response.text


@pytest.mark.parametrize(
    "scenario",
    [
        "rejected_password", "email_code", "changed_challenge",
        "delayed_spa", "delayed_navigation", "delayed_pending_email",
        "direct_password", "otp_only", "existing_session", "readonly_password",
        "disabled_password", "disabled_code", "email_alternate", "authenticator_only",
        "sms_code", "ambiguous_code", "authenticator_heading",
    ],
)
def test_login_wait_phase_matches_synthetic_page(monkeypatch, tmp_path, scenario):
    """Exercise the real adapter against intercepted provider pages only."""
    from types import SimpleNamespace
    import app.browser as module
    import playwright.sync_api
    monkeypatch.setattr(module, "configure_page_identity", lambda *args: None)

    phases, inputs, waits = [], [], []
    page_holder = []
    completed = False
    credential = {"identity": "synthetic@example.com", "credential_type": "chatgpt_web"}
    pages = {
        "/": "<p>Signed out</p>",
        "/auth/login": '<form action="/password"><input type="email" name="username"><button type="submit">Continue</button></form>',
        "/password": (
            '<form method="get" action="/code">'
            '<input type="email" name="username" value="synthetic@example.com" readonly>'
            '<label for="password">Password</label>'
            '<input id="password" type="password" name="password" '
            'autocomplete="current-password" required>'
            '<button type="submit" name="intent" value="validate">Continue</button></form>'
        ),
        "/code": '<form action="/done"><p>Check your email</p><input name="code" autocomplete="one-time-code"><button type="submit">Continue</button></form>',
        "/done": "<p>Done</p>",
    }
    if scenario == "rejected_password":
        pages["/password"] = '<form onsubmit="event.preventDefault(); document.querySelector(\'p\').textContent=\'Incorrect password\'"><input type="password" name="code"><button type="submit">Continue</button></form><p></p>'

    if scenario in ("delayed_spa", "delayed_navigation", "delayed_pending_email"):
        # The provider may retain the email form or show an intermediate page
        # while resolving the next challenge, exceeding the old four-second pause.
        transition = (
            "document.body.innerHTML=" + json.dumps(pages["/password"])
            if scenario == "delayed_spa"
            else "window.location.href='/password'"
        )
        loading = (
            "document.body.innerHTML='<p>Loading sign in</p>'; "
            if scenario != "delayed_pending_email" else ""
        )
        handler = "event.preventDefault(); " + loading + "setTimeout(() => {" + transition + "}, 5500)"
        pages["/auth/login"] = (
            '<form onsubmit="' + handler.replace('"', '&quot;') + '">'
            '<input type="email" name="username"><button type="submit">Continue</button></form>'
        )
    elif scenario == "direct_password":
        pages["/auth/login"] = pages["/password"]
    elif scenario == "otp_only":
        pages["/auth/login"] = pages["/code"]

    if scenario in ("readonly_password", "disabled_password"):
        pages["/password"] = pages["/password"].replace(
            '<label for="password">',
            '<input type="password" name="old" value="unchanged" readonly>'
            '<input type="password" name="disabled_old" disabled>'
            '<label for="password">',
        )
        if scenario == "disabled_password":
            pages["/password"] = pages["/password"].replace(
                'id="password" type="password"', 'id="password" type="password" disabled'
            ) + "<script>setTimeout(() => document.getElementById('password').disabled=false,5500)</script>"
    if scenario == "disabled_code":
        pages["/code"] = pages["/code"].replace('<input name="code"', '<input disabled name="code"') + (
            "<script>setTimeout(() => document.querySelector('input').disabled=false,5500)</script>"
        )
    if scenario == "email_alternate":
        pages["/code"] = pages["/code"].replace(
            '</form>', '<a href="#">Try authenticator instead</a></form>'
        )
    if scenario in ("authenticator_only", "sms_code", "ambiguous_code", "authenticator_heading"):
        pages["/auth/login"] = pages["/code"].replace(
            "Check your email",
            {
                "authenticator_only": "Enter the code from your authentication app",
                "authenticator_heading": "Check your authenticator app",
                "sms_code": "Enter the code sent via SMS to your phone",
                "ambiguous_code": "Enter verification code",
            }[scenario],
        )
    if scenario == "authenticator_heading":
        # The provider places the challenge title outside the input form,
        # nested in a layout container without a main landmark.
        pages["/auth/login"] = (
            '<div><header><h1>Check your authenticator app</h1></header>'
            '<p>Enter the one-time authentication code shown in your app to verify your identity.</p>'
            '<form action="/done"><label for="otp">One-time code</label>'
            '<input id="otp" name="code" autocomplete="one-time-code">'
            '<button type="submit">Continue</button>'
            '<a href="#">Try another method</a></form></div>'
        )

    with real_browser() as browser:

        class WrappedBrowser:
            def launch_persistent_context(self, **kwargs):
                # This scenario suite checks form behavior. The separate headed
                # device acceptance below exercises native profile persistence.
                for key in ("user_data_dir", "headless", "chromium_sandbox", "proxy", "env", "args"):
                    kwargs.pop(key)
                context = browser.new_context(**kwargs)

                def intercept(route):
                    path = urlsplit(route.request.url).path
                    inputs.append(route.request.url)
                    route.fulfill(
                        body=pages.get(path, "<p>Unknown</p>"), content_type="text/html"
                    )

                context.route("**/*", intercept)
                page = context.new_page()
                page_holder.append(page)
                # run_login owns one page; expose the same page for manual actions.
                return SimpleNamespace(
                    new_page=lambda: page,
                    route=context.route,
                    set_default_timeout=context.set_default_timeout,
                    storage_state=context.storage_state,
                    cookies=context.cookies,
                    close=context.close,
                )

            def close(self):
                browser.close()

        @contextmanager
        def fake_playwright():
            yield SimpleNamespace(
                chromium=WrappedBrowser()
            )

        @contextmanager
        def fake_route(account):
            yield SimpleNamespace(playwright_proxy=None)

        class Control:
            def __init__(self):
                self.started = time.monotonic()

            def checkpoint(self):
                elapsed = time.monotonic() - self.started
                if elapsed > 15:
                    page = page_holder[0] if page_holder else None
                    pytest.fail(
                        "Synthetic Codex flow exceeded 15s: "
                        f"url={page.url if page else None} phases={phases} "
                        f"requests={inputs}"
                    )

            def phase(self, phase, reason):
                phases.append(phase)

            def save_state(self, state):
                pass

            def wait_human(self, reason, *, phase):
                nonlocal completed
                page = page_holder[0]
                waits.append((phase, detect_state(page), reason))
                if scenario in ("delayed_spa", "delayed_navigation", "delayed_pending_email") and phase != "email_code_required":
                    pytest.fail("The adapter paused before submitting the delayed password form")
                if scenario == "rejected_password":
                    assert "Incorrect password" in page.locator("body").inner_text()
                    assert "verification code" not in reason
                    completed = True
                    return None
                if scenario == "changed_challenge" and len(waits) == 1:
                    # The user returns to a password page before an old code arrives.
                    page.goto("https://chatgpt.com/password")
                    page.set_content('<form><input type="password" name="code"><button type="submit">Continue</button></form>')
                    return "123456"
                if scenario == "changed_challenge":
                    assert page.locator('input[type="password"]').input_value() == ""
                    completed = True
                    return None
                return "123456"

        @contextmanager
        def fake_device(account, control):
            from pathlib import Path
            yield SimpleNamespace(path=tmp_path, restored=True, mark_ready=lambda: None, abort_snapshot=lambda: None)

        monkeypatch.setattr(module, "device_directory", fake_device)
        monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_playwright)
        monkeypatch.setattr(module, "account_route", fake_route)
        def fake_session(*args):
            if scenario == "existing_session" or completed or (
                page_holder and urlsplit(page_holder[0].url).path == "/done"
            ):
                return credential
            return None

        monkeypatch.setattr(module, "_get_session", fake_session)
        def synthetic_totp(seed):
            assert scenario in ("authenticator_only", "authenticator_heading"), "Only an explicit authenticator challenge may use the saved seed"
            return "123456"

        monkeypatch.setattr(module, "generate_code", synthetic_totp)
        monkeypatch.setattr(module, "seconds_remaining", lambda: 20)
        from app.browser_identity import generate_profile
        assert module.run_login(
            {"_browser_profile": generate_profile(set()), "username": "synthetic@example.com", "password": "synthetic-password", "totp": "synthetic-seed"},
            {"kind": "chatgpt-web-voice"},
            Control(),
        ) == credential
    no_password = ("otp_only", "existing_session", "authenticator_only", "sms_code", "ambiguous_code", "authenticator_heading")
    if scenario not in ("rejected_password", "changed_challenge", *no_password):
        assert any("password=synthetic-password" in url for url in inputs)
    if scenario in ("readonly_password", "disabled_password"):
        assert any("old=unchanged" in url for url in inputs)
    assert phases.count("password") == (0 if scenario in no_password else 1)
    assert phases.count("email") == (0 if scenario in ("direct_password", *no_password) else 1)
    if scenario == "rejected_password":
        assert [w[:2] for w in waits] == [("password_required", "password")]
    elif scenario == "changed_challenge":
        assert [w[:2] for w in waits] == [
            ("email_code_required", "email_code"),
            ("password_required", "password"),
        ]
    elif scenario in ("existing_session", "authenticator_only", "authenticator_heading"):
        assert not waits
        assert phases.count("totp") == (1 if scenario in ("authenticator_only", "authenticator_heading") else 0)
    elif scenario in ("sms_code", "ambiguous_code"):
        assert [w[:2] for w in waits] == [("verification_code_required", "verification_code")]
    else:
        assert [w[:2] for w in waits] == [("email_code_required", "email_code")]
        assert any("code=123456" in url for url in inputs)


@pytest.mark.parametrize(
    "instructions,expected",
    [
        ('<p>Enter the code sent to your email</p><a>Try authenticator instead</a>', "email_code"),
        ('<p>Enter the code from your authentication app</p><button>Use email instead</button>', "totp"),
        ('<h1>Authentication app</h1>', "totp"),
        ('<p>Enter the code sent via SMS</p>', "verification_code"),
        ('<p>Enter verification code</p>', "verification_code"),
        ('<p>Enter verification code<span hidden>Use your authenticator app</span></p>', "verification_code"),
        ('<p>Enter verification code<span style="display:none">Use your authenticator app</span></p>', "verification_code"),
        ('<p>Enter your email code or code from your authenticator app</p>', "verification_code"),
    ],
)
def test_code_classifier_uses_current_instructions_not_alternate_controls(instructions, expected):
    with real_browser() as browser:
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(
            body='<main><form>' + instructions + '<input name="code" autocomplete="one-time-code"></form></main>',
            content_type="text/html",
        ))
        page = context.new_page()
        page.goto("https://auth.openai.com/challenge")
        assert detect_state(page) == expected
        context.close()


def test_submit_skips_disabled_transition_button():
    with real_browser() as browser:
        page = browser.new_page()
        page.set_content('<form onsubmit="event.preventDefault(); document.body.dataset.submitted=1">'
                         '<button type="submit" disabled>Loading</button>'
                         '<button type="submit">Continue</button></form>')
        _submit(page)
        assert page.locator("body").get_attribute("data-submitted") == "1"


def test_submit_waits_for_only_pending_button():
    with real_browser() as browser:
        page = browser.new_page()
        page.set_content('<form onsubmit="event.preventDefault(); document.body.dataset.submitted=1">'
                         '<button type="submit" disabled>Continue</button></form>'
                         '<script>setTimeout(() => document.querySelector("button").disabled=false, 1500)</script>')
        _submit(page)
        assert page.locator("body").get_attribute("data-submitted") == "1"


def test_legacy_localstorage_migration_is_origin_bound_and_does_not_reset_values():
    from app.browser import _restore_legacy_state
    with real_browser() as browser:
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(body="<p>Synthetic</p>", content_type="text/html"))
        _restore_legacy_state(context, {"cookies": [], "origins": [{
            "origin": "https://legacy.example.test", "localStorage": [
                {"name": "synthetic-session", "value": "legacy-value"},
                {"name": "__proto__", "value": "ordinary-storage-key"},
            ],
        }]})
        page = context.new_page()
        page.goto("https://other.example.test/")
        assert page.evaluate("localStorage.length") == 0
        page.goto("https://legacy.example.test/")
        assert page.evaluate("localStorage.getItem('synthetic-session')") == "legacy-value"
        assert page.evaluate("localStorage.getItem('__proto__')") == "ordinary-storage-key"
        page.evaluate("localStorage.setItem('synthetic-session', 'updated-value')")
        page.reload()
        assert page.evaluate("localStorage.getItem('synthetic-session')") == "updated-value"
        context.close()


def test_headed_native_device_relaunch_preserves_storage_and_isolates_accounts():
    """Synthetic native Chromium acceptance; requires CI Xvfb, never a provider.

    Full profiles cross AESGCM-encrypted archive roundtrips into new /tmp
    directories. A persistent device preserves storage, while sessionStorage belongs
    to the original tab and is deliberately not resurrected by the adapter.
    """
    if not os.getenv("DISPLAY"):
        pytest.skip("Headed native device acceptance requires DISPLAY / Xvfb")
    from app.browser_identity import generate_profile, context_options
    from app.browser import _snapshot_session_cookies, _restore_session_cookies, DEVICE_READY_FILE, fit_browser_window
    from app.browser_device import device_directory
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    class EncryptedControl:
        def __init__(self):
            self.key = AESGCM.generate_key(bit_length=256)
            self.ciphertext = None
            self.saves = 0

        def load_device(self):
            if self.ciphertext is None:
                return None
            return AESGCM(self.key).decrypt(self.ciphertext[:12], self.ciphertext[12:], b"synthetic-device")

        def save_device(self, archive):
            nonce = os.urandom(12)
            self.ciphertext = nonce + AESGCM(self.key).encrypt(nonce, archive, b"synthetic-device")
            self.saves += 1

    first_control, second_control = EncryptedControl(), EncryptedControl()
    first_account, second_account = {"id": "synthetic-first"}, {"id": "synthetic-second"}
    first = generate_profile(set())
    dimensions = first["context"]["viewport"]
    second = generate_profile({(dimensions["width"], dimensions["height"])})
    executable = os.getenv("BRIDGE_TEST_CHROMIUM") or shutil.which("chromium")
    with sync_playwright() as playwright:
        if not executable and not os.path.exists(playwright.chromium.executable_path):
            pytest.skip("Chromium is not installed")

        @contextmanager
        def launch(account, control, profile):
            with device_directory(account, control) as device:
                assert device.restored is (control.saves > 0)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(device.path), executable_path=executable,
                    headless=False, chromium_sandbox=os.geteuid() != 0,
                    proxy=None, accept_downloads=False, service_workers="block",
                    env={**os.environ, "DISPLAY": os.getenv("DISPLAY", ":99")},
                    args=BROWSER_ARGS + ["--no-proxy-server"],
                    **context_options(profile, native_window=True),
                )
                try:
                    _restore_session_cookies(context, device.path)
                    (device.path / DEVICE_READY_FILE).touch(mode=0o600, exist_ok=True)
                    device.mark_ready()
                    context.route("**/*", lambda route: route.fulfill(body="<p>Synthetic</p>", content_type="text/html"))
                    page = context.new_page()
                    fit_browser_window(context, page)
                    page.wait_for_timeout(200)
                    print("Fitted native geometry: " + json.dumps(page.evaluate("({width:innerWidth,height:innerHeight,outerWidth,outerHeight,screenX,screenY,screenWidth:screen.width,screenHeight:screen.height})")), flush=True)
                    # Native Chromium frame calculations can round down by one pixel.
                    page.wait_for_function("outerWidth >= 1919 && outerWidth <= 1920 && outerHeight >= 1079 && outerHeight <= 1080 && screenX === 0 && screenY === 0", timeout=5000)
                    page.goto("https://device.example.test/")
                    yield context, page, device.path
                finally:
                    try:
                        _snapshot_session_cookies(context, device.path)
                    finally:
                        try:
                            context.close()
                        except BaseException:
                            device.abort_snapshot()
                            raise

        with launch(first_account, first_control, first) as (context, page, first_path):
            context.add_cookies([{"name": "synthetic-session", "value": "first-account",
                "domain": "device.example.test", "path": "/", "secure": True,
                "expires": __import__('time').time() + 3600}])
            context.add_cookies([{"name": "synthetic-tab-session", "value": "first-account-session",
                "domain": "device.example.test", "path": "/", "secure": True}])
            page.evaluate("""async () => {
                localStorage.setItem('device', 'first-account');
                sessionStorage.setItem('tab', 'first-tab');
                const db = await new Promise((resolve, reject) => {
                    const request = indexedDB.open('synthetic-device', 1);
                    request.onupgradeneeded = () => request.result.createObjectStore('tokens');
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('tokens', 'readwrite');
                    tx.objectStore('tokens').put('synthetic-token', 'session');
                    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
                }); db.close();
            }""")
            identity = page.evaluate("({width: innerWidth, height: innerHeight, outerWidth, outerHeight, screenWidth: screen.width, screenHeight: screen.height, screenAvailWidth: screen.availWidth, screenAvailHeight: screen.availHeight, dpr: devicePixelRatio, locale: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone})")
            print("Synthetic headed device geometry: " + json.dumps(identity, sort_keys=True))
            assert 1919 <= identity["outerWidth"] <= 1920
            assert 1079 <= identity["outerHeight"] <= 1080
            assert 1800 <= identity["width"] <= 1920
            assert 900 <= identity["height"] < 1080
            assert (identity["screenWidth"], identity["screenHeight"]) == (1920, 1080)
            assert identity["dpr"] == 1
            assert identity["width"] <= identity["outerWidth"] <= identity["screenAvailWidth"] <= 1920
            assert identity["height"] <= identity["outerHeight"] <= identity["screenAvailHeight"] <= 1080
            page.reload()
            assert page.evaluate("sessionStorage.getItem('tab')") == "first-tab"
            session = context.new_cdp_session(page)
            window_id = session.send("Browser.getWindowForTarget")["windowId"]
            session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "normal"}})
            session.send("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {"left": 200, "top": 100, "width": 1000, "height": 700},
            })
            page.wait_for_function("outerWidth >= 999 && outerWidth <= 1000 && outerHeight >= 699 && outerHeight <= 700 && innerWidth <= 1000 && innerHeight < 700", timeout=5000)
            session.detach()
        assert not first_path.exists()
        assert first_control.saves == 1 and first_control.ciphertext is not None
        assert b"synthetic-token" not in first_control.ciphertext
        with launch(first_account, first_control, first) as (context, page, restored_path):
            assert restored_path != first_path
            assert page.evaluate("localStorage.getItem('device')") == "first-account"
            assert any(c["name"] == "synthetic-tab-session" and c["value"] == "first-account-session" and c["expires"] == -1 for c in context.cookies())
            assert any(c["name"] == "synthetic-session" and c["value"] == "first-account" for c in context.cookies())
            assert page.evaluate("""async () => {
                const db = await new Promise(resolve => {
                    const request = indexedDB.open('synthetic-device', 1);
                    request.onsuccess = () => resolve(request.result);
                });
                const value = await new Promise(resolve => {
                    const request = db.transaction('tokens').objectStore('tokens').get('session');
                    request.onsuccess = () => resolve(request.result);
                }); db.close(); return value;
            }""") == "synthetic-token"
            assert page.evaluate("sessionStorage.getItem('tab')") is None
            assert page.evaluate("({width: innerWidth, height: innerHeight, outerWidth, outerHeight, screenWidth: screen.width, screenHeight: screen.height, screenAvailWidth: screen.availWidth, screenAvailHeight: screen.availHeight, dpr: devicePixelRatio, locale: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone})") == identity
        assert not restored_path.exists()
        assert first_control.saves == 2
        with launch(second_account, second_control, second) as (context, page, second_path):
            assert second_path not in (first_path, restored_path)
            assert page.evaluate("localStorage.length") == 0
            assert context.cookies() == []
            assert page.evaluate("indexedDB.databases().then(dbs => dbs.length)") == 0
            assert page.evaluate("sessionStorage.length") == 0
            assert first["identity_seed"] != second["identity_seed"]
            assert page.evaluate("({width: innerWidth, height: innerHeight})") == {"width": identity["width"], "height": identity["height"]}
        assert not second_path.exists()
        assert second_control.saves == 1


@pytest.mark.parametrize("scenario", [
    "matching", "nested_remove", "mismatch", "duplicate", "suffix", "remove", "other_account",
    "multiple_identities", "external_link", "unsupported_card", "unknown", "absent", "disabled", "ambiguous",
    "delayed", "delayed_disabled", "workspace", "click_failure",
    "wrong_result_identity", "invalid_callback", "chooser_replaced_remove",
    "chooser_replaced_external", "consent_replaced",
])
def test_codex_existing_session_continuation_is_identity_bound_and_recovers(
    monkeypatch, tmp_path, scenario,
):
    """Full synthetic OAuth flow; no real account, network, or saved device."""
    import base64
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlencode
    import playwright.sync_api
    import app.browser as module
    from app.browser_identity import generate_profile
    monkeypatch.setattr(module, "configure_page_identity", lambda *args: None)

    identity = "synthetic@example.com"
    callback_state = None
    pages, phases, waits, exchanges, launches = [], [], [], [], []
    inputs = []
    manual_scenarios = {
        "mismatch", "duplicate", "suffix", "remove", "other_account",
        "multiple_identities", "external_link", "unsupported_card", "unknown", "absent", "disabled", "ambiguous",
        "click_failure", "chooser_replaced_remove", "chooser_replaced_external", "consent_replaced",
    }
    monkeypatch.setattr(module, "TRANSITION_WAIT_SECONDS", 1.5)

    def jwt(claims):
        return "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode() + ".signature"

    def exchange(url, *, data):
        exchanges.append(data)
        assert data["code"] == "synthetic-code"
        return SimpleNamespace(status_code=200, json=lambda: {
            "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
            "id_token": jwt({"email": "wrong@example.com" if scenario == "wrong_result_identity" else identity,
                             "https://api.openai.com/auth": {"chatgpt_account_id": "synthetic-account"}}),
            "expires_in": 3600,
        })

    @contextmanager
    def fake_route(account):
        yield SimpleNamespace(playwright_proxy=None, session=SimpleNamespace(post=exchange))

    @contextmanager
    def fake_device(account, control):
        yield SimpleNamespace(path=tmp_path, mark_ready=lambda: None, abort_snapshot=lambda: None)

    def callback_url():
        return module.REDIRECT_URI + "?" + urlencode({
            "state": "incorrect-state" if scenario == "invalid_callback" else callback_state,
            "code": "synthetic-code",
        })

    def chooser():
        shown = {
            "mismatch": "other@example.com", "suffix": identity + ".invalid",
        }.get(scenario, identity.upper())
        action = "window.location.href='/sign-in-with-chatgpt/codex/consent'"
        card = '<button onclick="' + action + '"><span>' + shown + '</span></button>'
        if scenario == "external_link":
            card = '<a href="https://untrusted.example.test/"><span>' + shown + '</span></a>'
        if scenario == "unsupported_card":
            card = '<div onclick="' + action + '"><span>' + shown + '</span></div>'
        if scenario == "nested_remove":
            card = ('<div role="button" tabindex="0" onclick="' + action + '"><span>' + shown
                    + '</span><button aria-label="Remove account" onclick="event.stopPropagation(); document.body.dataset.unsafe=1">×</button></div>')
        if scenario == "duplicate":
            card += card
        if scenario == "multiple_identities":
            card = card.replace('</button>', '<span>other@example.com</span></button>')
        if scenario in ("remove", "other_account"):
            label = "Remove account" if scenario == "remove" else "Use another account"
            card = '<button aria-label="' + label + '" onclick="document.body.dataset.unsafe=1">' + shown + '</button>'
        if scenario == "unknown":
            return '<h1>Unknown page</h1><button onclick="document.body.dataset.unsafe=1">Continue</button>'
        return ('<h1>Welcome back</h1><p>Choose an account to continue to Codex</p>' + card
                + '<button aria-label="Remove account" onclick="document.body.dataset.unsafe=1">×</button>'
                  '<button onclick="document.body.dataset.unsafe=1">Use another account</button>'
                  '<button onclick="document.body.dataset.unsafe=1">Create account</button>')

    def consent():
        button = '<button type="button" onclick="window.location.href=\'' + callback_url() + '\'">Continue</button>'
        if scenario == "absent":
            button = ''
        elif scenario == "ambiguous":
            button += button
        elif scenario in ("disabled", "delayed_disabled"):
            button = button.replace('type="button"', 'type="button" disabled')
        if scenario == "delayed":
            button = '<script>setTimeout(() => {document.body.insertAdjacentHTML("beforeend", ' + json.dumps(button) + ')}, 650)</script>'
        elif scenario == "delayed_disabled":
            button += '<script>setTimeout(() => {document.querySelector("button[disabled]").disabled=false},650)</script>'
        # Consent preserves the selected workspace; automation must never
        # choose or change a workspace, even when other options are available.
        return ('<h1>Select a workspace</h1><label><input type="radio" name="workspace" checked>Personal account</label>'
                '<label><input type="radio" name="workspace" onclick="document.body.dataset.unsafe=1">Other workspace</label>'
                '<button onclick="document.body.dataset.unsafe=1">Cancel</button>' + button)

    with real_browser() as browser:
        class Chromium:
            def launch_persistent_context(self, **kwargs):
                launches.append(kwargs)
                for key in ("user_data_dir", "headless", "chromium_sandbox", "proxy", "env", "args"):
                    kwargs.pop(key)
                context = browser.new_context(**kwargs)

                def intercept(route):
                    nonlocal callback_state
                    parsed = urlsplit(route.request.url)
                    inputs.append(route.request.url)
                    if parsed.path == "/oauth/authorize":
                        callback_state = parse_qs(parsed.query)["state"][0]
                        entry = "/unknown" if scenario == "unknown" else "/choose-an-account"
                        destination = entry
                        if destination == "/unknown":
                            route.fulfill(body='<script>window.location.replace("https://auth.openai.com/unknown")</script>', content_type="text/html")
                        else:
                            route.fulfill(body='<script>window.location.replace("https://auth.openai.com/choose-an-account")</script>', content_type="text/html")
                    else:
                        route.fulfill(body=consent() if parsed.path.endswith("/consent") else chooser(), content_type="text/html")

                context.route("**/*", intercept)
                page = context.new_page()
                pages.append(page)
                return SimpleNamespace(new_page=lambda: page, route=context.route, new_cdp_session=context.new_cdp_session,
                                       set_default_timeout=context.set_default_timeout,
                                       storage_state=context.storage_state, cookies=context.cookies, close=context.close)

        @contextmanager
        def fake_playwright():
            yield SimpleNamespace(chromium=Chromium())

        class Control:
            def __init__(self):
                self.started = time.monotonic()

            def checkpoint(self):
                elapsed = time.monotonic() - self.started
                if elapsed > 15:
                    page = pages[0] if pages else None
                    pytest.fail(
                        "Synthetic Codex flow exceeded 15s: "
                        f"url={page.url if page else None} phases={phases} "
                        f"requests={inputs}"
                    )

            def phase(self, phase, reason):
                phases.append(phase)
                replacement = None
                # Replace after validation, before click: the same text must
                # never let a Locator silently target a new dangerous control.
                if phase == "account_chooser" and scenario == "chooser_replaced_remove":
                    replacement = '<button aria-label="Remove account" onclick="document.body.dataset.unsafe=1"><span>' + identity.upper() + '</span></button>'
                elif phase == "account_chooser" and scenario == "chooser_replaced_external":
                    replacement = '<a href="https://untrusted.example.test/" onclick="event.preventDefault(); document.body.dataset.unsafe=1"><span>' + identity.upper() + '</span></a>'
                elif phase == "consent" and scenario == "consent_replaced":
                    replacement = '<button onclick="document.body.dataset.unsafe=1">Continue</button>'
                if replacement is not None:
                    pages[0].locator("body").evaluate("(node, html) => {node.innerHTML = html}", replacement)

            def save_state(self, state):
                pass

            def wait_human(self, reason, *, phase):
                assert scenario in manual_scenarios, (
                    f"Unexpected early manual pause url={pages[0].url} "
                    f"requests={inputs} phase={phase}"
                )
                page = pages[0]
                waits.append((phase, module.detect_state(page)))
                assert page.locator('body').get_attribute('data-unsafe') is None
                assert not exchanges
                assert len(pages) == 1
                # A human can finish in the same browser; no relaunch/reset.
                page.goto(callback_url())
                return None

        if scenario == "click_failure":
            original = module._consent_continue

            def failing_action(page):
                action = original(page)
                if action is None:
                    return None
                def fail(**kwargs):
                    raise playwright.sync_api.Error("synthetic detached control")
                return SimpleNamespace(click=fail)

            monkeypatch.setattr(module, "_consent_continue", failing_action)
        monkeypatch.setattr(module, "device_directory", fake_device)
        monkeypatch.setattr(module, "account_route", fake_route)
        monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_playwright)
        account = {"_browser_profile": generate_profile(set()), "username": identity,
                   "password": "must-never-submit", "totp": "must-never-submit"}
        if scenario in ("wrong_result_identity", "invalid_callback"):
            with pytest.raises(module.BrowserError, match="identity does not match" if scenario == "wrong_result_identity" else "callback validation failed"):
                module.run_login(account, {"kind": "cliproxyapi"}, Control())
        else:
            result = module.run_login(account, {"kind": "cliproxyapi"}, Control())
            assert result["identity"] == identity
    assert len(launches) == 1
    assert len(exchanges) == (0 if scenario == "invalid_callback" else 1)
    assert bool(waits) == (scenario in manual_scenarios)
    assert not {"email", "password", "totp"}.intersection(phases)
    if scenario in {"absent", "disabled", "ambiguous", "click_failure", "consent_replaced"}:
        assert waits == [("waiting_human", "consent")]
    if scenario in {"mismatch", "duplicate", "suffix", "remove", "other_account", "multiple_identities", "external_link", "unsupported_card", "chooser_replaced_remove", "chooser_replaced_external"}:
        assert waits == [("waiting_human", "account_chooser")]
    if scenario == "unknown":
        assert waits == [("waiting_human", "unknown")]

    if scenario in {"chooser_replaced_remove", "chooser_replaced_external"}:
        assert phases.count("account_chooser") == 1, "Detached choices must never be replayed"
    if scenario == "consent_replaced":
        assert phases.count("consent") == 1, "Detached consent must never be replayed"

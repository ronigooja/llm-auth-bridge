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
def test_login_wait_phase_matches_synthetic_page(monkeypatch, scenario):
    """Exercise the real adapter against intercepted provider pages only."""
    from types import SimpleNamespace
    import app.browser as module
    import playwright.sync_api

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
            def checkpoint(self):
                pass

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
            yield SimpleNamespace(path=Path("/synthetic-device"), restored=True)

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


def test_headed_native_device_relaunch_preserves_storage_and_isolates_accounts(tmp_path):
    """Synthetic native Chromium acceptance; requires CI Xvfb, never a provider.

    A persistent device preserves durable storage, while sessionStorage belongs
    to the original tab and is deliberately not resurrected by the adapter.
    """
    if not os.getenv("DISPLAY"):
        pytest.skip("Headed native device acceptance requires DISPLAY / Xvfb")
    from app.browser_identity import generate_profile, context_options
    first = generate_profile(set())
    dimensions = first["context"]["viewport"]
    second = generate_profile({(dimensions["width"], dimensions["height"])})
    executable = os.getenv("BRIDGE_TEST_CHROMIUM") or shutil.which("chromium")
    with sync_playwright() as playwright:
        if not executable and not os.path.exists(playwright.chromium.executable_path):
            pytest.skip("Chromium is not installed")

        def launch(directory, profile):
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(directory), executable_path=executable,
                headless=False, chromium_sandbox=os.geteuid() != 0,
                args=BROWSER_ARGS + ["--no-proxy-server"],
                **context_options(profile),
            )
            context.route("**/*", lambda route: route.fulfill(body="<p>Synthetic</p>", content_type="text/html"))
            page = context.new_page()
            page.goto("https://device.example.test/")
            return context, page

        context, page = launch(tmp_path / "first", first)
        try:
            context.add_cookies([{"name": "synthetic-session", "value": "first-account",
                "domain": "device.example.test", "path": "/", "secure": True,
                "expires": __import__('time').time() + 3600}])
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
            identity = page.evaluate("({width: innerWidth, height: innerHeight, locale: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone})")
            page.reload()
            assert page.evaluate("sessionStorage.getItem('tab')") == "first-tab"
        finally:
            context.close()
        context, page = launch(tmp_path / "first", first)
        try:
            assert page.evaluate("localStorage.getItem('device')") == "first-account"
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
            assert page.evaluate("({width: innerWidth, height: innerHeight, locale: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone})") == identity
        finally:
            context.close()
        context, page = launch(tmp_path / "second", second)
        try:
            assert page.evaluate("localStorage.length") == 0
            assert context.cookies() == []
            assert page.evaluate("indexedDB.databases().then(dbs => dbs.length)") == 0
            assert page.evaluate("sessionStorage.length") == 0
            assert page.evaluate("innerWidth") != identity["width"] or page.evaluate("innerHeight") != identity["height"]
        finally:
            context.close()

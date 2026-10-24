"""Synthetic network/browser acceptance. Never contacts a real provider.

The root CI host can only launch Chromium with its sandbox disabled. This test
setting is not used by run_login, which requires the production sandbox.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
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


@pytest.mark.parametrize("scenario", ["rejected_password", "email_code", "changed_challenge"])
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
        "/password": '<form action="/code"><input type="password" name="password"><button type="submit">Continue</button></form>',
        "/code": '<form action="/done"><input name="code" autocomplete="one-time-code"><button type="submit">Continue</button></form>',
        "/done": "<p>Done</p>",
    }
    if scenario == "rejected_password":
        pages["/password"] = '<form onsubmit="event.preventDefault(); document.querySelector(\'p\').textContent=\'Incorrect password\'"><input type="password" name="code"><button type="submit">Continue</button></form><p></p>'

    with real_browser() as browser:

        class WrappedBrowser:
            def new_context(self, **kwargs):
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
                )

            def close(self):
                browser.close()

        @contextmanager
        def fake_playwright():
            yield SimpleNamespace(
                chromium=SimpleNamespace(launch=lambda **k: WrappedBrowser())
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

        monkeypatch.setattr(playwright.sync_api, "sync_playwright", fake_playwright)
        monkeypatch.setattr(module, "account_route", fake_route)
        def fake_session(*args):
            if completed or (
                page_holder and urlsplit(page_holder[0].url).path == "/done"
            ):
                return credential
            return None

        monkeypatch.setattr(module, "_get_session", fake_session)
        assert module.run_login(
            {"username": "synthetic@example.com", "password": "synthetic-password"},
            {"kind": "chatgpt-web-voice"},
            Control(),
        ) == credential
    assert phases.count("password") == 1
    if scenario == "rejected_password":
        assert [w[:2] for w in waits] == [("password_required", "password")]
    elif scenario == "changed_challenge":
        assert [w[:2] for w in waits] == [
            ("email_code_required", "email_code"),
            ("password_required", "password"),
        ]
    else:
        assert [w[:2] for w in waits] == [("email_code_required", "email_code")]
        assert any("code=123456" in url for url in inputs)

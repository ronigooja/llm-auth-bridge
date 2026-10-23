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

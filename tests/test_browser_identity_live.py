"""Headed synthetic identity acceptance. No credentials or provider traffic."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

import pytest
from playwright.sync_api import sync_playwright

from app.browser import BROWSER_ARGS
from app.browser_identity import configure_page_identity, context_options, generate_profile


@contextmanager
def identity_origin():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = (json.dumps(dict(self.headers)) if self.path == '/headers'
                    else ('<!doctype html><title>Synthetic identity</title>' +
                          ('<p>Frame</p>' if self.path == '/frame' else '<iframe src="/frame"></iframe>'))).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if self.path == '/headers' else 'text/html')
            self.send_header('Accept-CH', 'Sec-CH-UA-Full-Version-List, Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


PROBE = """async () => ({
    ua: navigator.userAgent, platform: navigator.platform,
    language: navigator.language, webdriver: navigator.webdriver,
    ch: await navigator.userAgentData.getHighEntropyValues([
        'platformVersion', 'architecture', 'bitness', 'fullVersionList'])
})"""


@pytest.mark.skipif(not os.getenv('DISPLAY'), reason='Requires headed CI display')
@pytest.mark.parametrize('platform,expected,nav', [('windows', 'Windows', 'Win32'), ('macos', 'macOS', 'MacIntel')])
def test_headed_identity_first_request_headers_js_iframe_and_restart(tmp_path, platform, expected, nav):
    profile = generate_profile()
    profile['browser']['platform'] = platform
    snapshots = []
    with identity_origin() as origin, sync_playwright() as playwright:
        for _ in range(2):
            context = playwright.chromium.launch_persistent_context(
                str(tmp_path / platform), headless=False, chromium_sandbox=True,
                args=BROWSER_ARGS + ['--no-proxy-server'], service_workers='block',
                **context_options(profile, native_window=True))
            try:
                page = context.new_page()
                configure_page_identity(context, page, profile)
                first = page.goto(origin)
                headers = {k.lower(): v for k, v in first.request.all_headers().items()}
                observed = page.evaluate(PROBE)
                assert 'Linux' not in observed['ua'] and 'HeadlessChrome' not in observed['ua']
                assert observed['platform'] == nav
                assert observed['language'] == 'en-US'
                assert observed['ch']['platform'] == expected
                assert observed['ch']['platformVersion'] == ('15.0.0' if platform == 'macos' else '10.0.0')
                assert observed['ch']['architecture'] == 'x86'
                assert observed['ch']['bitness'] == '64'
                major = context.browser.version.split('.')[0]
                assert f'Chrome/{major}.0.0.0' in observed['ua']
                assert headers['user-agent'] == observed['ua']
                assert headers['sec-ch-ua-platform'] == json.dumps(expected)
                assert headers['sec-ch-ua-mobile'] == '?0'
                echoed = page.evaluate("fetch('/headers').then(r => r.json())")
                echoed = {k.lower(): v for k, v in echoed.items()}
                assert echoed['user-agent'] == observed['ua']
                assert echoed['sec-ch-ua-platform'] == json.dumps(expected)
                assert context.browser.version in echoed['sec-ch-ua-full-version-list']
                page.frame_locator('iframe').locator('body').wait_for()
                frame = page.frames[1].evaluate(PROBE)
                assert frame == observed
                snapshots.append(observed)
            finally:
                context.close()
    assert snapshots[0] == snapshots[1]


@pytest.mark.skipif(not os.getenv('BRIDGE_BROWSERLEAKS_CHECK'), reason='Explicit external diagnostic only')
def test_browserleaks_synthetic_windows_profile(tmp_path):
    """Only public CI egress is exposed; never record the page, IP or cookies."""
    profile = generate_profile()
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / 'synthetic-browserleaks'), headless=False, chromium_sandbox=True,
            args=BROWSER_ARGS + ['--no-proxy-server'], service_workers='block',
            **context_options(profile, native_window=True))
        try:
            page = context.new_page()
            configure_page_identity(context, page, profile)
            response = page.goto('https://browserleaks.com/ip', wait_until='domcontentloaded', timeout=60000)
            assert response.status == 200
            assert 'BrowserLeaks' in page.title()
            identity = page.evaluate(PROBE)
            assert identity['platform'] == 'Win32'
            assert identity['ch']['platform'] == 'Windows'
            assert 'Linux' not in identity['ua']
        finally:
            context.close()

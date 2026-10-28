"""Headed synthetic identity acceptance. No credentials or provider traffic."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

import pytest
from camoufox.sync_api import Camoufox

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
    ch: typeof navigator.userAgentData,
    worker: await new Promise(resolve => {
        const url = URL.createObjectURL(new Blob([
            "postMessage({platform: navigator.platform, webdriver: navigator.webdriver})"
        ], {type: 'text/javascript'}));
        const worker = new Worker(url);
        const timer = setTimeout(() => { worker.terminate(); URL.revokeObjectURL(url); resolve(null); }, 3000);
        worker.onmessage = event => { clearTimeout(timer); worker.terminate(); URL.revokeObjectURL(url); resolve(event.data); };
        worker.onerror = () => { clearTimeout(timer); worker.terminate(); URL.revokeObjectURL(url); resolve(null); };
    })
})"""


@pytest.mark.skipif(not os.getenv('DISPLAY'), reason='Requires headed CI display')
@pytest.mark.parametrize('platform,expected,nav', [('windows', 'Windows', 'Win32'), ('macos', 'macOS', 'MacIntel')])
def test_headed_identity_first_request_headers_js_iframe_and_restart(tmp_path, platform, expected, nav):
    profile = generate_profile()
    profile['browser']['platform'] = platform
    snapshots = []
    with identity_origin() as origin:
        for _ in range(2):
            runtime = Camoufox(
                user_data_dir=str(tmp_path / platform), persistent_context=True,
                headless=False, os=platform, service_workers='block',
                **context_options(profile, native_window=True))
            context = runtime.__enter__()
            try:
                page = context.new_page()
                configure_page_identity(context, page, profile)
                first = page.goto(origin)
                headers = {k.lower(): v for k, v in first.request.all_headers().items()}
                observed = page.evaluate(PROBE)
                assert 'Linux' not in observed['ua'] and 'HeadlessChrome' not in observed['ua']
                assert observed['platform'] == nav
                assert observed['webdriver'] is False
                assert observed['worker'] and observed['worker']['platform'] == nav
                assert observed['language'] == 'en-US'
                assert observed['ch'] == 'undefined'
                assert 'Firefox/' in observed['ua']
                assert headers['user-agent'] == observed['ua']
                assert not any(name.startswith('sec-ch-ua') for name in headers)
                echoed = page.evaluate("fetch('/headers').then(r => r.json())")
                echoed = {k.lower(): v for k, v in echoed.items()}
                assert echoed['user-agent'] == observed['ua']
                assert not any(name.startswith('sec-ch-ua') for name in echoed)
                page.frame_locator('iframe').locator('body').wait_for()
                frame = page.frames[1].evaluate(PROBE)
                assert frame == observed
                snapshots.append(page.evaluate("({width: outerWidth, height: outerHeight, cores: navigator.hardwareConcurrency})"))
            finally:
                runtime.__exit__(None, None, None)
    assert snapshots[0] == snapshots[1]


@pytest.mark.skipif(not os.getenv('BRIDGE_BROWSERLEAKS_CHECK'), reason='Explicit external diagnostic only')
def test_browserleaks_synthetic_windows_profile(tmp_path):
    """Only public CI egress is exposed; never record the page, IP or cookies."""
    profile = generate_profile()
    with Camoufox(
        user_data_dir=str(tmp_path / 'synthetic-browserleaks'), persistent_context=True,
        headless=False, os='windows', service_workers='block',
        **context_options(profile, native_window=True),
    ) as context:

        page = context.new_page()
        configure_page_identity(context, page, profile)
        response = page.goto('https://browserleaks.com/ip', wait_until='domcontentloaded', timeout=60000)
        assert response.status == 200
        assert 'BrowserLeaks' in page.title()
        identity = page.evaluate(PROBE)
        assert identity['platform'] == 'Win32'
        assert identity['ch'] == 'undefined'
        assert 'Linux' not in identity['ua']

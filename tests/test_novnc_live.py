"""Packaged noVNC -> authenticated monitor -> websockify -> real x11vnc.

Only a synthetic task and the CI Xvfb display are used. No provider login,
recording, screenshot or browser-state export is performed.
"""

from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

import pytest

from app.crypto import load_key
from app.db import database
from app.queue import Queue
from test_browser_live import real_browser
from test_ui_live import web_server


def require_packaged_viewer():
    missing = [name for name in ("x11vnc", "websockify") if not shutil.which(name)]
    if not Path("/usr/share/novnc/vnc.html").is_file():
        missing.append("/usr/share/novnc/vnc.html")
    if not os.environ.get("DISPLAY"):
        missing.append("DISPLAY (Xvfb)")
    if missing:
        message = "Packaged noVNC smoke prerequisites missing: " + ", ".join(missing)
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_listening(process, port, log_path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"VNC transport exited ({process.returncode}): {log_path.read_text()}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    pytest.fail(f"VNC transport did not listen on {port}: {log_path.read_text()}")


@contextmanager
def packaged_vnc(settings, tmp_path):
    require_packaged_viewer()
    processes = []
    logs = []
    vnc_port = unused_port()
    websocket_port = unused_port()
    while websocket_port == vnc_port:
        websocket_port = unused_port()
    commands = [
        ["x11vnc", "-display", os.environ["DISPLAY"], "-localhost", "-rfbport",
         str(vnc_port), "-forever", "-shared", "-nopw", "-quiet"],
        ["websockify", f"127.0.0.1:{websocket_port}", f"127.0.0.1:{vnc_port}"],
    ]
    try:
        for command, port in zip(commands, (vnc_port, websocket_port)):
            log_path = tmp_path / f"{command[0]}.log"
            log = log_path.open("w")
            logs.append(log)
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_listening(process, port, log_path)
        yield replace(
            settings,
            takeover_url=f"ws://127.0.0.1:{websocket_port}/websockify",
            lease_seconds=120,
        )
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()


@contextmanager
def resizable_vnc(settings, tmp_path):
    """Real resizable desktop and maximized browser, with synthetic content only."""
    from app.browser import BROWSER_ARGS, fit_browser_window
    from app.browser_identity import context_options, generate_profile
    for executable in ("Xtigervnc", "openbox", "xprop"):
        if not shutil.which(executable):
            pytest.fail(f"Missing native resize prerequisite: {executable}")
    display = next(f":{number}" for number in range(110, 200)
                   if not Path(f"/tmp/.X11-unix/X{number}").exists())
    vnc_port, websocket_port = unused_port(), unused_port()
    while websocket_port == vnc_port:
        websocket_port = unused_port()
    env = {**os.environ, "DISPLAY": display}
    processes, logs = [], []
    commands = [
        ["Xtigervnc", display, "-geometry", "1920x1080", "-depth", "24", "-rfbport", str(vnc_port),
         "-localhost", "-SecurityTypes", "None", "-AlwaysShared", "-AcceptSetDesktopSize=1", "-nolisten", "tcp"],
        ["openbox", "--sm-disable"],
        ["websockify", f"127.0.0.1:{websocket_port}", f"127.0.0.1:{vnc_port}"],
    ]
    try:
        for index, command in enumerate(commands):
            log_path = tmp_path / f"native-{command[0]}.log"
            log = log_path.open("w")
            logs.append(log)
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            if index in (0, 2):
                wait_listening(process, vnc_port if index == 0 else websocket_port, log_path)
            else:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    result = subprocess.run(["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"], env=env, capture_output=True)
                    if b"window id" in result.stdout:
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail("Native window manager did not become ready: " + log_path.read_text())
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(tmp_path / "synthetic-native-profile"), headless=False,
                chromium_sandbox=os.geteuid() != 0, env=env,
                args=BROWSER_ARGS + ["--no-proxy-server"],
                **context_options(generate_profile(), native_window=True),
            )
            try:
                context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=
                    '<body style="margin:0;font:16px sans-serif;background:white"><p id="glyph">Synthetic 16px text</p></body>'))
                page = context.new_page()
                fit_browser_window(context, page)
                page.goto("https://synthetic.example.test/")
                yield replace(settings, takeover_url=f"ws://127.0.0.1:{websocket_port}/websockify", lease_seconds=180), page, playwright
            finally:
                context.close()
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()


def assert_native_viewer(frame, native_page):
    frame.wait_for_function("""() => {
        const canvas = document.querySelector('canvas');
        if (!canvas) return false;
        const rect = canvas.getBoundingClientRect();
        return Math.abs(canvas.width - innerWidth) <= 1 && Math.abs(canvas.height - innerHeight) <= 1
            && rect.width === canvas.width && rect.height === canvas.height
            && rect.left >= 0 && rect.left <= 1 && rect.top >= 0 && rect.top <= 1;
    }""", timeout=15000)
    viewer_size = frame.locator("canvas").evaluate("e => ({width: e.width, height: e.height})")
    native_page.wait_for_function("""size => screen.width === size.width && screen.height === size.height
        && Math.abs(outerWidth - size.width) <= 1 && Math.abs(outerHeight - size.height) <= 1""", arg=viewer_size, timeout=10000)
    assert native_page.evaluate("devicePixelRatio") == 1
    assert native_page.locator("#glyph").evaluate("e => getComputedStyle(e).fontSize") == "16px"
    assert frame.evaluate("""async () => {
        const {rfb} = await import('/account-viewer.js');
        return {readonly: rfb.viewOnly, scale: rfb.scaleViewport, resize: rfb.resizeSession};
    }""") == {"readonly": True, "scale": False, "resize": True}
    assert frame.get_by_role("status").is_hidden()
    assert frame.locator("select, button, input").count() == 0


def assert_read_only_viewer(frame):
    frame.wait_for_function("""() => {
        const canvas = document.querySelector('#noVNC_container canvas');
        return document.documentElement.classList.contains('noVNC_connected')
            && canvas && canvas.width > 0 && canvas.height > 0;
    }""", timeout=30000)
    assert frame.evaluate("""async () => {
        const {default: UI} = await import('/novnc/app/ui.js');
        return UI.rfb.viewOnly;
    }""") is True
    assert frame.locator("#noVNC_fallback_error").is_hidden()
    assert frame.locator("#noVNC_power").is_hidden()


@contextmanager
def viewer_browser(engine, driver=None):
    if driver is not None:
        options = {"headless": True}
        if engine == "chromium":
            options["chromium_sandbox"] = os.geteuid() != 0
        browser = getattr(driver, engine).launch(**options)
        try:
            yield browser
        finally:
            browser.close()
    elif engine == "chromium":
        with real_browser() as browser:
            yield browser
    else:
        with sync_playwright() as playwright:
            browser = playwright.webkit.launch(headless=True)
            try:
                yield browser
            finally:
                browser.close()


@pytest.mark.parametrize("viewer", ["direct", "account-popup"])
@pytest.mark.parametrize("engine", ["chromium", pytest.param("webkit", marks=pytest.mark.skipif(
    not os.getenv("BRIDGE_TEST_WEBKIT"), reason="Enable installed WebKit acceptance explicitly",
))])
def test_packaged_novnc_connects_read_only_without_pausing_task(settings, resources, tmp_path, viewer, engine):
    account, target = resources
    transport = resizable_vnc if viewer == "account-popup" else packaged_vnc
    with transport(settings, tmp_path) as transport_result:
        config, native_page, driver = transport_result if viewer == "account-popup" else (transport_result, None, None)
        if viewer == "account-popup" and not Path("frontend/dist/index.html").is_file():
            if os.environ.get("CI"):
                pytest.fail("Build the frontend before account popup acceptance")
            pytest.skip("Build the frontend before account popup acceptance")
        queue = Queue(config, load_key(config.key_file))
        task = queue.create(account, target)
        claim = queue.claim()
        queue.update(task["id"], claim["execution_id"], state="running", takeover_available=1)
        with web_server(config) as url, viewer_browser(engine, driver) as browser:
            # A non-loopback HTTP hostname exercises LAN cookie/site behavior.
            if os.getenv("BRIDGE_TEST_LAN_HOST"):
                url = url.replace("127.0.0.1", os.environ["BRIDGE_TEST_LAN_HOST"])
            context = browser.new_context(service_workers="block")
            failed_assets = []
            # Debian omits optional version metadata; noVNC catches that 404.
            # Authentication errors, including on this URL, must still fail.
            context.on("response", lambda response: failed_assets.append(
                (response.url, response.status)
            ) if "/novnc/" in response.url and response.status >= 400 and not (
                response.url.endswith("/novnc/package.json") and response.status == 404
            ) else None)
            try:
                response = context.request.post(
                    url + "/api/v1/auth/login",
                    data={"password": "synthetic-password-123"},
                )
                assert response.status == 200
                page = context.new_page()
                if viewer == "direct":
                    query = urlencode({
                        "autoconnect": "true", "shared": "true", "view_only": "true",
                        "resize": "off", "path": f"api/v1/tasks/{task['id']}/monitor",
                    })
                    page.goto(f"{url}/novnc/vnc.html?{query}")
                    assert_read_only_viewer(page)
                else:
                    page.goto(url)
                    page.get_by_role("button", name="账号", exact=True).click()
                    card = page.locator("article.resource").filter(
                        has=page.get_by_role("heading", name="test@example.com", exact=True),
                    )
                    with page.expect_popup() as opened:
                        card.get_by_role("button", name="账号窗口", exact=True).click()
                    popup = opened.value
                    popup.wait_for_url("**/account-window")
                    assert popup.evaluate("window.opener") is None
                    iframe = popup.locator('iframe[title="账号浏览器"]')
                    iframe.wait_for(state="attached")
                    assert f"api/v1/tasks/{task['id']}/monitor" in iframe.get_attribute("src")
                    frame = iframe.element_handle().content_frame()
                    assert frame is not None
                    assert native_page is not None
                    for width, height in ((1100, 900), (1400, 760), (900, 1000)):
                        popup.set_viewport_size({"width": width, "height": height})
                        assert_native_viewer(frame, native_page)
                    popup.close()
                assert failed_assets == []
                with database(config.db_path) as conn:
                    row = conn.execute(
                        "SELECT state,execution_id,takeover_requested,cancel_requested FROM tasks WHERE id=?",
                        (task["id"],),
                    ).fetchone()
                    assert row["state"] == "running"
                    assert row["execution_id"] == claim["execution_id"]
                    assert row["takeover_requested"] == 0
                    assert row["cancel_requested"] == 0
                    assert conn.execute(
                        "SELECT count(*) FROM tasks WHERE account_id=?", (account,),
                    ).fetchone()[0] == 1
            finally:
                context.close()

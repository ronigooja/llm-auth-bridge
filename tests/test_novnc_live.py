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


@pytest.mark.parametrize("viewer", ["direct", "account-popup"])
def test_packaged_novnc_connects_read_only_without_pausing_task(settings, resources, tmp_path, viewer):
    account, target = resources
    with packaged_vnc(settings, tmp_path) as config:
        if viewer == "account-popup" and not Path("frontend/dist/index.html").is_file():
            if os.environ.get("CI"):
                pytest.fail("Build the frontend before account popup acceptance")
            pytest.skip("Build the frontend before account popup acceptance")
        queue = Queue(config, load_key(config.key_file))
        task = queue.create(account, target)
        claim = queue.claim()
        queue.update(task["id"], claim["execution_id"], state="running", takeover_available=1)
        with web_server(config) as url, real_browser() as browser:
            context = browser.new_context(service_workers="block")
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
                    assert popup.evaluate("window.opener") is None
                    iframe = popup.locator('iframe[title="账号浏览器"]')
                    iframe.wait_for(state="attached")
                    assert f"api/v1/tasks/{task['id']}/monitor" in iframe.get_attribute("src")
                    frame = iframe.element_handle().content_frame()
                    assert frame is not None
                    assert_read_only_viewer(frame)
                    popup.close()
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

"""Real authenticated WebSocket transport against a synthetic RFB server."""

from contextlib import contextmanager
from dataclasses import replace
import struct
import threading

import httpx
import pytest
from websockets.sync.server import serve
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.crypto import load_key
from app.db import database
from app.queue import Queue
from test_ui_live import web_server


@contextmanager
def monitor_server(settings, resources, state="running", kind="login"):
    account, target = resources
    received = []
    framebuffer = b"\x00\0\0\0"  # Empty FramebufferUpdate

    def rfb(socket):
        try:
            socket.send(b"RFB 003.008\n")
            assert socket.recv() == b"RFB 003.008\n"
            socket.send(b"\x01\x01")
            assert socket.recv() == b"\x01"
            socket.send(b"\0\0\0\0")
            assert socket.recv() == b"\x01"
            socket.send(struct.pack(">HH", 1024, 768) + bytes([32, 24, 0, 1])
                        + struct.pack(">HHHBBB3x", 255, 255, 255, 16, 8, 0)
                        + struct.pack(">I", 9) + b"Synthetic")
            for data in socket:
                received.append(data)
                socket.send(framebuffer)
        except ConnectionClosed:
            pass

    with serve(rfb, "127.0.0.1", 0) as upstream:
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        config = replace(settings, takeover_url=f"ws://127.0.0.1:{upstream.socket.getsockname()[1]}")
        queue = Queue(config, load_key(config.key_file))
        task = queue.create(account, target)
        claim = queue.claim()
        queue.update(task["id"], claim["execution_id"], state=state, takeover_available=1)
        with database(config.db_path) as conn:
            conn.execute("UPDATE tasks SET kind=? WHERE id=?", (kind, task["id"]))
        try:
            with web_server(config) as url, httpx.Client(base_url=url, trust_env=False) as client:
                login = client.post("/api/v1/auth/login", json={"password": "synthetic-password-123"})
                assert login.status_code == 200
                cookie = client.cookies.get("bridge_session")
                client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                endpoint = url.replace("http:", "ws:") + f"/api/v1/tasks/{task['id']}/monitor"
                yield endpoint, url, cookie, client, config, task, received, framebuffer
        finally:
            upstream.shutdown()
            thread.join(3)


def handshake(socket):
    assert socket.recv(timeout=3) == b"RFB 003.008\n"
    socket.send(b"RFB 003.")
    socket.send(b"008\n")
    assert socket.recv(timeout=3) == b"\x01\x01"
    socket.send(b"\x01")
    assert socket.recv(timeout=3) == b"\0\0\0\0"
    socket.send(b"\x01")
    assert socket.recv(timeout=3).endswith(b"Synthetic")


@pytest.mark.parametrize("state,kind", [
    ("running", "login"), ("waiting_human", "login"),
    ("waiting_human", "browser_window"),
])
def test_monitor_handshake_framebuffer_and_forbidden_input(settings, resources, state, kind):
    with monitor_server(settings, resources, state, kind) as (endpoint, url, cookie, _, config, task, received, framebuffer):
        with connect(endpoint, origin=url, additional_headers={"Cookie": f"bridge_session={cookie}"}) as socket:
            handshake(socket)
            update = struct.pack(">BBHHHH", 3, 1, 0, 0, 1024, 768)
            socket.send(update[:4])
            socket.send(update[4:])
            assert socket.recv(timeout=3) == framebuffer
            assert received == [update]
            with database(config.db_path) as conn:
                assert conn.execute("SELECT state FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == state
            socket.send(b"\x04\x01\0\0\0\0\0a")
            with pytest.raises(ConnectionClosed):
                socket.recv(timeout=3)
            assert received == [update]


@pytest.mark.parametrize("change", ["logout", "cancel", "lease", "owner", "account", "finished", "unavailable"])
def test_idle_monitor_is_revoked(settings, resources, change):
    with monitor_server(settings, resources) as (endpoint, url, cookie, client, config, task, _, _):
        with connect(endpoint, origin=url, additional_headers={"Cookie": f"bridge_session={cookie}"}) as socket:
            handshake(socket)
            if change == "logout":
                assert client.post("/api/v1/auth/logout").status_code == 200
            else:
                assignments = {
                    "cancel": "cancel_requested=1",
                    "lease": "lease_until=0",
                    "owner": "execution_id='replacement-execution'",
                    "account": "account_id=account_id+1000",
                    "finished": "state='succeeded'",
                    "unavailable": "takeover_available=0",
                }
                with database(config.db_path) as conn:
                    if change == "account":
                        # A second synthetic account tests identity pinning without
                        # violating foreign keys.
                        account = client.post("/api/v1/accounts", json={"username": "other@example.test", "password": "synthetic", "route_type": "direct", "target_ids": []})
                        assert account.status_code == 200
                        assignments[change] = f"account_id={account.json()['id']}"
                    conn.execute(f"UPDATE tasks SET {assignments[change]} WHERE id=?", (task["id"],))
            with pytest.raises(ConnectionClosed):
                socket.recv(timeout=3)


@pytest.mark.parametrize("case", [
    "no-cookie", "no-origin", "foreign-origin", "wrong-task", "takeover-running",
    "queued", "unowned", "expired", "cancelled", "unavailable",
])
def test_monitor_denies_unauthorized_and_wrong_task(settings, resources, case):
    with monitor_server(settings, resources) as (endpoint, url, cookie, _, config, task, _, _):
        assignments = {
            "queued": "state='queued'", "unowned": "execution_id=NULL",
            "expired": "lease_until=0", "cancelled": "cancel_requested=1",
            "unavailable": "takeover_available=0",
        }
        if case in assignments:
            with database(config.db_path) as conn:
                conn.execute(f"UPDATE tasks SET {assignments[case]} WHERE id=?", (task["id"],))
        origin = None if case == "no-origin" else "https://foreign.example" if case == "foreign-origin" else url
        headers = {} if case == "no-cookie" else {"Cookie": f"bridge_session={cookie}"}
        if case == "wrong-task":
            endpoint = endpoint.replace(f"/{task['id']}/monitor", f"/{task['id'] + 9999}/monitor")
        if case == "takeover-running":
            endpoint = endpoint.replace("/monitor", "/takeover")
        with pytest.raises(InvalidStatus):
            with connect(endpoint, origin=origin, additional_headers=headers):
                pytest.fail("unauthorized account window was accepted")

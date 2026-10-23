"""Authenticated binary takeover tunnel and revocation against a local echo server."""

from dataclasses import replace
import threading
import time
import httpx
import pytest
from websockets.sync.server import serve
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed
from app.queue import Queue
from app.crypto import load_key
from test_ui_live import web_server


def test_websocket_tunnel_revoked_on_logout(settings, resources):
    a, t = resources

    def echo(socket):
        for data in socket:
            socket.send(data)

    with serve(echo, "127.0.0.1", 0) as upstream:
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        port = upstream.socket.getsockname()[1]
        settings = replace(settings, takeover_url=f"ws://127.0.0.1:{port}")
        q = Queue(settings, load_key(settings.key_file))
        task = q.create(a, t)
        claim = q.claim()
        q.update(
            task["id"],
            claim["execution_id"],
            state="waiting_human",
            takeover_available=1,
        )
        try:
            with (
                web_server(settings) as url,
                httpx.Client(base_url=url, trust_env=False) as client,
            ):
                login = client.post(
                    "/api/v1/auth/login", json={"password": "synthetic-password-123"}
                )
                assert login.status_code == 200
                cookie = client.cookies.get("bridge_session")
                with connect(
                    url.replace("http:", "ws:")
                    + f"/api/v1/tasks/{task['id']}/takeover",
                    origin=url,
                    additional_headers={"Cookie": f"bridge_session={cookie}"},
                    open_timeout=3,
                ) as socket:
                    socket.send(b"synthetic-rfb-bytes")
                    assert socket.recv(timeout=3) == b"synthetic-rfb-bytes"
                    assert (
                        client.post(
                            "/api/v1/auth/logout",
                            headers={"X-CSRF-Token": login.json()["csrf_token"]},
                        ).status_code
                        == 200
                    )
                    with pytest.raises(ConnectionClosed):
                        socket.recv(timeout=3)
        finally:
            upstream.shutdown()
            thread.join(3)

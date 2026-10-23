"""Real local routing acceptance using release GOST; never uses real accounts."""

from contextlib import contextmanager
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import os
import shutil
import socket
import threading
import httpx
import pytest
from app.routing import account_route


@contextmanager
def server(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(2)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def gost(monkeypatch):
    executable = os.getenv("BRIDGE_TEST_GOST") or shutil.which("gost")
    if not executable:
        pytest.skip("GOST release executable is not installed")
    monkeypatch.setattr("app.routing.shutil.which", lambda name: executable)
    return executable


def test_real_gost_http_proxy_and_credentials_do_not_fall_back(gost):
    received = []
    origin_hits = []

    class Proxy(QuietHandler):
        def do_CONNECT(self):
            received.append((self.path, self.headers.get("Proxy-Authorization")))
            self.send_response(200)
            self.end_headers()
            while self.rfile.readline().strip():
                pass
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 19\r\nConnection: close\r\n\r\nvia synthetic proxy"
            )

        def do_GET(self):
            received.append((self.path, self.headers.get("Proxy-Authorization")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"via synthetic proxy")

    class Origin(QuietHandler):
        def do_GET(self):
            origin_hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"direct")

    with server(Proxy) as proxy, server(Origin) as origin:
        endpoint = f"http://127.0.0.1:{origin.server_port}/observe"
        account = {
            "route_type": "proxy",
            "proxy": {
                "server": f"http://127.0.0.1:{proxy.server_port}",
                "username": "synthetic",
                "password": "secret",
            },
        }
        with account_route(account) as route:
            response = route.session.get(endpoint, timeout=5)
            assert response.text == "via synthetic proxy"
            assert (
                received
                and received[0][0] == f"127.0.0.1:{origin.server_port}"
                and received[0][1] == "Basic c3ludGhldGljOnNlY3JldA=="
            )
            assert origin_hits == []
    # The same reachable origin must not be contacted when upstream is down.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    with server(Origin) as origin:
        account["proxy"]["server"] = f"http://127.0.0.1:{dead_port}"
        with account_route(account) as route:
            try:
                response = route.session.get(
                    f"http://127.0.0.1:{origin.server_port}/must-not-connect", timeout=3
                )
            except httpx.HTTPError:
                pass
            else:
                assert response.status_code >= 400
        assert origin_hits == []

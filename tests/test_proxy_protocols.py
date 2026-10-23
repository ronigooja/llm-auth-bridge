"""Synthetic local protocol coverage for account_route's GOST bridge."""
import base64
import os
import shutil
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.routing import account_route


GOST = os.environ.get("BRIDGE_TEST_GOST") or shutil.which("gost")
pytestmark = pytest.mark.skipif(not GOST, reason="set BRIDGE_TEST_GOST to a GOST v3 binary")


@pytest.fixture(autouse=True)
def _gost_on_path(monkeypatch):
    monkeypatch.setenv("PATH", os.path.dirname(os.path.abspath(GOST)) + os.pathsep + os.environ.get("PATH", ""))


def _listener(handler, *, tls_context=None):
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)
    result = {}

    def run():
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5)
                if tls_context:
                    conn = tls_context.wrap_socket(conn, server_side=True)
                with conn:
                    handler(conn, result)
        except Exception as exc:  # surfaced in the test thread result
            result["error"] = exc
        finally:
            server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return server.getsockname()[1], result, thread


def _read_headers(sock):
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 16384:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _http_reply(sock):
    sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")


def _socks_handler(sock, result):
    version, count = sock.recv(2)
    methods = sock.recv(count)
    assert version == 5 and 2 in methods
    sock.sendall(b"\x05\x02")
    ver, ulen = sock.recv(2)
    user = sock.recv(ulen)
    plen = sock.recv(1)[0]
    password = sock.recv(plen)
    result["auth"] = (user, password)
    sock.sendall(b"\x01\x00")
    header = sock.recv(4)
    atyp = header[3]
    if atyp == 3:
        length = sock.recv(1)[0]
        host = sock.recv(length).decode()
    elif atyp == 1:
        host = socket.inet_ntoa(sock.recv(4))
    else:
        raise AssertionError(f"unexpected SOCKS address type {atyp}")
    port = int.from_bytes(sock.recv(2), "big")
    result["target"] = (host, port)
    sock.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
    result["request"] = _read_headers(sock)
    _http_reply(sock)


def _synthetic_tls_context(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "proxy-cert.pem", tmp_path / "proxy-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert_path


def _connect_handler(sock, result):
    request = _read_headers(sock)
    result["connect"] = request
    sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
    result["request"] = _read_headers(sock)
    _http_reply(sock)


def test_account_route_uses_authenticated_socks5_and_does_not_fallback():
    port, result, thread = _listener(_socks_handler)
    account = {"route_type": "proxy", "proxy": {"server": f"socks5://127.0.0.1:{port}", "username": "fixture-user", "password": "fixture-pass"}}
    with account_route(account) as route:
        response = route.session.get("http://never-resolve.invalid:8123/probe")
        assert route.playwright_proxy["server"].startswith("http://127.0.0.1:")
    thread.join(5)
    assert not thread.is_alive()
    assert "error" not in result
    assert result["auth"] == (b"fixture-user", b"fixture-pass")
    assert result["target"] == ("never-resolve.invalid", 8123)
    assert result["request"].startswith(b"GET /probe ")
    assert response.status_code == 200 and response.text == "ok"


def test_account_route_uses_tls_http_connect_proxy(tmp_path, monkeypatch):
    context, cert_path = _synthetic_tls_context(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(cert_path))
    port, result, thread = _listener(_connect_handler, tls_context=context)
    account = {"route_type": "proxy", "proxy": {"server": f"https://localhost:{port}", "username": "tls-user", "password": "tls-pass"}}
    with account_route(account) as route:
        response = route.session.get("http://never-resolve.invalid:8124/probe")
    thread.join(5)
    assert not thread.is_alive()
    assert "error" not in result
    connect = result["connect"].lower()
    assert connect.startswith(b"connect never-resolve.invalid:8124 ")
    assert b"proxy-authorization: basic " + base64.b64encode(b"tls-user:tls-pass").lower() in connect
    assert result["request"].startswith(b"GET /probe ")
    assert response.status_code == 200 and response.text == "ok"

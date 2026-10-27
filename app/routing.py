"""Explicit account routing. No request inherits ambient proxy variables."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import httpx


class RouteError(RuntimeError):
    pass


@dataclass
class Route:
    playwright_proxy: dict | None
    session: httpx.Client


def _proxy_config(proxy: dict) -> tuple[str, str, int, str | None, str | None]:
    try:
        parsed = urlsplit(proxy["server"])
        if (
            parsed.scheme not in ("http", "https", "socks5")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError
        return (
            parsed.scheme,
            parsed.hostname,
            parsed.port
            or (
                443
                if parsed.scheme == "https"
                else 1080
                if parsed.scheme == "socks5"
                else 80
            ),
            proxy.get("username"),
            proxy.get("password"),
        )
    except (KeyError, ValueError, TypeError):
        raise RouteError("Invalid account proxy configuration") from None


@contextmanager
def account_route(account: dict):
    mode = account.get("route_type")
    if mode not in ("direct", "proxy"):
        raise RouteError("An explicit direct or proxy route is required")
    if mode == "direct":
        with httpx.Client(
            trust_env=False, timeout=30, follow_redirects=False
        ) as session:
            yield Route(None, session)
        return
    scheme, host, port, username, password = _proxy_config(account.get("proxy") or {})
    gost = shutil.which("gost")
    if not gost:
        raise RouteError("Proxy routing requires the GOST v3 executable")
    # GOST makes one local HTTP proxy usable by both Chromium and httpx,
    # including authenticated SOCKS5, which Chromium does not support natively.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    local_port = listener.getsockname()[1]
    listener.close()
    auth = {"username": username or "", "password": password or ""}
    node = {
        "name": "upstream",
        "addr": f"[{host}]:{port}" if ":" in host else f"{host}:{port}",
        "connector": {"type": "socks5" if scheme == "socks5" else "http"},
        "dialer": {"type": "tls" if scheme == "https" else "tcp"},
    }
    if scheme == "https":
        node["dialer"]["tls"] = {"serverName": host, "secure": True}
    if username is not None or password is not None:
        node["connector"]["auth"] = auth
    config = {
        "services": [
            {
                "name": "account",
                "addr": f"127.0.0.1:{local_port}",
                "handler": {"type": "http", "chain": "account"},
                "listener": {"type": "tcp"},
            }
        ],
        "chains": [
            {"name": "account", "hops": [{"name": "upstream", "nodes": [node]}]}
        ],
    }
    with tempfile.TemporaryDirectory(prefix="bridge-route-") as directory:
        os.chmod(directory, 0o700)
        path = Path(directory) / "route.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(config, stream)
        process = None
        try:
            try:
                process = subprocess.Popen(
                    [gost, "-C", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                raise RouteError("Account proxy could not start") from None
            for _ in range(100):
                if process.poll() is not None:
                    raise RouteError("Account proxy could not start")
                try:
                    with socket.create_connection(
                        ("127.0.0.1", local_port), timeout=0.05
                    ):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RouteError("Account proxy did not become ready")
            endpoint = f"http://127.0.0.1:{local_port}"
            with httpx.Client(
                proxy=endpoint, trust_env=False, timeout=30, follow_redirects=False
            ) as session:
                yield Route({"server": endpoint}, session)
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

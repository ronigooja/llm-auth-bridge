import pytest
import app.routing as routing


@pytest.mark.parametrize(
    "account",
    [
        {},
        {"route_type": "unset"},
        {"route_type": "proxy"},
        {"route_type": "proxy", "proxy": {"server": "file:///etc/passwd"}},
        {
            "route_type": "proxy",
            "proxy": {"server": "http://user:password@proxy.example"},
        },
    ],
)
def test_explicit_route_fail_closed(account):
    with pytest.raises(routing.RouteError):
        with routing.account_route(account):
            pytest.fail("must not yield an invalid route")


def test_direct_disables_ambient_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")
    with routing.account_route({"route_type": "direct"}) as route:
        assert route.playwright_proxy is None
        assert route.session._trust_env is False


def test_route_consumer_oserror_is_not_mislabeled_as_proxy_failure(monkeypatch):
    monkeypatch.setattr(routing.shutil, "which", lambda _: "/synthetic/gost")

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(routing.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(routing.socket, "create_connection", lambda *a, **k: None)
    with pytest.raises(OSError, match="consumer failure"):
        with routing.account_route(
            {"route_type": "proxy", "proxy": {"server": "socks5://proxy.example:1080"}}
        ):
            raise OSError("consumer failure")


def test_proxy_never_falls_back_when_gost_missing(monkeypatch):
    monkeypatch.setattr(routing.shutil, "which", lambda _: None)
    with pytest.raises(routing.RouteError, match="GOST"):
        with routing.account_route(
            {
                "route_type": "proxy",
                "proxy": {
                    "server": "socks5://proxy.example:1080",
                    "password": "synthetic-secret",
                },
            }
        ):
            pytest.fail("must not fall back to direct")


@pytest.mark.parametrize("scheme", ["http", "https", "socks5"])
def test_gost_credentials_only_in_restricted_config(monkeypatch, scheme):
    import json
    import os
    from contextlib import contextmanager
    from pathlib import Path

    observed = {}
    monkeypatch.setattr(routing.shutil, "which", lambda _: "/synthetic/gost")

    class Process:
        def poll(self):
            return None

        def terminate(self):
            observed["terminated"] = True

        def wait(self, timeout=None):
            return 0

    def launch(args, **kwargs):
        assert "synthetic-secret" not in " ".join(args)
        path = Path(args[-1])
        observed["config"] = json.loads(path.read_text())
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert os.stat(path.parent).st_mode & 0o777 == 0o700
        observed["path"] = path
        return Process()

    @contextmanager
    def connection(*a, **k):
        yield None

    monkeypatch.setattr(routing.subprocess, "Popen", launch)
    monkeypatch.setattr(routing.socket, "create_connection", connection)
    with routing.account_route(
        {
            "route_type": "proxy",
            "proxy": {
                "server": scheme + "://proxy.example:8443",
                "username": "synthetic-user",
                "password": "synthetic-secret",
            },
        }
    ) as route:
        assert route.playwright_proxy["server"].startswith("http://127.0.0.1:")
        assert route.session._trust_env is False
    node = observed["config"]["chains"][0]["hops"][0]["nodes"][0]
    assert node["connector"]["auth"]["password"] == "synthetic-secret"
    if scheme == "https":
        assert node["dialer"]["tls"] == {"secure": True, "serverName": "proxy.example"}
    assert observed["terminated"]
    assert not observed["path"].exists()

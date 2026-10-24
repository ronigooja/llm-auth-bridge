"""Opt-in real HTTP contract acceptance against a disposable synthetic server.

Never point this at a production account store. This test deliberately updates a
synthetic record and leaves it in the disposable store. No provider is contacted
by this client. Run the target with outbound provider traffic blocked as well.
"""

import copy
import os

import httpx
import pytest

from app.integrations import (
    IntegrationError,
    _digest,
    sync_credential,
    test_connection as connection,
)


class RecordingTransport(httpx.BaseTransport):
    def __init__(self):
        self.inner = httpx.HTTPTransport(trust_env=False)
        self.requests = []
        self.lose_next_write_response = False

    def handle_request(self, request):
        assert "/bridge/v1/" in request.url.path
        self.requests.append((request.method, request.url.path))
        response = self.inner.handle_request(request)
        if request.method == "PUT" and self.lose_next_write_response:
            self.lose_next_write_response = False
            response.read()
            response.close()
            raise httpx.ReadTimeout("synthetic lost write response", request=request)
        return response

    def close(self):
        # Each bridge adapter closes its client. Keep the shared transport alive
        # across these calls; the test explicitly closes it in its finalizer.
        pass


def test_disposable_voice_bridge_real_http_contract():
    url = os.environ.get("BRIDGE_VOICE_ACCEPTANCE_URL")
    if not url:
        pytest.skip("set BRIDGE_VOICE_ACCEPTANCE_URL for a disposable synthetic server")
    if os.environ.get("BRIDGE_VOICE_ACCEPTANCE_DISPOSABLE") != "1":
        pytest.fail("confirm the dedicated disposable server with BRIDGE_VOICE_ACCEPTANCE_DISPOSABLE=1")
    target = {
        "kind": "chatgpt-web-voice",
        "config": {
            "base_url": url,
            "allow_http": True,
            "admin_username": "synthetic-user",
            "admin_password": "synthetic-password",
            "compatibility": "bridge-v1",
        },
    }
    account = {"username": "bridge-acceptance@example.test", "route_type": "direct"}
    result = {
        "credential_type": "chatgpt_web",
        "identity": account["username"],
        "expires_at": 1800000000,
        "credential": {"access_token": "synthetic-acceptance-token"},
    }
    transport = RecordingTransport()

    def sync(value=result, route=account, remote_id=None):
        return sync_credential(
            target, value, route, remote_id, _transport=transport, _sleep=lambda _: None
        )

    def writes():
        return sum(method == "PUT" for method, _ in transport.requests)

    try:
        base = url.rstrip("/")
        absent_path = "/bridge/v1/accounts/bridge-" + "0" * 32
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False) as client:
            for auth in (None, ("synthetic-user", "synthetic-wrong-password")):
                for method, path in (
                    ("GET", "/bridge/v1/capabilities"),
                    ("GET", absent_path),
                    ("PUT", absent_path),
                ):
                    assert client.request(method, base + path, auth=auth).status_code == 401
            client.auth = ("synthetic-user", "synthetic-password")
            assert client.get(base + absent_path).status_code == 404
            assert client.put(base + absent_path, content=b"{invalid").status_code in {400, 422}
            assert client.put(base + absent_path, content=b" " * (2 * 1024 * 1024)).status_code in {400, 413}
        assert connection(target, _transport=transport)["verification"] == "unverified"
        first = sync()
        assert first["verified"] is True
        assert first["remote_id"].startswith("bridge-")
        before = writes()
        assert sync() == first
        assert writes() == before

        payload = {**result, "route": {"type": "direct"}}
        key = first["remote_id"] + "-" + _digest(payload)
        path = base + "/bridge/v1/accounts/" + first["remote_id"]
        with httpx.Client(
            transport=transport,
            auth=("synthetic-user", "synthetic-password"),
            trust_env=False,
        ) as client:
            assert client.put(path, json=payload, headers={"Idempotency-Key": key}).is_success
            different = {**payload, "credential": {"access_token": "synthetic-other-token"}}
            assert client.put(path, json=different, headers={"Idempotency-Key": key}).status_code == 409
            different_identity = {**payload, "identity": "other-synthetic@example.test"}
            assert client.put(
                path, json=different_identity,
                headers={"Idempotency-Key": first["remote_id"] + "-" + _digest(different_identity)},
            ).status_code == 409
            # A different stable ID must not duplicate or steal this token's row.
            assert client.put(
                base + absent_path, json=different_identity,
                headers={"Idempotency-Key": absent_path.rsplit("/", 1)[-1] + "-" + _digest(different_identity)},
            ).status_code == 409
        before = writes()

        # A single synthetic string tests Python-compatible UTF-8 JSON hashing,
        # including Go's default HTML and Unicode separator escaping pitfalls.
        updated = copy.deepcopy(result)
        updated["credential"]["access_token"] = "synthetic-<&>-测试-\u2028\u2029"
        updated["credential"]["device_id"] = "synthetic-device-id"
        proxy = {
            **account,
            "route_type": "proxy",
            "proxy": {
                "server": "socks5h://proxy.example.test:1080",
                "username": "synthetic@user",
                "password": "synthetic:/password",
            },
        }
        transport.lose_next_write_response = True
        assert sync(updated, proxy, first["remote_id"]) == first
        assert writes() == before + 1

        # A historical write may have committed before a remote token changed.
        historical = {**result, "_reconcile_only": True}
        before = writes()
        with pytest.raises(IntegrationError, match="avoid overwriting rotated credentials") as exc:
            sync(historical, account, first["remote_id"])
        assert exc.value.write_possible is True
        assert writes() == before

        other_account = {**account, "username": "other-synthetic@example.test"}
        other = {**result, "identity": other_account["username"]}
        with pytest.raises(IntegrationError, match="identity differs"):
            sync(other, other_account, first["remote_id"])
        assert writes() == before

        # A fresh authorization can replace this identity's credential and route.
        # Restore the initial direct fixture so the test can run repeatedly.
        assert sync(result, account, first["remote_id"]) == first
    finally:
        transport.inner.close()

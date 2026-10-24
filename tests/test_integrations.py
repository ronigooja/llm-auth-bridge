import json

import httpx
import pytest

from app.integrations import (
    IntegrationError,
    _digest,
    sync_credential,
    test_connection as connection,
)


@pytest.fixture
def account():
    return {"username": "synthetic@example.test", "route_type": "direct"}


@pytest.fixture
def cpa():
    return {
        "kind": "cliproxyapi",
        "config": {
            "base_url": "https://target.test",
            "management_key": "synthetic-admin",
        },
    }


@pytest.fixture
def result(account):
    return {
        "credential_type": "codex_oauth",
        "identity": account["username"],
        "expires_at": 1800000000,
        "credential": {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "id_token": "synthetic-id",
            "account_id": "synthetic-account",
        },
    }


class CPA:
    def __init__(self):
        self.files = {}
        self.requests = []
        self.lose_response = False
        self.alter = None

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-admin"
        assert request.url.host == "target.test"
        name = request.url.params.get("name")
        if request.method == "POST":
            payload = json.loads(request.content)
            if self.alter:
                payload = self.alter(payload)
            self.files[name] = payload
            if self.lose_response:
                raise httpx.ReadTimeout(
                    "synthetic-secret-must-never-escape", request=request
                )
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path.endswith("download"):
            return (
                httpx.Response(200, json=self.files[name])
                if name in self.files
                else httpx.Response(404)
            )
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "name": filename,
                        "email": payload.get("email"),
                        "type": payload.get("type"),
                    }
                    for filename, payload in self.files.items()
                ]
            },
        )


def run(cpa, result, account, server, rid=None):
    return sync_credential(
        cpa,
        result,
        account,
        rid,
        _transport=httpx.MockTransport(server),
        _sleep=lambda _: None,
    )


def test_cpa_upload_readback_and_repeat(cpa, result, account):
    server = CPA()
    first = run(cpa, result, account, server)
    assert first["verified"] is True
    assert first["remote_id"].endswith(".json")
    record = server.files[first["remote_id"]]
    assert record["proxy_url"] == "direct"
    assert record["type"] == "codex"
    assert record["expired"].endswith("Z")
    assert run(cpa, result, account, server) == first
    assert len([r for r in server.requests if r.method == "POST"]) == 1
    assert len(server.files) == 1
    assert result["credential"]["refresh_token"] == "synthetic-refresh"


def test_existing_remote_id_updated_not_duplicated(cpa, result, account):
    server = CPA()
    server.files["existing.json"] = {
        "type": "codex",
        "email": account["username"],
        "access_token": "old",
    }
    assert (
        run(cpa, result, account, server, "existing.json")["remote_id"]
        == "existing.json"
    )
    assert list(server.files) == ["existing.json"]


def test_existing_cpa_email_file_reused_without_local_sync_id(cpa, result, account):
    server = CPA()
    legacy = "codex-legacy-account-plus.json"
    server.files[legacy] = {
        "type": "codex",
        "email": account["username"],
        "access_token": "old",
        "priority": 7,
        "weight": 3,
        "disabled": True,
    }
    assert run(cpa, result, account, server)["remote_id"] == legacy
    assert list(server.files) == [legacy]
    assert {key: server.files[legacy][key] for key in ("priority", "weight", "disabled")} == {
        "priority": 7,
        "weight": 3,
        "disabled": True,
    }


@pytest.mark.parametrize("files", [None, {}, "invalid"])
def test_first_sync_fails_closed_on_incompatible_auth_file_listing(
    cpa, result, account, files
):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("auth-files"):
            return httpx.Response(200, json={"files": files})
        pytest.fail("an incompatible listing must stop before any write")

    with pytest.raises(IntegrationError, match="incompatible"):
        sync_credential(cpa, result, account, _transport=httpx.MockTransport(handler))
    assert not any(request.method == "POST" for request in requests)


def test_first_sync_fails_closed_on_multiple_identity_matches(cpa, result, account):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("auth-files"):
            return httpx.Response(
                200,
                json={
                    "files": [
                        {"name": "legacy-a.json", "email": account["username"], "type": "codex"},
                        {"name": "legacy-b.json", "email": account["username"], "type": "codex"},
                    ]
                },
            )
        pytest.fail("ambiguous account identity must stop before download/write")

    with pytest.raises(IntegrationError, match="Multiple remote credentials"):
        sync_credential(cpa, result, account, _transport=httpx.MockTransport(handler))
    assert not any(request.method == "POST" for request in requests)


def test_lost_write_response_reconciles_without_duplicate(cpa, result, account):
    server = CPA()
    server.lose_response = True
    assert run(cpa, result, account, server)["verified"] is True
    assert len([r for r in server.requests if r.method == "POST"]) == 1


def test_conflicting_remote_identity_is_not_overwritten(cpa, result, account):
    server = CPA()
    server.files["existing.json"] = {"type": "codex", "email": "different@example.test"}
    with pytest.raises(IntegrationError, match="identity differs"):
        run(cpa, result, account, server, "existing.json")
    assert not any(r.method == "POST" for r in server.requests)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: {**p, "proxy_url": ""},
        lambda p: {**p, "access_token": "wrong"},
        lambda p: {**p, "account_id": "wrong"},
        lambda p: {**p, "email": "wrong"},
    ],
)
def test_readback_mismatch_fails_closed(cpa, result, account, change):
    server = CPA()
    server.alter = change
    with pytest.raises(IntegrationError):
        run(cpa, result, account, server)
    assert len([r for r in server.requests if r.method == "POST"]) <= 2


def test_proxy_credentials_encoded_and_verified(cpa, result, account):
    account.update(
        route_type="proxy",
        proxy={
            "server": "socks5h://proxy.test:1080",
            "username": "u@",
            "password": "p:/",
        },
    )
    server = CPA()
    remote = run(cpa, result, account, server)
    assert (
        server.files[remote["remote_id"]]["proxy_url"]
        == "socks5h://u%40:p%3A%2F@proxy.test:1080"
    )


@pytest.mark.parametrize(
    "route,proxy",
    [
        ("unset", None),
        ("proxy", {}),
        ("proxy", {"server": "http://user:secret@proxy.test"}),
        ("proxy", {"server": "http://proxy.test:0"}),
    ],
)
def test_implicit_or_invalid_route_rejected(cpa, result, account, route, proxy):
    account.update(route_type=route, proxy=proxy)
    with pytest.raises(IntegrationError):
        run(cpa, result, account, CPA())


@pytest.mark.parametrize(
    "bad", ["../outside.json", "secret?key.json", "not-json", "a/b.json"]
)
def test_remote_id_never_becomes_path_or_query_injection(cpa, result, account, bad):
    with pytest.raises(IntegrationError):
        run(cpa, result, account, CPA(), bad)


def test_types_and_identity_are_validated_before_network(cpa, result, account):
    server = CPA()
    result["credential_type"] = "chatgpt_web"
    with pytest.raises(IntegrationError, match="type"):
        run(cpa, result, account, server)
    result["credential_type"] = "codex_oauth"
    result["identity"] = "other@example.test"
    with pytest.raises(IntegrationError, match="identity"):
        run(cpa, result, account, server)
    assert server.requests == []


def test_missing_oauth_fields_rejected(cpa, result, account):
    del result["credential"]["refresh_token"]
    with pytest.raises(IntegrationError, match="complete Codex OAuth"):
        run(cpa, result, account, CPA())


def test_connection_is_management_only_unverified(cpa):
    server = CPA()
    assert connection(cpa, _transport=httpx.MockTransport(server)) == {
        "reachable": True,
        "verification": "unverified",
    }
    assert all(r.method == "GET" for r in server.requests)


@pytest.mark.parametrize(
    "status,message",
    [
        (401, "authentication"),
        (403, "authentication"),
        (302, "rejected"),
        (429, "rate limited"),
    ],
)
def test_errors_are_safe_bounded_and_redirects_not_followed(cpa, status, message):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="synthetic-credential-do-not-leak",
            headers={"Location": "https://evil.test"},
        )

    with pytest.raises(IntegrationError, match=message) as exc:
        connection(cpa, _transport=httpx.MockTransport(handler), _sleep=lambda _: None)
    assert "synthetic-credential" not in str(exc.value)
    assert 1 <= len(calls) <= 3
    assert all(r.url.host == "target.test" for r in calls)


def test_transport_failures_safe_and_bounded(cpa):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError(
            "https://secret-user:secret-password@host", request=request
        )

    with pytest.raises(IntegrationError) as exc:
        connection(cpa, _transport=httpx.MockTransport(handler), _sleep=lambda _: None)
    assert "secret" not in str(exc.value)
    assert len(calls) == 3


def test_retry_after_long_delay_does_not_block(cpa):
    sleeps = []
    with pytest.raises(IntegrationError, match="retry later"):
        connection(
            cpa,
            _transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": "600"})
            ),
            _sleep=sleeps.append,
        )
    assert sleeps == []


@pytest.mark.parametrize(
    "url",
    [
        "http://target.test",
        "https://user:pass@target.test",
        "https://target.test?key=secret",
        "https://target.test/#secret",
    ],
)
def test_target_url_validation(cpa, url):
    cpa["config"]["base_url"] = url
    with pytest.raises(IntegrationError):
        connection(cpa, _transport=httpx.MockTransport(CPA()))


def test_target_http_requires_explicit_opt_in(cpa):
    cpa["config"].update(base_url="http://target.test", allow_http=True)
    assert connection(cpa, _transport=httpx.MockTransport(CPA()))["reachable"]


def test_client_ignores_environment_proxy(cpa, monkeypatch):
    original = httpx.Client
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted-proxy.test")
    connection(cpa, _transport=httpx.MockTransport(CPA()))
    assert seen[0]["trust_env"] is False
    assert seen[0]["follow_redirects"] is False
    assert "proxy" not in seen[0]


@pytest.fixture
def voice():
    return {
        "kind": "chatgpt-web-voice",
        "config": {
            "base_url": "https://voice.test",
            "admin_username": "synthetic-user",
            "admin_password": "synthetic-password",
            "compatibility": "bridge-v1",
        },
    }


def test_voice_requires_explicit_compatible_contract(voice):
    del voice["config"]["compatibility"]
    with pytest.raises(IntegrationError, match="bridge-v1"):
        connection(voice)


def test_voice_stable_upsert_and_digest_readback(voice, account):
    state, requests = {}, []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"].startswith("Basic ")
        if request.url.path.endswith("capabilities"):
            return httpx.Response(
                200,
                json={
                    "protocol": "bridge-v1",
                    "explicit_route": True,
                    "credential_digest": True,
                },
            )
        rid = request.url.path.split("/")[-1]
        if request.method == "PUT":
            p = json.loads(request.content)
            assert "refresh_token" not in p["credential"]
            assert p["route"] == {"type": "direct"}
            state[rid] = {**p, "credential_digest": _digest(p.pop("credential"))}
            raise httpx.ReadTimeout("lost", request=request)
        return (
            httpx.Response(200, json=state[rid])
            if rid in state
            else httpx.Response(404)
        )

    result = {
        "credential_type": "chatgpt_web",
        "identity": account["username"],
        "expires_at": None,
        "credential": {
            "access_token": "synthetic-web",
            "refresh_token": "must-not-export",
        },
    }
    transport = httpx.MockTransport(handler)
    first = sync_credential(voice, result, account, _transport=transport)
    assert first["verified"]
    assert (
        sync_credential(voice, result, account, _transport=httpx.MockTransport(handler))
        == first
    )
    assert len([r for r in requests if r.method == "PUT"]) == 1


def test_voice_capability_claims_mandatory(voice):
    with pytest.raises(IntegrationError, match="compatibility API"):
        connection(
            voice,
            _transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"protocol": "bridge-v1"})
            ),
        )


def test_voice_digest_canonical_utf8_vector():
    # Shared cross-language vector: no HTML escaping, ASCII escaping, whitespace,
    # newline, or Unicode normalization is permitted in the hashed bytes.
    assert _digest({"device_id": "测试<&>\u2028\u2029", "access_token": "synthetic"}) == (
        "5fcc9d4ab814aedce4447a6dd1243d8f67353cf8270f4d23eeaef6aa6286502d"
    )


def test_existing_cpa_email_filename_reused(cpa, result, account):
    server = CPA()
    rid = "codex-synthetic+bridge@example.test-free.json"
    server.files[rid] = {"type": "codex", "email": account["username"]}
    assert run(cpa, result, account, server, rid)["remote_id"] == rid
    assert list(server.files) == [rid]


def test_cpa_existing_other_credential_type_not_overwritten(cpa, result, account):
    server = CPA()
    server.files["existing.json"] = {"type": "claude", "email": account["username"]}
    with pytest.raises(IntegrationError, match="credential type"):
        run(cpa, result, account, server, "existing.json")
    assert not any(r.method == "POST" for r in server.requests)


def test_cpa_null_compatibility_uses_native_default(cpa):
    cpa["config"]["compatibility"] = None
    assert connection(cpa, _transport=httpx.MockTransport(CPA()))["reachable"]


def test_reconciliation_does_not_overwrite_remote_token_rotation(cpa, result, account):
    server = CPA()
    first = run(cpa, result, account, server)
    record = server.files[first["remote_id"]]
    record.update(
        access_token="remote-rotated-access", refresh_token="remote-rotated-refresh"
    )
    result["_reconcile_only"] = True
    before = len(server.requests)
    with pytest.raises(IntegrationError, match="avoid overwriting rotated credentials"):
        run(cpa, result, account, server, first["remote_id"])
    assert not any(r.method == "POST" for r in server.requests[before:])
    assert record["refresh_token"] == "remote-rotated-refresh"


def test_reconciliation_can_upload_when_remote_record_absent(cpa, result, account):
    server = CPA()
    result["_reconcile_only"] = True
    assert run(cpa, result, account, server)["verified"]
    assert len([r for r in server.requests if r.method == "POST"]) == 1


def test_rotation_immediately_after_upload_prevents_second_write(cpa, result, account):
    server = CPA()
    server.alter = lambda p: {**p, "refresh_token": "remote-rotated-refresh"}
    server.lose_response = True
    with pytest.raises(IntegrationError, match="avoid overwriting rotated credentials"):
        run(cpa, result, account, server)
    assert len([r for r in server.requests if r.method == "POST"]) == 1
    assert (
        next(iter(server.files.values()))["refresh_token"] == "remote-rotated-refresh"
    )


def test_reconciliation_matching_remote_requires_no_write(cpa, result, account):
    server = CPA()
    first = run(cpa, result, account, server)
    result["_reconcile_only"] = True
    before = len(server.requests)
    assert run(cpa, result, account, server, first["remote_id"]) == first
    assert not any(r.method == "POST" for r in server.requests[before:])


def test_first_preflight_auth_failure_reports_no_possible_write(cpa, result, account):
    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, lambda _: httpx.Response(401))
    assert exc.value.write_possible is False


def test_first_preflight_config_failure_reports_no_possible_write(cpa, result, account):
    cpa["config"]["base_url"] = "invalid"
    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, CPA())
    assert exc.value.write_possible is False


def test_write_mismatch_reports_possible_write(cpa, result, account):
    server = CPA()
    server.alter = lambda p: {**p, "refresh_token": "rotated"}
    server.lose_response = True
    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, server)
    assert exc.value.write_possible is True


def test_reconciliation_conflict_preserves_possible_historical_write(
    cpa, result, account
):
    server = CPA()
    first = run(cpa, result, account, server)
    server.files[first["remote_id"]]["refresh_token"] = "rotated"
    result["_reconcile_only"] = True
    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, server, first["remote_id"])
    assert exc.value.write_possible is True


@pytest.mark.parametrize("failure", ["auth", "config"])
def test_reconciliation_preflight_failure_preserves_historical_uncertainty(
    cpa, result, account, failure
):
    result["_reconcile_only"] = True
    if failure == "config":
        cpa["config"]["base_url"] = "invalid"
    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, lambda _: httpx.Response(401))
    assert exc.value.write_possible is True


def test_lost_write_response_without_readback_reports_possible_write(
    cpa, result, account
):
    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("synthetic-secret", request=request)
        if request.url.path.endswith("auth-files"):
            return httpx.Response(200, json={"files": []})
        return httpx.Response(404)

    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, handler)
    assert exc.value.write_possible is True


def test_first_preflight_transport_failure_reports_no_possible_write(
    cpa, result, account
):
    def handler(request):
        raise httpx.ConnectError("synthetic-secret", request=request)

    with pytest.raises(IntegrationError) as exc:
        run(cpa, result, account, handler)
    assert exc.value.write_possible is False

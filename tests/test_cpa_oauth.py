"""Synthetic native OAuth contract and durable recovery checks; no account login."""
import json
import time
from copy import deepcopy
from urllib.parse import parse_qs

import httpx
import pytest

from app.browser import authorization_url, REDIRECT_URI, run_login
from app.cpa_oauth import NativeOAuth, PROTOCOL, ROOT
from app.crypto import decrypt, load_key
from app.db import database
from app.integrations import IntegrationError, sync_credential, test_connection as check_connection
from app.queue import Queue, LeaseLost, Conflict
from app.worker import Worker, Control

ACCOUNT = {"username": "test@example.com", "route_type": "direct"}
TARGET = {"kind": "cliproxyapi", "config": {"base_url": "https://cpa.example", "management_key": "synthetic-key", "compatibility": PROTOCOL}}
SESSION_ID = "synthetic-session"
RID = "native-test.json"
DIGEST = "a" * 64


def session(state="pending", **overrides):
    value = {"protocol": PROTOCOL, "session_id": SESSION_ID, "identity": ACCOUNT["username"],
             "route": {"type": "direct"}, "remote_id": RID, "state": state,
             "authorization_url": authorization_url("synthetic-state", "synthetic-challenge"),
             "provider_state": "synthetic-state", "expires_at": time.time() + 2700,
             "credential_digest": DIGEST,
             "record": {"remote_id": RID, "identity": ACCOUNT["username"], "route": {"type": "direct"}, "credential_digest": DIGEST}}
    value.update(overrides)
    return value


def response(data):
    return httpx.Response(200, json=data)


def transport(handler):
    def handle(request):
        if request.url.path == ROOT + "/capabilities":
            return response({"protocol": PROTOCOL, "providers": ["codex"]})
        return handler(request)
    return httpx.MockTransport(handle)


@pytest.mark.parametrize("change", [
    {"authorization_url": "https://evil.example/oauth/authorize?state=synthetic-state"},
    {"authorization_url": authorization_url("different", "challenge")},
    {"authorization_url": authorization_url("synthetic-state", "challenge") + "&state=synthetic-state"},
    {"authorization_url": authorization_url("synthetic-state", "challenge").replace("localhost%3A1455", "localhost%3A1456")},
    {"authorization_url": authorization_url("synthetic-state", "challenge").replace("S256", "plain")},
    {"authorization_url": authorization_url("synthetic-state", "challenge") + "#fragment"},
    {"provider_state": ""},
])
def test_authorization_url_and_state_fail_closed(change):
    with pytest.raises(IntegrationError, match="authorization URL is invalid"):
        NativeOAuth.validate_authorization(session(**change))


@pytest.mark.parametrize("change", [
    {"identity": "other@example.com"}, {"route": {"type": "proxy", "url": "http://proxy.example:8080"}},
    {"session_id": "wrong"}, {"protocol": "stock"}, {"remote_id": "../secret.json"}, {"state": "unknown"},
])
def test_session_binding_checks_identity_route_protocol(change):
    client = NativeOAuth(TARGET, ACCOUNT, SESSION_ID, transport=transport(lambda r: response(session(**change))))
    try:
        with pytest.raises(IntegrationError):
            client.get()
    finally:
        client.close()


def test_start_sends_only_bound_identity_explicit_route_and_record():
    requests = []
    client = NativeOAuth(TARGET, ACCOUNT, SESSION_ID, remote_id=RID,
                         transport=transport(lambda r: requests.append(r) or response(session())))
    try:
        client.start()
    finally:
        client.close()
    assert len(requests) == 1 and requests[0].method == "PUT"
    assert json.loads(requests[0].content) == {"identity": ACCOUNT["username"], "route": {"type": "direct"}, "remote_id": RID}


def test_lost_callback_response_recovers_without_replaying_code():
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadError("synthetic-secret-code", request=request)
        return response(session("staged"))
    client = NativeOAuth(TARGET, ACCOUNT, SESSION_ID, transport=transport(handler), sleep=lambda _: None)
    try:
        result = client.result(client.callback(REDIRECT_URI + "?state=synthetic-state&code=synthetic-secret-code", "synthetic-state"))
        assert result["native_oauth"]["session_id"] == SESSION_ID
        assert "credential" not in result
    finally:
        client.close()
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize("mismatch", ["digest", "identity", "route", "remote_id"])
def test_completed_session_requires_actual_record_readback(mismatch):
    current = session("completed")
    proof = current["record"]
    proof[{"digest": "credential_digest"}.get(mismatch, mismatch)] = {
        "digest": "b" * 64, "identity": "other@example.com", "route": {"type": "proxy", "url": "http://proxy.example"}, "remote_id": "other.json"
    }[mismatch]
    with pytest.raises(IntegrationError, match="record readback"):
        sync_credential(TARGET, native_result(), ACCOUNT, RID, _transport=transport(lambda r: response(current)))


def native_result():
    return {"credential_type": "codex_oauth", "identity": ACCOUNT["username"],
            "native_oauth": {"protocol": PROTOCOL, "session_id": SESSION_ID}}


def test_lost_commit_response_reads_back_without_token_upload():
    calls = []
    committed = False
    def handler(request):
        nonlocal committed
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path.endswith("/commit") and json.loads(request.content) == {}
            committed = True
            raise httpx.ReadError("synthetic-secret-token", request=request)
        return response(session("completed" if committed else "staged"))
    chosen, checkpoints = [], []
    result = sync_credential(TARGET, native_result(), ACCOUNT, RID, _transport=transport(handler),
                             _on_remote_id=chosen.append, _checkpoint=lambda: checkpoints.append(True))
    assert result == {"remote_id": RID, "verified": True}
    assert chosen == [RID] and checkpoints == [True]
    assert [m for m, _ in calls] == ["GET", "POST", "GET"]
    assert all("auth-files" not in path for _, path in calls)


def test_commit_uncertainty_survives_failure_before_next_write():
    data = {**native_result(), "_reconcile_only": True}
    def unavailable(request):
        raise httpx.ConnectError("synthetic-secret", request=request)
    with pytest.raises(IntegrationError) as error:
        sync_credential(TARGET, data, ACCOUNT, RID, _transport=httpx.MockTransport(unavailable), _sleep=lambda _: None)
    assert error.value.write_possible is True
    assert "synthetic-secret" not in str(error.value)


def test_native_target_does_not_fall_back_to_local_tokens_or_stock_api():
    with pytest.raises(IntegrationError, match="session result"):
        sync_credential(TARGET, {"credential_type": "codex_oauth", "credential": {"access_token": "synthetic"}}, ACCOUNT)
    stock = deepcopy(TARGET)
    stock["config"]["compatibility"] = "cpa-auth-files-v1"
    with pytest.raises(IntegrationError, match="native target contract"):
        sync_credential(stock, native_result(), ACCOUNT)
    assert check_connection(TARGET, _transport=transport(lambda r: pytest.fail("unexpected endpoint")))["verification"] == "unverified"


def test_recovered_submitted_callback_never_opens_browser_or_starts_session(monkeypatch):
    import app.cpa_oauth as module
    calls = []
    class Client:
        def __init__(self, *a, **k): pass
        def check(self): calls.append("check")
        def get(self): calls.append("GET"); return session("staged")
        def result(self, data): calls.append("result"); return native_result()
        def close(self): calls.append("closed")
    class Guard:
        def checkpoint(self): pass
        def native_session(self): return {"session_id": SESSION_ID, "callback_submitted": True}
    monkeypatch.setattr(module, "NativeOAuth", Client)
    assert run_login(ACCOUNT, TARGET, Guard()) == native_result()
    assert calls == ["check", "GET", "result", "closed"]


def test_missing_session_after_submitted_callback_never_restarts(monkeypatch):
    import app.cpa_oauth as module
    class Client:
        def __init__(self, *a, **k): pass
        def check(self): pass
        def get(self): return None
        def result(self, data): assert data is None; raise IntegrationError("Native exchange outcome unavailable")
        def start(self): pytest.fail("must not restart a session after callback submission")
        def close(self): pass
    class Guard:
        def checkpoint(self): pass
        def native_session(self): return {"session_id": SESSION_ID, "callback_submitted": True}
    monkeypatch.setattr(module, "NativeOAuth", Client)
    with pytest.raises(IntegrationError):
        run_login(ACCOUNT, TARGET, Guard())


def reserve(settings, resources):
    account, target = resources
    worker = Worker(settings)
    worker.queue.create(account, target)
    task = worker.queue.claim()
    control = Control(worker, task)
    reserved = control.native_session()
    return worker, task, control, reserved


def test_private_session_and_submitted_flag_are_encrypted_and_fenced(settings, resources):
    worker, task, control, reserved = reserve(settings, resources)
    control.native_callback_submitted()
    with database(settings.db_path) as conn:
        cipher = conn.execute("SELECT session_cipher FROM native_sessions").fetchone()[0]
        assert reserved["session_id"] not in cipher
        assert json.loads(decrypt(cipher, worker.key))["callback_submitted"] is True
        assert reserved["session_id"] not in str([dict(r) for r in conn.execute("SELECT * FROM task_events")])
        conn.execute("UPDATE tasks SET lease_until=?", (time.time() - 1,))
    with pytest.raises(LeaseLost):
        control.native_callback_submitted()


def test_restart_retains_same_session_and_callback_flag(settings, resources):
    worker, task, control, reserved = reserve(settings, resources)
    control.native_callback_submitted()
    with database(settings.db_path) as conn:
        conn.execute("UPDATE tasks SET lease_until=?", (time.time() - 1,))
    worker.queue.recover()
    recovered = worker.queue.claim()
    assert recovered["id"] == task["id"] and recovered["execution_id"] != task["execution_id"]
    again = Control(worker, recovered).native_session()
    assert again["session_id"] == reserved["session_id"] and again["callback_submitted"] is True


def test_native_recovery_failure_blocks_new_login_until_retry_or_cancel(settings, resources):
    worker, task, control, reserved = reserve(settings, resources)
    assert worker._release_native(task, "native_recovery_failed", "Native reconciliation required")
    assert worker.queue.claim() is None
    with pytest.raises(Conflict):
        worker.queue.create(*resources)
    worker.queue.action(task["id"], "retry-sync")
    assert worker.queue.claim()["id"] == task["id"]


def test_idle_native_cancel_reconciles_remote_before_local_deletion(settings, resources, monkeypatch):
    import app.cpa_oauth as module
    worker, task, control, reserved = reserve(settings, resources)
    worker._release_native(task, "native_recovery_failed", "Native reconciliation required")
    worker.queue.action(task["id"], "cancel")
    cancelled = []
    class Client:
        def __init__(self, target, account, sid, **kwargs): assert sid == reserved["session_id"]
        def cancel(self): cancelled.append(True); return session("cancelled")
        def close(self): pass
    monkeypatch.setattr(module, "NativeOAuth", Client)
    assert worker.run_once()
    assert cancelled == [True]
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "cancelled"
        assert not conn.execute("SELECT 1 FROM native_sessions").fetchone()
    assert worker.queue.create(*resources)["state"] == "queued"


def test_commit_post_then_unavailable_readback_retains_write_uncertainty():
    committed = False
    def handler(request):
        nonlocal committed
        if request.method == "POST":
            committed = True
            raise httpx.ReadError("synthetic-secret", request=request)
        if committed:
            raise httpx.ConnectError("synthetic-secret", request=request)
        return response(session("staged"))
    with pytest.raises(IntegrationError) as error:
        sync_credential(TARGET, native_result(), ACCOUNT, RID, _transport=transport(handler), _sleep=lambda _: None)
    assert error.value.write_possible is True
    assert "synthetic-secret" not in str(error.value)


def test_native_configuration_change_does_not_allow_another_authorization(settings, resources):
    worker, task, control, reserved = reserve(settings, resources)
    worker._release_native(task, "native_recovery_failed", "Native reconciliation required")
    with database(settings.db_path) as conn:
        conn.execute("UPDATE accounts SET version=version+1 WHERE id=?", (resources[0],))
    worker.queue.action(task["id"], "retry-sync")
    assert worker.queue.claim() is None
    with database(settings.db_path) as conn:
        row = conn.execute("SELECT state,phase FROM tasks").fetchone()
        assert tuple(row) == ("queued", "native_recovery_failed")
        assert conn.execute("SELECT 1 FROM native_sessions").fetchone()
    with pytest.raises(Conflict):
        worker.queue.create(*resources)


def test_expired_uncommitted_native_session_does_not_claim_remote_write():
    with pytest.raises(IntegrationError) as error:
        sync_credential(TARGET, native_result(), ACCOUNT, RID,
                        _transport=transport(lambda r: response(session("expired"))))
    assert error.value.write_possible is False


def test_native_browser_uses_saved_account_context_and_fences_callback(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import app.browser as browser_module
    import app.cpa_oauth as native_module
    import playwright.sync_api
    from app.browser_identity import generate_profile, context_options

    events = []
    saved = {"cookies": [], "origins": []}
    profile = generate_profile(set())
    callback = REDIRECT_URI + "?state=synthetic-state&code=synthetic-code"
    pending = session()
    result = native_result()

    class Context:
        def route(self, pattern, handler): self.handler = handler
        def set_default_timeout(self, value): pass
        def new_page(self): return Page(self)
        def cookies(self): return []
        def storage_state(self, *, indexed_db):
            assert indexed_db is True
            return saved
        def close(self): events.append("browser_closed")

    context = Context()

    class Page:
        def __init__(self, context): self.context = context
        def goto(self, url, **kwargs):
            assert events[-1] == "context"
            events.append("navigation")
            assert url == pending["authorization_url"]
            request_route = SimpleNamespace(request=SimpleNamespace(url=callback), fulfill=lambda **kw: None)
            self.context.handler(request_route)

    class Chromium:
        def launch_persistent_context(self, **kwargs):
            assert "storage_state" not in kwargs
            assert kwargs["user_data_dir"] == str(tmp_path)
            assert all(kwargs[k] == v for k, v in context_options(profile, native_window=True).items())
            assert "identity_seed" not in kwargs
            events.append("context")
            return context

    class Native:
        def __init__(self, *a, **kw): pass
        def check(self): pass
        def get(self): return pending
        def callback(self, url, state):
            assert events[-1] == "callback_fenced"
            assert url == callback and state == "synthetic-state"
            events.append("native_callback")
            return session("staged")
        def result(self, value): assert value["state"] == "staged"; return result
        def close(self): events.append("native_closed")

    class Guard:
        def checkpoint(self): pass
        def phase(self, *a): pass
        def native_session(self): return {"session_id": SESSION_ID, "callback_submitted": False}
        def native_callback_submitted(self): events.append("callback_fenced")
        def save_state(self, state): assert state is saved; events.append("saved")

    @contextmanager
    def fake_camoufox(**kwargs):
        yield Chromium().launch_persistent_context(**kwargs)

    @contextmanager
    def fake_route(account):
        yield SimpleNamespace(playwright_proxy=None, session=None)

    @contextmanager
    def fake_device(account, control):
        from pathlib import Path
        try:
            yield SimpleNamespace(path=tmp_path, restored=True, mark_ready=lambda: None, abort_snapshot=lambda: None)
        finally:
            assert events[-1] == "browser_closed"

    monkeypatch.setattr(browser_module, "fit_browser_window", lambda *a: None)
    monkeypatch.setattr(browser_module, "configure_page_identity", lambda *a: None)
    monkeypatch.setattr(browser_module, "device_directory", fake_device)
    monkeypatch.setattr(native_module, "NativeOAuth", Native)
    monkeypatch.setattr("camoufox.sync_api.Camoufox", fake_camoufox)
    monkeypatch.setattr(browser_module, "account_route", fake_route)
    monkeypatch.setattr(browser_module, "pkce_pair", lambda: pytest.fail("native PKCE belongs to CLIProxyAPI"))
    assert run_login({**ACCOUNT, "_browser_profile": profile}, TARGET, Guard(), saved) == result
    assert events == ["context", "navigation", "callback_fenced", "native_callback", "saved", "browser_closed", "native_closed"]


def test_graceful_worker_stop_retains_pending_commit_for_reconciliation(settings, resources):
    account_id, target_id = resources
    seen = []
    def runner(account, target, control, saved):
        control.native_session()
        return native_result()
    def syncer(target, result, account, remote_id):
        seen.append(result["_reconcile_only"])
        raise LeaseLost()
    worker = Worker(settings, runner=runner, syncer=syncer)
    task = worker.queue.create(account_id, target_id)
    assert worker.run_once()
    assert worker.run_once()
    with database(settings.db_path) as conn:
        row = conn.execute("SELECT state,phase,execution_id FROM tasks").fetchone()
        assert tuple(row) == ("sync_pending", "sync_ready", None)
        assert conn.execute("SELECT attempts FROM pending_credentials").fetchone()[0] == 1
        assert conn.execute("SELECT 1 FROM native_sessions").fetchone()
    assert seen == [False]
    assert worker.run_once()
    assert seen == [False, True]

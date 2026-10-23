from dataclasses import replace
import json
import threading
import time
import pytest
from app.worker import Worker, Control
from app.queue import Queue, LeaseLost, Conflict, HumanTimeout
from app.crypto import load_key, decrypt
from app.db import database


def queue(settings):
    return Queue(settings, load_key(settings.key_file))


def result():
    return {
        "credential_type": "codex_oauth",
        "identity": "test@example.com",
        "credential": {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "id_token": "synthetic-id",
            "account_id": "acct",
        },
        "expires_at": time.time() + 7200,
    }


def test_config_change_fences_queued_task(settings, resources, admin):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    admin.patch(f"/api/v1/accounts/{a}", json={"password": "replacement-secret"})
    assert q.claim() is None
    with database(settings.db_path) as conn:
        assert (
            conn.execute(
                "SELECT state FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()[0]
            == "interrupted"
        )


def test_expired_worker_cannot_write_or_replay(settings, resources):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    claimed = q.claim()
    with database(settings.db_path) as conn:
        conn.execute("UPDATE tasks SET lease_until=?", (time.time() - 1,))
    with pytest.raises(LeaseLost):
        q.finish(task["id"], claimed["execution_id"], "succeeded", "bad", "stale")
    q.recover()
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "interrupted"
    assert q.claim() is None


def test_dual_workers_shared_lock_and_database_claim(settings, resources):
    a, t = resources
    q = queue(settings)
    q.create(a, t)
    entered = threading.Event()
    release = threading.Event()

    def runner(account, target, control, saved):
        entered.set()
        assert release.wait(5)
        return result()

    w1 = Worker(settings, runner=runner)
    w2 = Worker(settings, runner=runner)
    thread = threading.Thread(target=w1.run_once)
    thread.start()
    assert entered.wait(3)
    try:
        assert not w2.run_once()
        assert q.claim() is None
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "sync_pending"


def test_cancel_releases_browser_resources(settings, resources):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    closed = []

    def runner(account, target, control, saved):
        try:
            q.action(task["id"], "cancel")
            control.checkpoint()
        finally:
            closed.append(True)

    assert Worker(settings, runner=runner).run_once()
    assert closed == [True]
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "cancelled"
    assert q.create(a, t)["state"] == "queued"


def test_human_code_encrypted_idempotent_and_resume(settings, resources):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    claimed = q.claim()
    worker = Worker(settings)
    control = Control(worker, claimed)
    seen = []
    thread = threading.Thread(
        target=lambda: seen.append(control.wait_human("Enter code"))
    )
    thread.start()
    for _ in range(100):
        with database(settings.db_path) as conn:
            state = conn.execute("SELECT state FROM tasks").fetchone()[0]
        if state == "waiting_human":
            break
        time.sleep(0.01)
    q.action(task["id"], "code", "123456", "unique-submission")
    q.action(task["id"], "code", "123456", "unique-submission")
    with database(settings.db_path) as conn:
        row = conn.execute("SELECT command_cipher FROM tasks").fetchone()
        if row[0]:
            assert "123456" not in row[0]
        assert "123456" not in str(
            [dict(r) for r in conn.execute("SELECT * FROM task_events")]
        )
    thread.join(3)
    assert seen == ["123456"]
    q.action(
        task["id"], "code", "123456", "unique-submission"
    )  # late duplicate is still idempotent


def test_human_timeout_becomes_interrupted(settings, resources):
    a, t = resources
    q = queue(settings)
    q.create(a, t)
    short = replace(settings, human_seconds=0.02)
    Worker(short, runner=lambda a, t, c, s: c.wait_human("Enter code")).run_once()
    with database(settings.db_path) as conn:
        r = conn.execute("SELECT state,phase FROM tasks").fetchone()
        assert tuple(r) == ("interrupted", "human_timeout")


def test_sync_retry_does_not_repeat_browser_and_clears_credentials(
    settings, resources, admin
):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    calls = []
    attempts = []

    def runner(*args):
        calls.append(True)
        return result()

    def syncer(target, data, account, remote_id):
        attempts.append(data["_reconcile_only"])
        if len(attempts) == 1:
            raise RuntimeError("synthetic failure")
        assert target["config"]["management_key"] == "replacement-key"
        return {"remote_id": "remote-id.json", "verified": True}

    worker = Worker(settings, runner=runner, syncer=syncer)
    assert worker.run_once()
    assert worker.run_once()
    with database(settings.db_path) as conn:
        assert (
            conn.execute("SELECT state,phase FROM tasks").fetchone()[1] == "sync_failed"
        )
        assert (
            "synthetic-refresh"
            not in conn.execute(
                "SELECT result_cipher FROM pending_credentials"
            ).fetchone()[0]
        )
    assert (
        admin.patch(
            f"/api/v1/targets/{t}",
            json={"config": {"base_url": "https://other.example"}},
        ).status_code
        == 409
    )
    r = admin.patch(
        f"/api/v1/targets/{t}", json={"config": {"management_key": "replacement-key"}}
    )
    assert r.status_code == 200, r.text
    q.action(task["id"], "retry-sync")
    assert worker.run_once()
    assert calls == [True] and attempts == [False, True]
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "succeeded"
        assert (
            conn.execute("SELECT count(*) FROM pending_credentials").fetchone()[0] == 0
        )
        assert (
            conn.execute("SELECT remote_id FROM syncs").fetchone()[0]
            == "remote-id.json"
        )


def test_sync_cancel_cannot_discard_unknown_remote_outcome(settings, resources):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)

    def syncer(*args):
        with pytest.raises(Conflict, match="reconcile"):
            q.action(task["id"], "cancel")
        raise RuntimeError("lost response")

    worker = Worker(settings, runner=lambda *args: result(), syncer=syncer)
    worker.run_once()
    worker.run_once()
    with pytest.raises(Conflict):
        q.action(task["id"], "cancel")
    with database(settings.db_path) as conn:
        assert (
            conn.execute("SELECT count(*) FROM pending_credentials").fetchone()[0] == 1
        )
        assert tuple(conn.execute("SELECT state,phase FROM tasks").fetchone()) == (
            "sync_pending",
            "sync_failed",
        )


def test_restart_reconciles_sync_without_browser(settings, resources):
    a, t = resources
    q = queue(settings)
    q.create(a, t)
    worker = Worker(settings, runner=lambda *args: result())
    worker.run_once()
    claimed = q.claim()
    with database(settings.db_path) as conn:
        conn.execute("UPDATE tasks SET lease_until=?", (time.time() - 1,))
    calls = []
    replacement = Worker(
        settings,
        runner=lambda *args: calls.append("browser"),
        syncer=lambda *args: {"remote_id": "remote.json", "verified": True},
    )
    replacement.run_once()
    assert calls == []
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "succeeded"


def test_maintenance_dedup_and_reauth_required(settings, resources):
    a, t = resources
    with database(settings.db_path) as conn:
        conn.execute("UPDATE targets SET kind='chatgpt-web-voice' WHERE id=?", (t,))
        conn.execute(
            "INSERT INTO syncs(account_id,target_id,credential_type,state,next_check) VALUES(?,?,'chatgpt_web','verified',?)",
            (a, t, time.time() - 1),
        )
    worker = Worker(
        settings,
        runner=lambda *args: (_ for _ in ()).throw(RuntimeError("reauth_required")),
    )
    worker.maintenance()
    worker.maintenance()
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    worker.run_once()
    with database(settings.db_path) as conn:
        assert (
            conn.execute("SELECT status FROM accounts").fetchone()[0]
            == "reauth_required"
        )
        assert conn.execute("SELECT state,next_check FROM syncs").fetchone()[1] is None


def test_cancel_between_checkpoint_and_first_sync_attempt_is_atomic(
    settings, resources, monkeypatch
):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    calls = []
    worker = Worker(
        settings, runner=lambda *args: result(), syncer=lambda *args: calls.append(True)
    )
    worker.run_once()
    checkpoint = Control.checkpoint

    def cancel_after_checkpoint(self):
        checkpoint(self)
        if self.task["state"] == "sync_pending":
            q.action(task["id"], "cancel")

    monkeypatch.setattr(Control, "checkpoint", cancel_after_checkpoint)
    worker.run_once()
    assert calls == []
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "cancelled"
        assert (
            conn.execute("SELECT count(*) FROM pending_credentials").fetchone()[0] == 0
        )


def test_sync_preflight_failure_can_retry_existing_remote_after_key_fix(
    settings, resources, admin
):
    from app.integrations import IntegrationError

    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    attempts = []
    with database(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO syncs(account_id,target_id,remote_id,credential_type,state) VALUES(?,?,'existing.json','codex_oauth','verified')",
            (a, t),
        )

    def syncer(target, data, account, remote_id):
        attempts.append(data["_reconcile_only"])
        assert remote_id == "existing.json"
        if len(attempts) == 1:
            raise IntegrationError("Authentication failed before write")
        return {"remote_id": remote_id, "verified": True}

    worker = Worker(settings, runner=lambda *args: result(), syncer=syncer)
    worker.run_once()
    worker.run_once()
    assert (
        admin.patch(
            f"/api/v1/targets/{t}", json={"config": {"management_key": "fixed-key"}}
        ).status_code
        == 200
    )
    q.action(task["id"], "retry-sync")
    worker.run_once()
    assert attempts == [False, False]
    with database(settings.db_path) as conn:
        assert conn.execute("SELECT state FROM tasks").fetchone()[0] == "succeeded"


def test_explicit_discard_keeps_audit_and_allows_new_authorization(
    settings, resources, admin
):
    a, t = resources
    q = queue(settings)
    task = q.create(a, t)
    worker = Worker(
        settings,
        runner=lambda *args: result(),
        syncer=lambda *args: (_ for _ in ()).throw(RuntimeError("lost response")),
    )
    worker.run_once()
    worker.run_once()
    assert (
        admin.post(
            f"/api/v1/tasks/{task['id']}/discard-sync", json={"confirmation": "wrong"}
        ).status_code
        == 409
    )
    response = admin.post(
        f"/api/v1/tasks/{task['id']}/discard-sync",
        json={"confirmation": "test@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "interrupted" and response.json()["remote_id"]
    with database(settings.db_path) as conn:
        assert (
            conn.execute("SELECT count(*) FROM pending_credentials").fetchone()[0] == 0
        )
        assert (
            conn.execute("SELECT status FROM accounts").fetchone()[0] == "sync_unknown"
        )
    assert q.create(a, t)["state"] == "queued"

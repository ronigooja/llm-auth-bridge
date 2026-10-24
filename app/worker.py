"""Serial, fenced browser worker with durable encrypted credential handoff."""

import fcntl
import json
import os
import signal
import threading
import time
import uuid
from pathlib import Path
from .config import Settings
from .crypto import load_key, encrypt, decrypt
from .db import database, validate_database
from .queue import Queue, LeaseLost, Cancelled, HumanTimeout, Conflict, event


class Control:
    def __init__(self, worker, task):
        self.worker, self.task = worker, task
        self.queue = worker.queue
        self.id = task["id"]
        self.execution_id = task["execution_id"]

    def row(self):
        with database(self.worker.settings.db_path) as conn:
            return dict(self.queue.owned(conn, self.id, self.execution_id))

    def checkpoint(self):
        row = self.row()
        if row["cancel_requested"]:
            raise Cancelled()
        if self.worker.stopping.is_set():
            raise LeaseLost()
        if row["state"] != "waiting_human" and row["deadline"] < time.time():
            raise TimeoutError("task execution timed out")
        if row["takeover_requested"] and row["state"] != "waiting_human":
            self.wait_human("Manual browser takeover requested")

    def phase(self, name, message):
        self.checkpoint()
        # Adapters own safe phase strings. Neither values nor raw exceptions belong here.
        self.queue.update(self.id, self.execution_id, phase=name, message=message)

    def browser_ready(self, port=6080):
        self.queue.update(self.id, self.execution_id, takeover_available=1)

    def browser_closed(self):
        self.queue.update(self.id, self.execution_id, takeover_available=0)

    def save_state(self, state):
        with database(self.worker.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.queue.owned(conn, self.id, self.execution_id)
            if row["cancel_requested"]:
                raise Cancelled()
            conn.execute(
                "INSERT OR REPLACE INTO browser_sessions VALUES(?,?,?)",
                (
                    row["account_id"],
                    encrypt(json.dumps(state), self.worker.key),
                    time.time(),
                ),
            )

    def wait_human(self, reason, *, phase="waiting_human"):
        start = time.time()
        deadline = start + self.worker.settings.human_seconds
        self.queue.update(
            self.id,
            self.execution_id,
            state="waiting_human",
            phase=phase,
            message=reason,
            human_deadline=deadline,
            takeover_requested=0,
        )
        while True:
            if self.worker.stopping.is_set():
                raise LeaseLost()
            with database(self.worker.settings.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = self.queue.owned(conn, self.id, self.execution_id)
                if row["cancel_requested"]:
                    raise Cancelled()
                if time.time() > deadline:
                    raise HumanTimeout()
                if row["command_cipher"]:
                    command = json.loads(
                        decrypt(row["command_cipher"], self.worker.key)
                    )
                    conn.execute(
                        "UPDATE tasks SET state='running',phase='resuming',message='Rechecking browser page',command_cipher=NULL,takeover_requested=0,human_deadline=NULL,deadline=? WHERE id=? AND execution_id=?",
                        (
                            row["deadline"] + time.time() - start,
                            self.id,
                            self.execution_id,
                        ),
                    )
                    event(conn, self.id)
                    return command.get("code")
            self.worker.stopping.wait(0.25)


class Worker:
    def __init__(self, settings=None, runner=None, syncer=None):
        self.settings = settings or Settings()
        self.key = load_key(self.settings.key_file)
        validate_database(self.settings.db_path, self.key)
        self.queue = Queue(self.settings, self.key)
        self.stopping = threading.Event()
        self.runner = runner
        self.syncer = syncer
        self.worker_id = str(uuid.uuid4())
        self.current = None
        self._heartbeat_thread = None

    def heartbeat(self):
        browser_available = bool(os.getenv("DISPLAY"))
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser_available = (
                    browser_available and Path(p.chromium.executable_path).exists()
                )
        except Exception:
            browser_available = False
        while not self.stopping.is_set():
            try:
                with database(self.settings.db_path) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO runtime VALUES(?,?,?)",
                        (self.worker_id, time.time(), int(browser_available)),
                    )
                current = self.current
                if current:
                    self.queue.heartbeat(current["id"], current["execution_id"])
            except Exception:
                pass
            self.stopping.wait(max(0.2, min(5, self.settings.lease_seconds / 3)))

    def load(self, task):
        with database(self.settings.db_path) as conn:
            account = dict(
                conn.execute(
                    "SELECT * FROM accounts WHERE id=?", (task["account_id"],)
                ).fetchone()
            )
            target = dict(
                conn.execute(
                    "SELECT * FROM targets WHERE id=?", (task["target_id"],)
                ).fetchone()
            )
            stored = conn.execute(
                "SELECT state_cipher FROM browser_sessions WHERE account_id=?",
                (task["account_id"],),
            ).fetchone()
        for name, column in [
            ("password", "password_cipher"),
            ("totp", "totp_cipher"),
            ("mailbox_url", "mailbox_url_cipher"),
        ]:
            account[name] = (
                decrypt(account[column], self.key) if account[column] else None
            )
        account["proxy"] = (
            json.loads(decrypt(account["proxy_cipher"], self.key))
            if account["proxy_cipher"]
            else None
        )
        account["_maintenance"] = task["kind"] == "maintenance"
        target["config"] = json.loads(decrypt(target["config_cipher"], self.key))
        return (
            account,
            target,
            json.loads(decrypt(stored["state_cipher"], self.key)) if stored else None,
        )

    def process(self, task):
        self.current = task
        control = Control(self, task)
        try:
            account, target, saved = self.load(task)
            if task["state"] == "sync_pending":
                with database(self.settings.db_path) as conn:
                    stored = conn.execute(
                        "SELECT result_cipher,attempts FROM pending_credentials WHERE task_id=?",
                        (task["id"],),
                    ).fetchone()
                    old = conn.execute(
                        "SELECT remote_id FROM syncs WHERE account_id=? AND target_id=?",
                        (task["account_id"], task["target_id"]),
                    ).fetchone()
                if not stored:
                    raise ValueError("pending credentials are unavailable")
                result = json.loads(decrypt(stored["result_cipher"], self.key))
                control.checkpoint()
                result["_reconcile_only"] = bool(stored["attempts"])
                with database(self.settings.db_path) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    owned = self.queue.owned(conn, task["id"], task["execution_id"])
                    if owned["cancel_requested"]:
                        raise Cancelled()
                    conn.execute(
                        "UPDATE pending_credentials SET attempts=attempts+1 WHERE task_id=?",
                        (task["id"],),
                    )
                if self.syncer:
                    syncer = self.syncer
                else:
                    from .integrations import sync_credential

                    syncer = sync_credential
                stable_remote_id = old["remote_id"] if old else task.get("remote_id")
                if self.syncer:
                    if stable_remote_id is None:
                        from .integrations import _remote_id

                        stable_remote_id = _remote_id(
                            None, result["identity"], target["kind"]
                        )
                        with database(self.settings.db_path) as conn:
                            conn.execute("BEGIN IMMEDIATE")
                            owned = self.queue.owned(
                                conn, task["id"], task["execution_id"]
                            )
                            if owned["cancel_requested"]:
                                raise Cancelled()
                            conn.execute(
                                "UPDATE tasks SET remote_id=? WHERE id=? AND execution_id=?",
                                (stable_remote_id, task["id"], task["execution_id"]),
                            )
                    synced = syncer(target, result, account, stable_remote_id)
                else:
                    def persist_remote_id(remote_id):
                        with database(self.settings.db_path) as conn:
                            conn.execute("BEGIN IMMEDIATE")
                            owned = self.queue.owned(
                                conn, task["id"], task["execution_id"]
                            )
                            if owned["cancel_requested"]:
                                raise Cancelled()
                            conn.execute(
                                "UPDATE tasks SET remote_id=? WHERE id=? AND execution_id=?",
                                (remote_id, task["id"], task["execution_id"]),
                            )

                    synced = syncer(
                        target,
                        result,
                        account,
                        stable_remote_id,
                        _on_remote_id=persist_remote_id,
                    )
                if not synced.get("verified"):
                    raise ValueError("downstream did not verify credentials")
                with database(self.settings.db_path) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = self.queue.owned(conn, task["id"], task["execution_id"])
                    if row["cancel_requested"]:
                        raise Cancelled()
                    expires = result.get("expires_at")
                    next_check = (
                        min(time.time() + 21600, expires - 3600)
                        if expires
                        else time.time() + 21600
                    )
                    conn.execute(
                        "INSERT INTO syncs(account_id,target_id,remote_id,credential_type,state,expires_at,verified_at,next_check,last_error) VALUES(?,?,?,?,?,?,?,?,NULL) ON CONFLICT(account_id,target_id) DO UPDATE SET remote_id=excluded.remote_id,credential_type=excluded.credential_type,state=excluded.state,expires_at=excluded.expires_at,verified_at=excluded.verified_at,next_check=excluded.next_check,last_error=NULL",
                        (
                            task["account_id"],
                            task["target_id"],
                            str(synced["remote_id"]),
                            result["credential_type"],
                            "verified",
                            expires,
                            time.time(),
                            next_check,
                        ),
                    )
                    conn.execute(
                        "DELETE FROM pending_credentials WHERE task_id=?", (task["id"],)
                    )
                    conn.execute(
                        "UPDATE accounts SET status='ready' WHERE id=?",
                        (task["account_id"],),
                    )
                    conn.execute(
                        "UPDATE tasks SET state='succeeded',phase='verified',message='Downstream synchronization verified',remote_id=?,execution_id=NULL,lease_until=NULL,takeover_available=0,updated_at=CURRENT_TIMESTAMP WHERE id=? AND execution_id=?",
                        (str(synced["remote_id"]), task["id"], task["execution_id"]),
                    )
                    event(conn, task["id"])
            else:
                if self.runner:
                    runner = self.runner
                else:
                    from .browser import run_login

                    runner = run_login
                result = runner(account, target, control, saved)
                control.checkpoint()
                expected = (
                    "codex_oauth" if target["kind"] == "cliproxyapi" else "chatgpt_web"
                )
                if (
                    result.get("credential_type") != expected
                    or result.get("identity", "").casefold()
                    != account["username"].casefold()
                ):
                    raise ValueError("credential identity mismatch")
                self.queue.save_result(task["id"], task["execution_id"], result)
        except Cancelled:
            self._finish(task, "cancelled", "cancelled", "Task cancelled")
        except LeaseLost:
            # Finishing is fenced; an expired owner is never allowed to update a result.
            self._finish(
                task,
                "interrupted",
                "interrupted",
                "Worker stopped; start a new authorization",
            )
        except HumanTimeout:
            self._finish(
                task,
                "interrupted",
                "human_timeout",
                "Human input timed out; start a new task",
            )
        except Exception as exc:
            from .integrations import IntegrationError
            from .browser import BrowserError
            from .routing import RouteError

            safe_message = (
                str(exc)
                if isinstance(exc, (IntegrationError, BrowserError, RouteError))
                else None
            )
            if task["state"] == "sync_pending":
                try:
                    with database(self.settings.db_path) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        self.queue.owned(conn, task["id"], task["execution_id"])
                        if getattr(exc, "write_possible", True) is False:
                            conn.execute(
                                "UPDATE pending_credentials SET attempts=0 WHERE task_id=?",
                                (task["id"],),
                            )
                        conn.execute(
                            "UPDATE tasks SET phase='sync_failed',message=?,execution_id=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND execution_id=?",
                            (
                                safe_message
                                or "Synchronization failed; check target compatibility and retry",
                                task["id"],
                                task["execution_id"],
                            ),
                        )
                        event(conn, task["id"])
                except LeaseLost:
                    pass
            else:
                reauth = "reauth_required" in str(exc)
                if reauth:
                    with database(self.settings.db_path) as conn:
                        self.queue.owned(conn, task["id"], task["execution_id"])
                        conn.execute(
                            "UPDATE accounts SET status='reauth_required' WHERE id=?",
                            (task["account_id"],),
                        )
                        conn.execute(
                            "UPDATE syncs SET state='reauth_required',last_error='reauth_required',next_check=NULL WHERE account_id=? AND target_id=?",
                            (task["account_id"], task["target_id"]),
                        )
                self._finish(
                    task,
                    "failed",
                    "reauth_required" if reauth else "login_failed",
                    "Web session expired; start login again"
                    if reauth
                    else safe_message
                    or "Login failed; check route and account, then start a new task",
                )
        finally:
            self.current = None

    def _finish(self, task, *args):
        try:
            self.queue.finish(task["id"], task["execution_id"], *args)
        except LeaseLost:
            pass

    def maintenance(self):
        now = time.time()
        with database(self.settings.db_path) as conn:
            cfg = conn.execute("SELECT * FROM settings").fetchone()
            if cfg["maintenance_enabled"]:
                due = conn.execute(
                    "SELECT s.account_id,s.target_id FROM syncs s JOIN targets t ON t.id=s.target_id WHERE t.kind='chatgpt-web-voice' AND s.state='verified' AND s.next_check<=?",
                    (now,),
                ).fetchall()
            else:
                due = []
            # Retain final task audit records for configured days. No secret logs exist.
            conn.execute(
                "DELETE FROM tasks WHERE state IN ('succeeded','failed','cancelled','interrupted') AND updated_at<datetime('now',?)",
                (f"-{cfg['retention_days']} days",),
            )
            conn.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
        for s in due:
            try:
                self.queue.create(s["account_id"], s["target_id"], kind="maintenance")
            except Exception:
                pass
            with database(self.settings.db_path) as conn:
                conn.execute(
                    "UPDATE syncs SET next_check=? WHERE account_id=? AND target_id=?",
                    (now + 21600, s["account_id"], s["target_id"]),
                )

    def run_once(self):
        self.settings.browser_lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.settings.browser_lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            self.queue.recover()
            task = self.queue.claim()
            if not task:
                return False
            self.process(task)
            return True
        finally:
            os.close(fd)

    def run(self):
        self._heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
        self._heartbeat_thread.start()
        next_maintenance = 0
        try:
            while not self.stopping.is_set():
                if time.time() >= next_maintenance:
                    self.maintenance()
                    next_maintenance = time.time() + 900
                if not self.run_once():
                    self.stopping.wait(0.5)
        finally:
            self.stopping.set()
            self._heartbeat_thread.join(timeout=6)
            with database(self.settings.db_path) as conn:
                conn.execute("DELETE FROM runtime WHERE id=?", (self.worker_id,))


def main():
    os.umask(0o077)
    worker = Worker()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: worker.stopping.set())
    worker.run()


if __name__ == "__main__":
    main()

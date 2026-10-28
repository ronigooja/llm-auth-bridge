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
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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

    def native_session(self):
        """Durably reserve a private native ID before any remote operation."""
        with database(self.worker.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.queue.owned(conn, self.id, self.execution_id)
            if row["cancel_requested"]:
                raise Cancelled()
            stored = conn.execute("SELECT session_cipher FROM native_sessions WHERE task_id=?", (self.id,)).fetchone()
            if stored:
                return json.loads(decrypt(stored[0], self.worker.key))
            old = conn.execute("SELECT remote_id FROM syncs WHERE account_id=? AND target_id=?", (row["account_id"], row["target_id"])).fetchone()
            session = {"session_id": uuid.uuid4().hex, "callback_submitted": False,
                       "remote_id": old[0] if old else row["remote_id"]}
            conn.execute("INSERT INTO native_sessions(task_id,session_cipher) VALUES(?,?)",
                         (self.id, encrypt(json.dumps(session), self.worker.key)))
            return session

    def native_callback_submitted(self):
        self.checkpoint()
        with database(self.worker.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.queue.owned(conn, self.id, self.execution_id)
            if row["cancel_requested"]:
                raise Cancelled()
            stored = conn.execute("SELECT session_cipher FROM native_sessions WHERE task_id=?", (self.id,)).fetchone()
            if not stored:
                raise ValueError("native session is unavailable")
            session = json.loads(decrypt(stored[0], self.worker.key))
            if session["callback_submitted"]:
                raise ValueError("native callback was already submitted")
            session["callback_submitted"] = True
            conn.execute("UPDATE native_sessions SET session_cipher=? WHERE task_id=?",
                         (encrypt(json.dumps(session), self.worker.key), self.id))

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

    def load_device(self):
        """Read only this leased account's authenticated profile archive."""
        self.checkpoint()
        with database(self.worker.settings.db_path) as conn:
            row = self.queue.owned(conn, self.id, self.execution_id)
            stored = conn.execute(
                "SELECT archive_cipher FROM browser_devices WHERE account_id=?",
                (row["account_id"],),
            ).fetchone()
        if stored is None:
            return None
        blob = bytes(stored[0])
        aad = f"browser-device-v1:{row['account_id']}".encode()
        try:
            return AESGCM(self.worker.key).decrypt(blob[:12], blob[12:], aad)
        except Exception:
            raise ValueError("encrypted browser device cannot be read") from None

    def save_device(self, archive):
        """Checkpoint the closed device, including progress before cancellation.

        Cancellation stops provider operations but must not discard the device.
        A still-valid execution lease is mandatory; expired owners cannot write.
        """
        from .browser_device import MAX_COMPRESSED_BYTES
        if not isinstance(archive, bytes) or len(archive) > MAX_COMPRESSED_BYTES:
            raise ValueError("invalid browser device archive")
        with database(self.worker.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.queue.owned(conn, self.id, self.execution_id)
            nonce = os.urandom(12)
            aad = f"browser-device-v1:{row['account_id']}".encode()
            cipher = nonce + AESGCM(self.worker.key).encrypt(nonce, archive, aad)
            conn.execute(
                "INSERT INTO browser_devices(account_id,archive_cipher,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(account_id) DO UPDATE SET archive_cipher=excluded.archive_cipher,updated_at=excluded.updated_at",
                (row["account_id"], cipher, time.time()),
            )

    def update_timezone(self, timezone):
        """Persist verified route preference without replacing device identity."""
        from zoneinfo import ZoneInfo
        ZoneInfo(timezone)
        self.checkpoint()
        with database(self.worker.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.queue.owned(conn, self.id, self.execution_id)
            if row["cancel_requested"]:
                raise Cancelled()
            stored = conn.execute(
                "SELECT profile_cipher FROM browser_profiles WHERE account_id=?",
                (row["account_id"],),
            ).fetchone()
            if not stored:
                raise ValueError("browser profile is unavailable")
            profile = json.loads(decrypt(stored[0], self.worker.key))
            profile["context"]["timezone_id"] = timezone
            conn.execute("UPDATE browser_profiles SET profile_cipher=? WHERE account_id=?",
                         (encrypt(json.dumps(profile), self.worker.key), row["account_id"]))

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
            from camoufox import launch_options
            browser_available = browser_available and Path(
                launch_options(headless=True).get("executable_path", "")
            ).exists()
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
        from .browser_identity import load_or_create_profile
        profile = load_or_create_profile(self.settings.db_path, self.key, self.queue, task)
        with database(self.settings.db_path) as conn:
            account = dict(
                conn.execute(
                    "SELECT * FROM accounts WHERE id=?", (task["account_id"],)
                ).fetchone()
            )
            target_row = conn.execute("SELECT * FROM targets WHERE id=?", (task["target_id"],)).fetchone()
            target = dict(target_row) if target_row else None
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
                decrypt(account[column], self.key) if account[column] and task["kind"] != "browser_window" else None
            )
        account["proxy"] = (
            json.loads(decrypt(account["proxy_cipher"], self.key))
            if account["proxy_cipher"]
            else None
        )
        account["_browser_profile"] = profile
        account["_maintenance"] = task["kind"] == "maintenance"
        if target is not None:
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
            control.checkpoint()
            account, target, saved = self.load(task)
            if task["kind"] == "browser_window":
                if self.runner:
                    self.runner(account, None, control, saved)
                else:
                    from .browser import run_browser_window
                    run_browser_window(account, control, saved)
                control.checkpoint()
                self.queue.finish(task["id"], task["execution_id"], "succeeded", "browser_closed", "Account browser closed")
            elif task["state"] == "sync_pending":
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
                        **({"_checkpoint": control.checkpoint} if result.get("native_oauth") else {}),
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
                    conn.execute("DELETE FROM native_sessions WHERE task_id=?", (task["id"],))
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
                # Persist the validated web-session check while this task still owns its lease.
                if target["kind"] == "chatgpt-web-voice":
                    with database(self.settings.db_path) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        self.queue.owned(conn, task["id"], task["execution_id"])
                        now = time.time()
                        conn.execute("INSERT INTO web_session_health(account_id,status,checked_at,last_success_at,error_code) VALUES(?,?,?,?,NULL) ON CONFLICT(account_id) DO UPDATE SET status='valid',checked_at=excluded.checked_at,last_success_at=excluded.last_success_at,error_code=NULL", (task["account_id"], "valid", now, now))
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
            if not self._cancel_native(task):
                self._release_native(task, "native_cancel_pending", "Native cancellation remains pending; retry reconciliation")
                return
            self._finish(task, "cancelled", "cancelled", "Task cancelled")
        except LeaseLost:
            if task["state"] == "sync_pending":
                # A graceful stop must retain staged credentials and any prior
                # commit uncertainty, just like expired-owner recovery does.
                try:
                    with database(self.settings.db_path) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        self.queue.owned(conn, task["id"], task["execution_id"])
                        conn.execute("UPDATE tasks SET phase='sync_ready',message='Synchronization interrupted; reconciliation queued',execution_id=NULL,lease_until=NULL,takeover_available=0 WHERE id=? AND execution_id=?", (task["id"], task["execution_id"]))
                        event(conn, task["id"])
                except LeaseLost:
                    pass
                return
            if self._release_native(task, "native_recovery", "Native OAuth interrupted; reconciliation queued"):
                return
            # Finishing is fenced; an expired owner is never allowed to update a result.
            self._finish(
                task,
                "interrupted",
                "interrupted",
                "Worker stopped; start a new authorization",
            )
        except HumanTimeout:
            if self._release_native(task, "native_recovery_failed", "Human input timed out; retry or cancel native authorization"):
                return
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
                if self._release_native(task, "native_recovery_failed", safe_message or "Native OAuth requires reconciliation; retry or cancel this task"):
                    return
                reauth = "reauth_required" in str(exc)
                if reauth:
                    with database(self.settings.db_path) as conn:
                        self.queue.owned(conn, task["id"], task["execution_id"])
                        now = time.time()
                        conn.execute("INSERT INTO web_session_health(account_id,status,checked_at,last_success_at,error_code) VALUES(?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET status='signed_out',checked_at=excluded.checked_at,error_code=excluded.error_code", (task["account_id"], "signed_out", now, None, "signed_out"))
                        conn.execute(
                            "UPDATE accounts SET status='reauth_required' WHERE id=?",
                            (task["account_id"],),
                        )
                        conn.execute(
                            "UPDATE syncs SET state='reauth_required',last_error='reauth_required',next_check=NULL WHERE account_id=? AND target_id=?",
                            (task["account_id"], task["target_id"]),
                        )
                if not reauth and task.get("target_id"):
                    with database(self.settings.db_path) as conn:
                        target_row = conn.execute("SELECT kind FROM targets WHERE id=?", (task["target_id"],)).fetchone()
                        if target_row and target_row["kind"] == "chatgpt-web-voice":
                            self.queue.owned(conn, task["id"], task["execution_id"])
                            error_code = "identity_mismatch" if "identity" in str(exc).lower() and "match" in str(exc).lower() else "check_failed"
                            conn.execute("INSERT INTO web_session_health(account_id,status,checked_at,last_success_at,error_code) VALUES(?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET status='error',checked_at=excluded.checked_at,error_code=excluded.error_code", (task["account_id"], "error", time.time(), None, error_code))
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

    def _release_native(self, task, phase, message):
        if task["state"] == "sync_pending":
            return False
        try:
            with database(self.settings.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self.queue.owned(conn, task["id"], task["execution_id"])
                if not conn.execute("SELECT 1 FROM native_sessions WHERE task_id=?", (task["id"],)).fetchone():
                    return False
                # Keep the active task, preventing a second authorization from
                # overwriting an unresolved native exchange or cancellation.
                conn.execute("UPDATE tasks SET state='queued',phase=?,message=?,execution_id=NULL,lease_until=NULL,takeover_available=0,command_cipher=NULL WHERE id=? AND execution_id=?", (phase, message, task["id"], task["execution_id"]))
                event(conn, task["id"])
                return True
        except LeaseLost:
            return False

    def _cancel_native(self, task):
        try:
            with database(self.settings.db_path) as conn:
                self.queue.owned(conn, task["id"], task["execution_id"])
                stored = conn.execute("SELECT session_cipher FROM native_sessions WHERE task_id=?", (task["id"],)).fetchone()
                if not stored:
                    return True
                target_row = conn.execute("SELECT * FROM targets WHERE id=?", (task["target_id"],)).fetchone()
                account_row = conn.execute("SELECT * FROM accounts WHERE id=?", (task["account_id"],)).fetchone()
            session = json.loads(decrypt(stored[0], self.key))
            target = dict(target_row)
            target["config"] = json.loads(decrypt(target["config_cipher"], self.key))
            account = dict(account_row)
            account["proxy"] = json.loads(decrypt(account["proxy_cipher"], self.key)) if account["proxy_cipher"] else None
            from .cpa_oauth import NativeOAuth
            client = NativeOAuth(target, account, session["session_id"], remote_id=session["remote_id"])
            try:
                outcome = client.cancel()
                if outcome and outcome["state"] not in {"cancelled", "expired", "failed"}:
                    return False
            finally:
                client.close()
            with database(self.settings.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self.queue.owned(conn, task["id"], task["execution_id"])
                conn.execute("DELETE FROM native_sessions WHERE task_id=?", (task["id"],))
            return True
        except Exception:
            return False

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
                "DELETE FROM tasks WHERE state IN ('succeeded','failed','cancelled','interrupted') AND updated_at<datetime('now',?) AND NOT EXISTS (SELECT 1 FROM tasks child WHERE child.depends_on_task_id=tasks.id AND child.state IN ('queued','running','waiting_human','sync_pending'))",
                (f"-{cfg['retention_days']} days",),
            )
            conn.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
        for s in due:
            try:
                self.queue.create(s["account_id"], s["target_id"], kind="maintenance")
            except Conflict:
                # An active task owns the account; leave the due time unchanged.
                continue
            except Exception:
                # Scheduling diagnostics are intentionally generic and do not move the plan.
                continue
            with database(self.settings.db_path) as conn:
                conn.execute("UPDATE syncs SET next_check=? WHERE account_id=? AND target_id=?", (now + 21600, s["account_id"], s["target_id"]))

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

"""Durable task ownership, fencing, user commands and resumable events."""

import json
import secrets
import sqlite3
import time
from .db import database
from .crypto import encrypt, decrypt

ACTIVE = ("queued", "running", "waiting_human", "sync_pending")
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")
PUBLIC_TASK = (
    "remote_id",
    "id",
    "account_id",
    "target_id",
    "kind",
    "state",
    "phase",
    "message",
    "created_at",
    "updated_at",
    "takeover_available",
)


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class LeaseLost(Exception):
    pass


class Cancelled(Exception):
    pass


class HumanTimeout(Exception):
    pass


def public_task(row):
    return {k: row[k] for k in PUBLIC_TASK}


def event(conn, task_id):
    conn.execute(
        "INSERT INTO task_events(task_id,state,phase,message,takeover_available) SELECT id,state,phase,message,takeover_available FROM tasks WHERE id=?",
        (task_id,),
    )


class Queue:
    def __init__(self, settings, key):
        self.settings, self.key = settings, key

    def create(self, account_id, target_id, idempotency_key=None, kind="login"):
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                old = conn.execute(
                    "SELECT * FROM tasks WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if old:
                    if (old["account_id"], old["target_id"], old["kind"]) != (
                        account_id,
                        target_id,
                        kind,
                    ):
                        raise Conflict("idempotency key belongs to another request")
                    return public_task(old)
            account = conn.execute(
                "SELECT * FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            target = conn.execute(
                "SELECT * FROM targets WHERE id=?", (target_id,)
            ).fetchone()
            if not account or not target:
                raise NotFound("account or target not found")
            if account["route_type"] == "unset":
                raise Conflict("choose direct or proxy before starting login")
            if not conn.execute(
                "SELECT 1 FROM account_targets WHERE account_id=? AND target_id=?",
                (account_id, target_id),
            ).fetchone():
                raise Conflict("bind the target to this account first")
            old = conn.execute(
                "SELECT id FROM tasks WHERE account_id=? AND target_id=? AND state IN ('queued','running','waiting_human','sync_pending')",
                (account_id, target_id),
            ).fetchone()
            if old:
                raise Conflict(
                    "an active task already exists for this account and target"
                )
            cur = conn.execute(
                "INSERT INTO tasks(account_id,target_id,kind,state,phase,message,account_version,target_version,idempotency_key) VALUES(?,?,?,'queued','queued','Waiting for worker',?,?,?)",
                (
                    account_id,
                    target_id,
                    kind,
                    account["version"],
                    target["version"],
                    idempotency_key,
                ),
            )
            event(conn, cur.lastrowid)
            return public_task(
                conn.execute(
                    "SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)
                ).fetchone()
            )

    def recover(self):
        """Call only while holding the shared browser file lock."""
        now = time.time()
        with database(self.settings.db_path) as conn:
            rows = conn.execute(
                "SELECT id,state FROM tasks WHERE execution_id IS NOT NULL AND (lease_until IS NULL OR lease_until<?)",
                (now,),
            ).fetchall()
            for row in rows:
                if row["state"] == "sync_pending":
                    conn.execute(
                        "UPDATE tasks SET execution_id=NULL,lease_until=NULL,phase='sync_ready',message='Previous sync interrupted; reconciliation required',takeover_available=0 WHERE id=?",
                        (row["id"],),
                    )
                elif row["state"] in ("running", "waiting_human"):
                    conn.execute(
                        "UPDATE tasks SET state='interrupted',phase='interrupted',message='Worker interrupted; start a new authorization',execution_id=NULL,lease_until=NULL,takeover_available=0,command_cipher=NULL WHERE id=?",
                        (row["id"],),
                    )
                event(conn, row["id"])

    def claim(self):
        now = time.time()
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Database guard complements the process-wide browser file lock.
            if conn.execute(
                "SELECT 1 FROM tasks WHERE execution_id IS NOT NULL AND lease_until>?",
                (now,),
            ).fetchone():
                return None
            row = conn.execute(
                "SELECT * FROM tasks WHERE state='sync_pending' AND execution_id IS NULL AND phase='sync_ready' ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE state='queued' ORDER BY CASE kind WHEN 'login' THEN 0 ELSE 1 END,id LIMIT 1"
                ).fetchone()
            if not row:
                return None
            a = conn.execute(
                "SELECT version FROM accounts WHERE id=?", (row["account_id"],)
            ).fetchone()
            t = conn.execute(
                "SELECT version FROM targets WHERE id=?", (row["target_id"],)
            ).fetchone()
            if (
                not a
                or not t
                or a["version"] != row["account_version"]
                or t["version"] != row["target_version"]
            ):
                conn.execute(
                    "UPDATE tasks SET state='interrupted',phase='configuration_changed',message='Configuration changed; create a new task' WHERE id=?",
                    (row["id"],),
                )
                event(conn, row["id"])
                return None
            token = secrets.token_hex(24)
            state = "sync_pending" if row["state"] == "sync_pending" else "running"
            phase = "syncing" if state == "sync_pending" else "starting"
            conn.execute(
                "UPDATE tasks SET state=?,phase=?,message=?,execution_id=?,lease_until=?,deadline=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    state,
                    phase,
                    "Task claimed",
                    token,
                    now + self.settings.lease_seconds,
                    now + self.settings.task_seconds,
                    row["id"],
                ),
            )
            event(conn, row["id"])
            return dict(
                conn.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()
            )

    def owned(self, conn, task_id, execution_id):
        row = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND execution_id=? AND lease_until>?",
            (task_id, execution_id, time.time()),
        ).fetchone()
        if not row or row["state"] in TERMINAL:
            raise LeaseLost()
        return row

    def heartbeat(self, task_id, execution_id):
        with database(self.settings.db_path) as conn:
            self.owned(conn, task_id, execution_id)
            conn.execute(
                "UPDATE tasks SET lease_until=? WHERE id=? AND execution_id=?",
                (time.time() + self.settings.lease_seconds, task_id, execution_id),
            )

    def update(
        self, task_id, execution_id, state=None, phase=None, message=None, **fields
    ):
        allowed = {
            "takeover_available",
            "human_deadline",
            "deadline",
            "command_cipher",
            "takeover_requested",
        }
        if set(fields) - allowed:
            raise ValueError("unsupported task update")
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.owned(conn, task_id, execution_id)
            if row["cancel_requested"] and state not in ("cancelled", "interrupted"):
                raise Cancelled()
            changes = {
                "state": state or row["state"],
                "phase": phase or row["phase"],
                "message": message or row["message"],
                **fields,
            }
            conn.execute(
                "UPDATE tasks SET "
                + ",".join(f"{k}=?" for k in changes)
                + ",updated_at=CURRENT_TIMESTAMP WHERE id=? AND execution_id=?",
                (*changes.values(), task_id, execution_id),
            )
            event(conn, task_id)

    def finish(self, task_id, execution_id, state, phase, message):
        if state not in TERMINAL:
            raise ValueError("invalid terminal state")
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.owned(conn, task_id, execution_id)
            if row["cancel_requested"]:
                state, phase, message = "cancelled", "cancelled", "Task cancelled"
            conn.execute(
                "UPDATE tasks SET state=?,phase=?,message=?,execution_id=NULL,lease_until=NULL,takeover_available=0,command_cipher=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND execution_id=?",
                (state, phase, message, task_id, execution_id),
            )
            event(conn, task_id)
            if state == "cancelled":
                conn.execute(
                    "DELETE FROM pending_credentials WHERE task_id=?", (task_id,)
                )

    def save_result(self, task_id, execution_id, result):
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.owned(conn, task_id, execution_id)
            if row["cancel_requested"]:
                raise Cancelled()
            conn.execute(
                "INSERT OR REPLACE INTO pending_credentials(task_id,result_cipher) VALUES(?,?)",
                (task_id, encrypt(json.dumps(result), self.key)),
            )
            from .integrations import _remote_id

            old = conn.execute(
                "SELECT remote_id FROM syncs WHERE account_id=? AND target_id=?",
                (row["account_id"], row["target_id"]),
            ).fetchone()
            target = conn.execute(
                "SELECT kind FROM targets WHERE id=?", (row["target_id"],)
            ).fetchone()
            remote_id = _remote_id(
                old[0] if old else None, result["identity"], target["kind"]
            )
            conn.execute(
                "UPDATE tasks SET remote_id=? WHERE id=?", (remote_id, task_id)
            )
            conn.execute(
                "UPDATE tasks SET state='sync_pending',phase='sync_ready',message='Credentials ready for synchronization',execution_id=NULL,lease_until=NULL,takeover_available=0,command_cipher=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND execution_id=?",
                (task_id, execution_id),
            )
            event(conn, task_id)

    def action(self, task_id, action, code=None, submission_id=None, confirmation=None):
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise NotFound("task not found")
            if action == "cancel":
                if row["state"] in TERMINAL:
                    return public_task(row)
                attempt = conn.execute(
                    "SELECT attempts FROM pending_credentials WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if row["state"] == "sync_pending" and attempt and attempt[0] > 0:
                    raise Conflict(
                        "synchronization has started; reconcile the remote outcome before discarding credentials"
                    )
                if row["execution_id"]:
                    conn.execute(
                        "UPDATE tasks SET cancel_requested=1,message='Cancellation requested',takeover_available=0 WHERE id=?",
                        (task_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE tasks SET state='cancelled',phase='cancelled',message='Task cancelled',command_cipher=NULL,takeover_available=0 WHERE id=?",
                        (task_id,),
                    )
                    conn.execute(
                        "DELETE FROM pending_credentials WHERE task_id=?", (task_id,)
                    )
            elif action == "discard-sync":
                account = conn.execute(
                    "SELECT username FROM accounts WHERE id=?", (row["account_id"],)
                ).fetchone()
                if not account or confirmation != account["username"]:
                    raise Conflict(
                        "confirm the exact account identity before discarding local credentials"
                    )
                if row["state"] != "sync_pending" or row["execution_id"]:
                    raise Conflict(
                        "wait for synchronization to stop before resolving its outcome"
                    )
                conn.execute(
                    "UPDATE tasks SET state='interrupted',phase='remote_outcome_unknown',message='Administrator discarded local credentials; remote outcome requires manual reconciliation',takeover_available=0,command_cipher=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (task_id,),
                )
                conn.execute(
                    "DELETE FROM pending_credentials WHERE task_id=?", (task_id,)
                )
                conn.execute(
                    "UPDATE accounts SET status='sync_unknown' WHERE id=?",
                    (row["account_id"],),
                )
                conn.execute(
                    "UPDATE syncs SET state='reconciliation_required',last_error='Administrator discarded local credentials; inspect remote account',next_check=NULL WHERE account_id=? AND target_id=?",
                    (row["account_id"], row["target_id"]),
                )
            elif action == "retry-sync":
                if row["state"] != "sync_pending":
                    raise Conflict("no pending synchronization")
                if row["phase"] == "sync_ready" or row["execution_id"]:
                    return public_task(row)
                conn.execute(
                    "UPDATE tasks SET phase='sync_ready',message='Synchronization retry queued' WHERE id=?",
                    (task_id,),
                )
            elif action == "takeover":
                if (
                    row["state"] not in ("running", "waiting_human")
                    or not row["takeover_available"]
                ):
                    raise Conflict("browser is unavailable")
                conn.execute(
                    "UPDATE tasks SET takeover_requested=1 WHERE id=?", (task_id,)
                )
            elif action in ("code", "continue"):
                if action == "code" and row["submission_id"] == submission_id:
                    return public_task(row)
                if row["state"] != "waiting_human":
                    raise Conflict("task is not waiting for input")
                if action == "code" and row["phase"] not in (
                    "email_code_required",
                    "authenticator_code_required",
                ):
                    raise Conflict("task is not waiting for a verification code")
                if row["command_cipher"]:
                    raise Conflict("input already submitted")
                command = {"action": action, "code": code if action == "code" else None}
                conn.execute(
                    "UPDATE tasks SET command_cipher=?,submission_id=? WHERE id=?",
                    (encrypt(json.dumps(command), self.key), submission_id, task_id),
                )
            else:
                raise Conflict("unsupported action")
            event(conn, task_id)
            return public_task(
                conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            )

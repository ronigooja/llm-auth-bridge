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
    "depends_on_task_id",
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


def settle_dependencies(conn):
    rows = conn.execute("""SELECT child.id FROM tasks child LEFT JOIN tasks parent ON parent.id=child.depends_on_task_id
        WHERE child.state='queued' AND child.depends_on_task_id IS NOT NULL
        AND (parent.id IS NULL OR parent.state IN ('failed','cancelled','interrupted'))""").fetchall()
    for row in rows:
        conn.execute("UPDATE tasks SET state='interrupted',phase='prerequisite_failed',message='Previous login did not complete; start a new flow',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        conn.execute("INSERT INTO task_events(task_id,state,phase,message,takeover_available) SELECT id,state,phase,message,takeover_available FROM tasks WHERE id=?", (row["id"],))


def event(conn, task_id):
    conn.execute(
        "INSERT INTO task_events(task_id,state,phase,message,takeover_available) SELECT id,state,phase,message,takeover_available FROM tasks WHERE id=?",
        (task_id,),
    )
    settle_dependencies(conn)


class Queue:
    def __init__(self, settings, key):
        self.settings, self.key = settings, key

    def create(self, account_id, target_id, idempotency_key=None, kind="login"):
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                if conn.execute("SELECT 1 FROM browser_requests WHERE idempotency_key=?", (idempotency_key,)).fetchone():
                    raise Conflict("idempotency key belongs to another request")
                if conn.execute("SELECT 1 FROM login_flows WHERE idempotency_key=?", (idempotency_key,)).fetchone():
                    raise Conflict("idempotency key belongs to another request")
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

    def create_login_flow(self, account_id, voice_target_id, cli_target_id=None, idempotency_key=None):
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                if conn.execute("SELECT 1 FROM browser_requests WHERE idempotency_key=?", (idempotency_key,)).fetchone():
                    raise Conflict("idempotency key belongs to another request")
                old = conn.execute("SELECT * FROM login_flows WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if old:
                    tasks = [conn.execute("SELECT * FROM tasks WHERE id=?", (old[k],)).fetchone() for k in ("voice_task_id", "cli_task_id") if old[k] is not None]
                    expected = [(account_id, voice_target_id)]
                    if cli_target_id is not None:
                        expected.append((account_id, cli_target_id))
                    if [(t["account_id"], t["target_id"]) for t in tasks] != expected:
                        raise Conflict("idempotency key belongs to another request")
                    return [public_task(t) for t in tasks]
                if conn.execute("SELECT 1 FROM tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone():
                    raise Conflict("idempotency key belongs to another request")
            account = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not account:
                raise NotFound("account not found")
            if account["route_type"] == "unset":
                raise Conflict("choose direct or proxy before starting login")
            targets = []
            selected = [(voice_target_id, "chatgpt-web-voice")]
            if cli_target_id is not None:
                selected.append((cli_target_id, "cliproxyapi"))
            for target_id, kind in selected:
                target = conn.execute("SELECT * FROM targets WHERE id=?", (target_id,)).fetchone()
                if not target:
                    raise NotFound("target not found")
                if target["kind"] != kind:
                    raise Conflict("login flow requires a Voice target and, when selected, a CLIProxyAPI target")
                if not conn.execute("SELECT 1 FROM account_targets WHERE account_id=? AND target_id=?", (account_id, target_id)).fetchone():
                    raise Conflict("bind each selected target to this account first")
                if conn.execute("SELECT 1 FROM tasks WHERE account_id=? AND target_id=? AND state IN ('queued','running','waiting_human','sync_pending')", (account_id, target_id)).fetchone():
                    raise Conflict("an active task already exists for this account and target")
                targets.append(target)
            ids = []
            for target in targets:
                cur = conn.execute("INSERT INTO tasks(account_id,target_id,kind,state,phase,message,account_version,target_version,depends_on_task_id) VALUES(?,?,'login','queued',?,?,?,?,?)", (account_id, target["id"], "waiting_prerequisite" if ids else "queued", "Waiting for previous verified login" if ids else "Waiting for worker", account["version"], target["version"], ids[0] if ids else None))
                ids.append(cur.lastrowid)
                event(conn, cur.lastrowid)
            conn.execute("INSERT INTO login_flows VALUES(?,?,?)", (ids[0], ids[1] if len(ids) > 1 else None, idempotency_key))
            return [public_task(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()) for task_id in ids]

    def open_browser(self, account_id, idempotency_key=None):
        with database(self.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                alias = conn.execute("SELECT tasks.* FROM browser_requests JOIN tasks ON tasks.id=browser_requests.task_id WHERE browser_requests.idempotency_key=?", (idempotency_key,)).fetchone()
                if alias:
                    if alias["account_id"] != account_id:
                        raise Conflict("idempotency key belongs to another request")
                    return public_task(alias)
                old = conn.execute("SELECT * FROM tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if old:
                    if old["account_id"] != account_id or old["kind"] != "browser_window":
                        raise Conflict("idempotency key belongs to another request")
                    return public_task(old)
                if conn.execute("SELECT 1 FROM login_flows WHERE idempotency_key=?", (idempotency_key,)).fetchone():
                    raise Conflict("idempotency key belongs to another request")
            account = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not account:
                raise NotFound("account not found")
            old = conn.execute("SELECT * FROM tasks WHERE account_id=? AND (state IN ('running','waiting_human') OR (state='queued' AND phase NOT IN ('native_recovery_failed','native_cancel_pending') AND (depends_on_task_id IS NULL OR EXISTS (SELECT 1 FROM tasks parent WHERE parent.id=tasks.depends_on_task_id AND parent.state='succeeded')))) ORDER BY CASE state WHEN 'waiting_human' THEN 0 WHEN 'running' THEN 1 ELSE 2 END,id LIMIT 1", (account_id,)).fetchone()
            if old:
                if idempotency_key:
                    conn.execute("INSERT INTO browser_requests VALUES(?,?)", (idempotency_key, old["id"]))
                return public_task(old)
            if account["route_type"] == "unset":
                raise Conflict("choose direct or proxy before opening browser")
            cur = conn.execute("INSERT INTO tasks(account_id,kind,state,phase,message,account_version,idempotency_key) VALUES(?,'browser_window','queued','queued','Waiting to open account browser',?,?)", (account_id, account["version"], idempotency_key))
            event(conn, cur.lastrowid)
            return public_task(conn.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone())

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
                elif row["state"] in ("running", "waiting_human") and conn.execute("SELECT 1 FROM native_sessions WHERE task_id=?", (row["id"],)).fetchone():
                    conn.execute("UPDATE tasks SET state='queued',phase='native_recovery',message='Native OAuth interrupted; reconciliation queued',execution_id=NULL,lease_until=NULL,takeover_available=0,command_cipher=NULL WHERE id=?", (row["id"],))
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
            settle_dependencies(conn)
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
                    "SELECT * FROM tasks WHERE state='queued' AND (depends_on_task_id IS NULL OR EXISTS (SELECT 1 FROM tasks prerequisite WHERE prerequisite.id=tasks.depends_on_task_id AND prerequisite.state='succeeded' AND prerequisite.phase='verified')) AND phase NOT IN ('native_recovery_failed','native_cancel_pending') ORDER BY CASE kind WHEN 'login' THEN 0 ELSE 1 END,id LIMIT 1"
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
                or (row["kind"] != "browser_window" and not t)
                or a["version"] != row["account_version"]
                or (row["kind"] != "browser_window" and t["version"] != row["target_version"])
            ):
                if conn.execute("SELECT 1 FROM native_sessions WHERE task_id=?", (row["id"],)).fetchone():
                    conn.execute("UPDATE tasks SET state='queued',phase='native_recovery_failed',message='Configuration changed; native outcome still requires reconciliation' WHERE id=?", (row["id"],))
                    event(conn, row["id"])
                    return None
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
            old = conn.execute(
                "SELECT remote_id FROM syncs WHERE account_id=? AND target_id=?",
                (row["account_id"], row["target_id"]),
            ).fetchone()
            # Keep a known stable ID, but let the integration discover legacy
            # remote filenames before it creates a deterministic new one.
            if old and old[0]:
                conn.execute(
                    "UPDATE tasks SET remote_id=? WHERE id=?", (old[0], task_id)
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
                if conn.execute("SELECT 1 FROM native_sessions WHERE task_id=?", (task_id,)).fetchone() and not row["execution_id"]:
                    conn.execute("UPDATE tasks SET state='queued',phase='native_recovery',cancel_requested=1,message='Native cancellation queued',takeover_available=0 WHERE id=?", (task_id,))
                elif row["execution_id"]:
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
                if row["state"] == "queued" and row["phase"] in {"native_recovery_failed", "native_cancel_pending"}:
                    conn.execute("UPDATE tasks SET phase='native_recovery',message='Native reconciliation queued' WHERE id=?", (task_id,))
                    event(conn, task_id)
                    return public_task(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
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
                    "verification_code_required",
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

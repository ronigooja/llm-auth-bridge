"""Explicit transactional schema migrations. Connections never mutate the schema."""

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from .config import DB_PATH
from .crypto import encrypt, decrypt

SCHEMA_VERSION = 2
IDENTITY_SCHEMA = """
CREATE TABLE browser_profiles(account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,profile_cipher TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE native_sessions(task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,session_cipher TEXT NOT NULL);
"""
SCHEMA = """
CREATE TABLE accounts (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_cipher TEXT NOT NULL,
 totp_cipher TEXT, mailbox_url_cipher TEXT, route_type TEXT NOT NULL DEFAULT 'unset' CHECK(route_type IN ('unset','direct','proxy')),
 proxy_cipher TEXT, allow_http_mailbox INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE targets (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('cliproxyapi','chatgpt-web-voice')),
 name TEXT NOT NULL, config_cipher TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 verification TEXT NOT NULL DEFAULT 'unverified', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE account_targets(account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
 target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE, PRIMARY KEY(account_id,target_id));
CREATE TABLE tasks (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), target_id INTEGER REFERENCES targets(id),
 kind TEXT NOT NULL DEFAULT 'login', state TEXT NOT NULL CHECK(state IN ('queued','running','waiting_human','sync_pending','succeeded','failed','cancelled','interrupted')),
 phase TEXT NOT NULL, message TEXT, account_version INTEGER, target_version INTEGER, remote_id TEXT, execution_id TEXT, lease_until REAL,
 deadline REAL, human_deadline REAL, cancel_requested INTEGER NOT NULL DEFAULT 0, takeover_requested INTEGER NOT NULL DEFAULT 0,
 takeover_available INTEGER NOT NULL DEFAULT 0, command_cipher TEXT, submission_id TEXT, idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX one_active_task ON tasks(account_id,target_id) WHERE state IN ('queued','running','waiting_human');
CREATE TABLE task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 state TEXT NOT NULL,phase TEXT NOT NULL,message TEXT,takeover_available INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE syncs (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,remote_id TEXT,credential_type TEXT NOT NULL,
 state TEXT NOT NULL,expires_at REAL,verified_at REAL,last_error TEXT,next_check REAL,UNIQUE(account_id,target_id)
);
CREATE TABLE pending_credentials(task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,result_cipher TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE browser_sessions(account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,state_cipher TEXT NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE admin(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL,key_check TEXT NOT NULL);
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires_at REAL NOT NULL);
CREATE TABLE login_attempts(client TEXT PRIMARY KEY,attempts INTEGER NOT NULL,reset_at REAL NOT NULL);
CREATE TABLE runtime(id TEXT PRIMARY KEY,heartbeat REAL NOT NULL,browser_available INTEGER NOT NULL);
CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1),maintenance_enabled INTEGER NOT NULL DEFAULT 1,retention_days INTEGER NOT NULL DEFAULT 30);
INSERT INTO settings(id) VALUES(1);
""" + IDENTITY_SCHEMA


def connect(path: Path = DB_PATH):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def database(path=DB_PATH):
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _statements(conn, script):
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def migrate(path: Path, key: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN EXCLUSIVE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("database schema is newer than this application")
        if version == 0:
            legacy = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='accounts'"
            ).fetchone()
            if legacy:
                # Read legacy rows in memory inside the same rollback-capable transaction.
                old = {
                    table: [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
                    for table in ("accounts", "targets", "tasks", "syncs")
                }
                # Verify key before modifying or removing any legacy secret field.
                for a in old["accounts"]:
                    decrypt(a["password_cipher"], key)
                for t in old["targets"]:
                    decrypt(t["config_cipher"], key)
                for table in ("syncs", "tasks", "targets", "accounts"):
                    conn.execute(f"DROP TABLE {table}")
                _statements(conn, SCHEMA)
                for a in old["accounts"]:
                    route, proxy = "unset", None
                    if a.get("proxy_json"):
                        parsed = json.loads(a["proxy_json"])
                        route = (
                            "direct"
                            if parsed == "direct" or parsed == {"type": "direct"}
                            else "proxy"
                        )
                        proxy = (
                            encrypt(json.dumps(parsed), key)
                            if route == "proxy"
                            else None
                        )
                    conn.execute(
                        "INSERT INTO accounts(id,username,password_cipher,totp_cipher,mailbox_url_cipher,route_type,proxy_cipher,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            a["id"],
                            a["username"],
                            a["password_cipher"],
                            a["totp_cipher"],
                            a["mailbox_url_cipher"],
                            route,
                            proxy,
                            a["status"],
                            a["created_at"],
                            a["updated_at"],
                        ),
                    )
                for t in old["targets"]:
                    conn.execute(
                        "INSERT INTO targets(id,kind,name,config_cipher,created_at) VALUES(?,?,?,?,?)",
                        tuple(
                            t[k]
                            for k in (
                                "id",
                                "kind",
                                "name",
                                "config_cipher",
                                "created_at",
                            )
                        ),
                    )
                for t in old["tasks"]:
                    state = (
                        t["state"]
                        if t["state"] in ("succeeded", "failed", "cancelled")
                        else "interrupted"
                    )
                    msg = (
                        "Legacy task requires explicit route and target; create a new task"
                        if state == "interrupted"
                        else "Legacy task migrated"
                    )
                    conn.execute(
                        "INSERT INTO tasks(id,account_id,target_id,kind,state,phase,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            t["id"],
                            t["account_id"],
                            t["target_id"],
                            t["kind"],
                            state,
                            "migrated",
                            msg,
                            t["created_at"],
                            t["updated_at"],
                        ),
                    )
                for s in old["syncs"]:
                    conn.execute(
                        "INSERT INTO syncs(id,account_id,target_id,remote_id,credential_type,state) VALUES(?,?,?,?,?,?)",
                        tuple(
                            s[k]
                            for k in (
                                "id",
                                "account_id",
                                "target_id",
                                "remote_id",
                                "credential_type",
                                "state",
                            )
                        ),
                    )
            else:
                _statements(conn, SCHEMA)
            version = SCHEMA_VERSION
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if version == 1:
            # Verify the supplied key before changing an existing versioned DB.
            admin = conn.execute("SELECT key_check FROM admin WHERE id=1").fetchone()
            if admin and decrypt(admin["key_check"], key) != "llm-auth-bridge":
                raise ValueError("database key check failed")
            for table, column in (
                ("accounts", "password_cipher"),
                ("targets", "config_cipher"),
                ("browser_sessions", "state_cipher"),
            ):
                for row in conn.execute(f"SELECT {column} FROM {table}"):
                    decrypt(row[column], key)
            # Additive migration: retain existing account and encrypted session rows.
            _statements(conn, IDENTITY_SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
        # Scrub dropped plaintext proxy pages from the main file and WAL.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        path.chmod(0o600)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_database(path: Path, key: bytes):
    if not path.is_file():
        raise RuntimeError("database is missing; run initialization first")
    with database(path) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError(
                "run the explicit migrate command before starting services"
            )
        admin = conn.execute("SELECT key_check FROM admin WHERE id=1").fetchone()
        if not admin or decrypt(admin["key_check"], key) != "llm-auth-bridge":
            raise RuntimeError("database is not initialized or key is incorrect")

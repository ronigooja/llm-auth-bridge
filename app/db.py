import sqlite3
from pathlib import Path
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_cipher TEXT NOT NULL,
 totp_cipher TEXT, mailbox_url_cipher TEXT, proxy_json TEXT, status TEXT NOT NULL DEFAULT 'new',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS targets (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('cliproxyapi','chatgpt-web-voice')),
 name TEXT NOT NULL, config_cipher TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), target_id INTEGER REFERENCES targets(id),
 kind TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL, message TEXT, lease_until TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS syncs (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), target_id INTEGER NOT NULL REFERENCES targets(id),
 remote_id TEXT, credential_type TEXT NOT NULL, state TEXT NOT NULL, UNIQUE(account_id,target_id)
);
"""

def connect(path: Path = DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


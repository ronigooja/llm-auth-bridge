import os
import sqlite3
from dataclasses import replace
import pytest
from app.db import SCHEMA, SCHEMA_VERSION, IDENTITY_SCHEMA, DEVICE_SCHEMA, migrate, database, validate_database
from app.cli import backup, restore, initialize
from app.crypto import load_key, encrypt, decrypt
from app.main import create_app
from fastapi.testclient import TestClient

LEGACY = """
CREATE TABLE accounts(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_cipher TEXT NOT NULL,totp_cipher TEXT,mailbox_url_cipher TEXT,proxy_json TEXT,status TEXT DEFAULT 'new',created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE targets(id INTEGER PRIMARY KEY,kind TEXT,name TEXT,config_cipher TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE tasks(id INTEGER PRIMARY KEY,account_id INTEGER REFERENCES accounts(id),target_id INTEGER REFERENCES targets(id),kind TEXT,state TEXT,phase TEXT,message TEXT,lease_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE syncs(id INTEGER PRIMARY KEY,account_id INTEGER REFERENCES accounts(id),target_id INTEGER REFERENCES targets(id),remote_id TEXT,credential_type TEXT,state TEXT);
"""


def legacy(path, key):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY)
    conn.execute(
        "INSERT INTO accounts(id,username,password_cipher,proxy_json) VALUES(1,?,?,?)",
        (
            "synthetic@example.com",
            encrypt("synthetic-password", key),
            '{"server":"socks5://proxy.example:1080","password":"plaintext-legacy-proxy"}',
        ),
    )
    conn.execute(
        "INSERT INTO targets(id,kind,name,config_cipher) VALUES(1,'cliproxyapi','target',?)",
        (encrypt("{}", key),),
    )
    conn.execute(
        "INSERT INTO tasks(id,account_id,target_id,kind,state,phase) VALUES(1,1,NULL,'login','queued','queued')"
    )
    conn.execute("INSERT INTO syncs VALUES(1,1,1,'remote','codex_oauth','verified')")
    conn.commit()
    conn.close()


def test_legacy_migration_preserves_data_and_removes_plaintext(tmp_path):
    key = os.urandom(32)
    path = tmp_path / "legacy.db"
    legacy(path, key)
    migrate(path, key)
    with database(path) as conn:
        row = conn.execute("SELECT * FROM accounts").fetchone()
        assert row["username"] == "synthetic@example.com"
        assert "proxy_json" not in row.keys() and row["route_type"] == "proxy"
        assert decrypt(row["password_cipher"], key) == "synthetic-password"
        assert "plaintext-legacy-proxy" in decrypt(row["proxy_cipher"], key)
        assert tuple(conn.execute("SELECT state,phase FROM tasks").fetchone()) == (
            "interrupted",
            "migrated",
        )
        assert conn.execute("SELECT remote_id FROM syncs").fetchone()[0] == "remote"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert b"plaintext-legacy-proxy" not in path.read_bytes()
    migrate(path, key)


def test_wrong_key_migration_rolls_back(tmp_path):
    path = tmp_path / "legacy.db"
    legacy(path, os.urandom(32))
    with pytest.raises(ValueError):
        migrate(path, os.urandom(32))
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT proxy_json FROM accounts").fetchone()[0]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()


def test_start_missing_key_fails_without_generating(settings):
    missing = settings.key_file.with_name("missing-key")
    with pytest.raises(FileNotFoundError):
        with TestClient(create_app(replace(settings, key_file=missing))):
            pass
    assert not missing.exists()


def test_corrupt_cipher_is_safe(settings, resources, admin):
    a, _ = resources
    with database(settings.db_path) as conn:
        conn.execute(
            "UPDATE accounts SET mailbox_url_cipher='corrupt' WHERE id=?", (a,)
        )
    response = admin.patch(f"/api/v1/accounts/{a}", json={"username": "new"})
    assert response.status_code == 422 and "corrupt" not in response.text


def test_consistent_backup_and_restore(settings, resources, tmp_path):
    backup_path = tmp_path / "backup.db"
    backup(settings, backup_path)
    restored = replace(settings, db_path=tmp_path / "restored" / "bridge.db")
    restore(restored, backup_path)
    key = load_key(restored.key_file)
    validate_database(restored.db_path, key)
    with database(restored.db_path) as conn:
        assert (
            decrypt(
                conn.execute("SELECT password_cipher FROM accounts").fetchone()[0], key
            )
            == "synthetic-password"
        )
    assert backup_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        backup(settings, backup_path)


def test_wrong_restore_key_rejected(settings, tmp_path):
    source = tmp_path / "backup.db"
    backup(settings, source)
    wrong = tmp_path / "wrong"
    wrong.write_bytes(os.urandom(32))
    destination = tmp_path / "restored.db"
    with pytest.raises(ValueError):
        restore(replace(settings, key_file=wrong, db_path=destination), source)
    assert not destination.exists()


def version_one_backup(path, key):
    """A synthetic initialized archive from before identity tables existed."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA.removesuffix(IDENTITY_SCHEMA).removesuffix(DEVICE_SCHEMA))
        conn.execute("PRAGMA user_version=1")
        conn.execute(
            "INSERT INTO admin VALUES(1,'synthetic-hash',?)",
            (encrypt("llm-auth-bridge", key),),
        )
        conn.execute(
            "INSERT INTO accounts(id,username,password_cipher,route_type,status,version) VALUES(1,?,?,'direct','ready',7)",
            ("synthetic@example.com", encrypt("synthetic-password", key)),
        )
        conn.execute(
            "INSERT INTO browser_sessions VALUES(1,?,123.0)",
            (encrypt('{"cookies":[]}', key),),
        )
        conn.execute(
            "INSERT INTO tasks(id,account_id,state,phase) VALUES(1,1,'succeeded','complete')"
        )
        conn.commit()
    finally:
        conn.close()


def test_restore_v1_migrates_only_destination(settings, tmp_path):
    key = load_key(settings.key_file)
    source = tmp_path / "v1.db"
    version_one_backup(source, key)
    original = source.read_bytes()
    source.chmod(0o444)
    original_mtime = source.stat().st_mtime_ns
    restored = replace(settings, db_path=tmp_path / "restored" / "bridge.db")
    # Services must still reject old schemas instead of migrating on startup.
    with pytest.raises(RuntimeError):
        validate_database(source, key)
    restore(restored, source)
    validate_database(restored.db_path, key)
    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_mtime
    assert not source.with_name(source.name + "-wal").exists()
    assert not source.with_name(source.name + "-shm").exists()
    with database(restored.db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        account = conn.execute("SELECT * FROM accounts").fetchone()
        assert (account["username"], account["route_type"], account["status"], account["version"]) == (
            "synthetic@example.com", "direct", "ready", 7
        )
        assert decrypt(account["password_cipher"], key) == "synthetic-password"
        assert decrypt(conn.execute("SELECT state_cipher FROM browser_sessions").fetchone()[0], key) == '{"cookies":[]}'
        assert tuple(conn.execute("SELECT state,phase FROM tasks").fetchone()) == ("succeeded", "complete")
        assert conn.execute("SELECT count(*) FROM browser_profiles").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM native_sessions").fetchone()[0] == 0
    assert restored.db_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["wrong-key", "unversioned", "future"])
def test_restore_v1_preflight_rejects_before_destination_creation(settings, tmp_path, failure):
    source = tmp_path / "v1.db"
    version_one_backup(source, load_key(settings.key_file))
    if failure == "wrong-key":
        wrong = tmp_path / "wrong-key"
        wrong.write_bytes(os.urandom(32))
        settings = replace(settings, key_file=wrong)
    else:
        with sqlite3.connect(source) as conn:
            conn.execute(f"PRAGMA user_version={0 if failure == 'unversioned' else SCHEMA_VERSION + 1}")
    original = source.read_bytes()
    destination = tmp_path / "absent" / "restored.db"
    with pytest.raises((RuntimeError, ValueError)):
        restore(replace(settings, db_path=destination), source)
    assert not destination.parent.exists()
    assert source.read_bytes() == original


def test_restore_migration_failure_removes_incomplete_destination(settings, tmp_path, monkeypatch):
    source = tmp_path / "v1.db"
    version_one_backup(source, load_key(settings.key_file))
    original = source.read_bytes()
    destination = tmp_path / "restored.db"

    def fail_migration(path, key):
        path.with_name(path.name + "-wal").write_bytes(b"synthetic incomplete journal")
        raise RuntimeError("synthetic migration failure")

    monkeypatch.setattr("app.cli.migrate", fail_migration)
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        restore(replace(settings, db_path=destination), source)
    assert not destination.exists()
    assert not destination.with_name(destination.name + "-wal").exists()
    assert source.read_bytes() == original


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_restore_preserves_preexisting_destination_paths(settings, tmp_path, suffix):
    source = tmp_path / "v1.db"
    version_one_backup(source, load_key(settings.key_file))
    destination = tmp_path / "restored.db"
    preserved = destination.with_name(destination.name + suffix)
    preserved.write_bytes(b"synthetic preexisting data")
    with pytest.raises(ValueError, match="destination must not exist"):
        restore(replace(settings, db_path=destination), source)
    assert preserved.read_bytes() == b"synthetic preexisting data"


def test_existing_database_never_gets_replacement_key(tmp_path):
    from app.config import Settings

    path = tmp_path / "legacy.db"
    legacy(path, os.urandom(32))
    missing = tmp_path / "missing-key"
    with pytest.raises(ValueError):
        initialize(Settings(db_path=path, key_file=missing), "synthetic-password-123")
    assert not missing.exists()


def test_backup_opens_from_read_only_directory(settings):
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    # root otherwise bypasses chmod, so test the archive with an unprivileged reader.
    with tempfile.TemporaryDirectory(prefix="bridge-readonly-") as directory:
        folder = Path(directory)
        archive = folder / "backup.db"
        backup(settings, archive)
        assert archive.read_bytes()[18:20] == bytes([1, 1])
        archive.chmod(0o444)
        folder.chmod(0o555)
        try:
            program = 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); assert c.execute("SELECT count(*) FROM admin").fetchone()[0]==1; c.close()'
            executable = shutil.which("python3", path="/usr/bin:/usr/local/bin")
            options = {"user": 65534, "group": 65534} if os.geteuid() == 0 else {}
            response = subprocess.run(
                [executable, "-c", program, str(archive)],
                capture_output=True,
                text=True,
                timeout=5,
                **options,
            )
            assert response.returncode == 0, response.stderr
            assert (
                not (folder / "backup.db-wal").exists()
                and not (folder / "backup.db-shm").exists()
            )
        finally:
            folder.chmod(0o700)

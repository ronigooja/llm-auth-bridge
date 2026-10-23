"""Offline administration: initialize, migrate, consistent backup and restore."""

import argparse
import getpass
import os
from pathlib import Path
import secrets
import sqlite3
from argon2 import PasswordHasher
from .config import Settings
from .crypto import load_key, encrypt
from .db import migrate, database, validate_database, connect


def initialize(settings: Settings, password: str):
    if len(password) < 12:
        raise ValueError("administrator password must contain at least 12 characters")
    if settings.db_path.exists() and not settings.key_file.exists():
        raise ValueError("existing database requires its original master key")
    settings.key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not settings.key_file.exists():
        fd = os.open(settings.key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(32))
    key = load_key(settings.key_file)
    migrate(settings.db_path, key)
    with database(settings.db_path) as conn:
        if conn.execute("SELECT 1 FROM admin").fetchone():
            raise ValueError("administrator already initialized")
        conn.execute(
            "INSERT INTO admin(id,password_hash,key_check) VALUES(1,?,?)",
            (PasswordHasher().hash(password), encrypt("llm-auth-bridge", key)),
        )
    return key


def backup(settings: Settings, destination: Path):
    validate_database(settings.db_path, load_key(settings.key_file))
    if destination.exists():
        raise ValueError("backup destination must not exist")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = connect(settings.db_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        # A self-contained archive must open from a read-only backup mount.
        target.execute("PRAGMA journal_mode=DELETE").fetchone()
    finally:
        source.close()
        target.close()


def restore(settings: Settings, source: Path):
    key = load_key(settings.key_file)
    validate_database(source, key)
    if settings.db_path.exists():
        raise ValueError(
            "restore destination must not exist; stop services and move existing database first"
        )
    settings.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(settings.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source_conn = connect(source)
    target = sqlite3.connect(settings.db_path)
    try:
        source_conn.backup(target)
        target.execute("PRAGMA journal_mode=WAL").fetchone()
    finally:
        source_conn.close()
        target.close()
    validate_database(settings.db_path, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--password-file", type=Path)
    sub.add_parser("migrate")
    sub.add_parser("backup").add_argument("destination", type=Path)
    sub.add_parser("restore").add_argument("source", type=Path)
    args = parser.parse_args()
    settings = Settings()
    try:
        if args.command == "init":
            password = (
                args.password_file.read_text().rstrip("\n")
                if args.password_file
                else getpass.getpass("Administrator password: ")
            )
            initialize(settings, password)
        elif args.command == "migrate":
            migrate(settings.db_path, load_key(settings.key_file))
        elif args.command == "backup":
            backup(settings, args.destination)
        else:
            restore(settings, args.source)
    except Exception:
        parser.exit(
            1,
            "Operation failed. Check initialization, key, permissions, and offline database state.\n",
        )
    print("Operation completed.")


if __name__ == "__main__":
    main()

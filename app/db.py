from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime

from app.config import Settings


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def hash_password(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=actual_salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1${}${}".format(
        base64.b64encode(actual_salt).decode(), base64.b64encode(derived).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
        return secrets.compare_digest(actual, base64.b64decode(digest))
    except (TypeError, ValueError):
        return False


def database_connection(settings: Settings) -> sqlite3.Connection:
    db = sqlite3.connect(settings.state_dir / "selfdrive.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def setup_storage(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with database_connection(settings) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY, original_name TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0), created_at TEXT NOT NULL
            );
        """)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE nodes (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT REFERENCES nodes(id),
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('file', 'folder')),
                    storage_name TEXT UNIQUE,
                    size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK ((kind = 'folder' AND storage_name IS NULL) OR (kind = 'file' AND storage_name IS NOT NULL))
                );
                INSERT INTO nodes (id, parent_id, name, kind, storage_name, size_bytes, created_at, updated_at)
                SELECT id, NULL, original_name, 'file', storage_name, size_bytes, created_at, created_at FROM files;
                PRAGMA user_version = 1;
                COMMIT;
            """)
        if db.execute("SELECT id FROM users WHERE username = ?", (settings.username,)).fetchone() is None:
            db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (settings.username, hash_password(settings.password)))


def reset_admin_password(settings: Settings) -> None:
    setup_storage(settings)
    with database_connection(settings) as db:
        db.execute("DELETE FROM users")
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (settings.username, hash_password(settings.password)))

"""SQLite access layer.

Design notes
- One short-lived connection per unit of work. sqlite3 connections are not safe to share
  across threads, and callers run these functions in a worker thread (``asyncio.to_thread``)
  so the event loop is never blocked on disk I/O.
- WAL journal mode lets the health check and history reads proceed while a chat write
  is in progress.
- The schema is idempotent (``IF NOT EXISTS``) and applied at startup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    metadata    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id, id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    system_prompt  TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str, *, timeout_seconds: float = 5.0) -> None:
        self.path = path
        self._timeout = timeout_seconds

    def initialize(self) -> None:
        """Create the parent directory and schema. Safe to call repeatedly."""
        Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=self._timeout)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout = {int(self._timeout * 1000)}")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic unit of work: commits on success, rolls back on any exception."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()

    def ping(self) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("SELECT 1 FROM messages LIMIT 1").fetchall()
            return True
        except sqlite3.Error:
            return False

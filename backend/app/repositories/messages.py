"""Persistence for conversation history (SQLite).

All methods are synchronous and are meant to be run via ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.database import Database


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class StoredMessage:
    role: str
    content: str
    metadata: dict[str, Any] | None
    created_at: str


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_history(self, session_id: str) -> list[StoredMessage]:
        """Messages of one session, oldest first (``id`` is monotonic, so ties on timestamp are stable)."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            StoredMessage(
                role=row["role"],
                content=row["content"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_system_prompt(self, session_id: str) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return row["system_prompt"] if row else None

    def save_exchange(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_message: str,
        assistant_metadata: dict[str, Any],
        system_prompt: str | None,
    ) -> None:
        """Persist one successful turn atomically: both messages or neither.

        ``system_prompt`` is only written when the client supplied one, so a later request without
        the field keeps the prompt the session already uses.
        """
        user_ts = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, system_prompt, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt),
                    updated_at = excluded.updated_at
                """,
                (session_id, system_prompt, user_ts, user_ts),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
                (session_id, user_message, user_ts),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
                (session_id, assistant_message, json.dumps(assistant_metadata), utc_now_iso()),
            )

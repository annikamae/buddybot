"""Local SQLite storage for Buddy conversations."""

import json
import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from typing import Any
from collections.abc import Iterator
import uuid


class ConversationStore:
    """Persist conversations for the single local user running Buddy."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if os.name != "nt":
            self.path.chmod(0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'ollama',
                    model TEXT NOT NULL,
                    vision_model TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    display TEXT NOT NULL,
                    images_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS messages_by_conversation
                    ON messages(conversation_id, id);
                CREATE INDEX IF NOT EXISTS conversations_by_updated
                    ON conversations(updated_at DESC);
                """
            )

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, provider, model, vision_model, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC, created_at DESC, id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(
        self,
        model: str,
        vision_model: str,
        provider: str = "ollama",
        title: str = "New conversation",
    ) -> str:
        conversation_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, title, provider, model, vision_model)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, title, provider, model, vision_model),
            )
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, provider, model, vision_model, created_at, updated_at
                FROM conversations WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, display, images_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id
                """,
                (conversation_id,),
            ).fetchall()
        messages = []
        for row in rows:
            message = dict(row)
            message["images"] = json.loads(message.pop("images_json"))
            messages.append(message)
        return messages

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        display: str,
        images: list[dict[str, str]] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (conversation_id, role, content, display, images_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    display,
                    json.dumps(images or [], separators=(",", ":")),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
    ) -> None:
        fields = {
            "title": title,
            "provider": provider,
            "model": model,
            "vision_model": vision_model,
        }
        updates = {name: value for name, value in fields.items() if value is not None}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        values = list(updates.values())
        values.append(conversation_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE conversations SET {assignments}, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise KeyError("Conversation does not exist.")

    def clear_conversation(self, conversation_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            cursor = connection.execute(
                """
                UPDATE conversations
                SET title = 'New conversation', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (conversation_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError("Conversation does not exist.")

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError("Conversation does not exist.")

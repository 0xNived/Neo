# ruff: noqa: SIM117
from __future__ import annotations

import json
from datetime import UTC, datetime

import psycopg

from ..domain.models import Session


class PostgresSessionStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def _connect(self):
        return await psycopg.AsyncConnection.connect(self.database_url)

    async def initialize(self) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,messages_json JSONB NOT NULL,references_json JSONB NOT NULL,title TEXT,updated_at TIMESTAMPTZ NOT NULL)"
                )
                await cur.execute(
                    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title TEXT"
                )

    async def get_or_create(self, session_id: str, user_id: str) -> Session:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT user_id,messages_json,references_json FROM sessions WHERE id=%s",
                    (session_id,),
                )
                row = await cur.fetchone()
        if not row:
            return Session(session_id, user_id)
        if row[0] != user_id:
            raise PermissionError("Session belongs to another user")
        messages = row[1] if isinstance(row[1], list) else json.loads(row[1])
        references = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        return Session(session_id, user_id, messages, references)

    async def save(self, session: Session) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO sessions(id,user_id,messages_json,references_json,updated_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET messages_json=EXCLUDED.messages_json,references_json=EXCLUDED.references_json,updated_at=EXCLUDED.updated_at",
                    (
                        session.id,
                        session.user_id,
                        json.dumps(session.messages),
                        json.dumps(session.references),
                        datetime.now(UTC),
                    ),
                )

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,messages_json,title,updated_at FROM sessions WHERE user_id=%s ORDER BY updated_at DESC",
                    (user_id,),
                )
                rows = await cur.fetchall()
        result = []
        for session_id, messages, saved_title, updated_at in rows:
            messages = messages if isinstance(messages, list) else json.loads(messages)
            fallback_title = next(
                (
                    item.get("content", "")
                    for item in messages
                    if item.get("role") == "user"
                ),
                "New conversation",
            )
            result.append(
                {
                    "id": session_id,
                    "title": (saved_title or fallback_title).strip()[:80],
                    "updated_at": updated_at.isoformat(),
                }
            )
        return result

    async def rename(self, session_id: str, user_id: str, title: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE sessions SET title=%s,updated_at=%s WHERE id=%s AND user_id=%s",
                    (title, datetime.now(UTC), session_id, user_id),
                )
                return cur.rowcount > 0

    async def delete(self, session_id: str, user_id: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "DELETE FROM sessions WHERE id=%s AND user_id=%s",
                    (session_id, user_id),
                )
                return cur.rowcount > 0

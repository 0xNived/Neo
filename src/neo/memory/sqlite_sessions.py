from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from ..domain.models import Session


class SqliteSessionStore:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,messages_json TEXT NOT NULL,references_json TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )
            await db.commit()

    async def get_or_create(self, session_id: str, user_id: str) -> Session:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT user_id,messages_json,references_json FROM sessions WHERE id=?",
                    (session_id,),
                )
            ).fetchone()
        if not row:
            return Session(session_id, user_id)
        if row[0] != user_id:
            raise PermissionError("Session belongs to another user")
        return Session(session_id, user_id, json.loads(row[1]), json.loads(row[2]))

    async def save(self, session: Session):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO sessions(id,user_id,messages_json,references_json,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET messages_json=excluded.messages_json,references_json=excluded.references_json,updated_at=excluded.updated_at",
                (
                    session.id,
                    session.user_id,
                    json.dumps(session.messages),
                    json.dumps(session.references),
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT id,messages_json,updated_at FROM sessions WHERE user_id=? ORDER BY updated_at DESC",
                    (user_id,),
                )
            ).fetchall()
        result = []
        for row in rows:
            messages = json.loads(row[1])
            first_user = next(
                (
                    item.get("content", "")
                    for item in messages
                    if item.get("role") == "user"
                ),
                "New conversation",
            )
            result.append(
                {"id": row[0], "title": first_user[:52], "updated_at": row[2]}
            )
        return result

    async def delete(self, session_id: str, user_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0

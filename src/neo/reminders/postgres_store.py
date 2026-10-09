# ruff: noqa: SIM117
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg


class PostgresReminderStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def _connect(self):
        return await psycopg.AsyncConnection.connect(self.database_url)

    async def initialize(self) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,title TEXT NOT NULL,due_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,delivered_at TIMESTAMPTZ)"
                )

    async def create(self, user_id: str, title: str, due_at: str) -> dict:
        due = datetime.fromisoformat(due_at)
        if due.tzinfo is None or due.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("due_at must be a future ISO-8601 timestamp with timezone")
        if not title.strip():
            raise ValueError("Reminder title is required")
        item = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": title.strip(),
            "due_at": due.astimezone(UTC).isoformat(),
            "status": "scheduled",
        }
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO reminders(id,user_id,title,due_at,status,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                    (*item.values(), datetime.now(UTC)),
                )
        return item

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,title,due_at,status,delivered_at FROM reminders WHERE user_id=%s ORDER BY due_at DESC",
                    (user_id,),
                )
                rows = await cur.fetchall()
        return [
            {
                "id": row[0],
                "title": row[1],
                "due_at": row[2].isoformat(),
                "status": row[3],
                "delivered_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]

    async def claim_due(self) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "WITH due AS (SELECT id FROM reminders WHERE status='scheduled' AND due_at<=NOW() FOR UPDATE SKIP LOCKED) UPDATE reminders r SET status='delivering' FROM due WHERE r.id=due.id RETURNING r.id,r.user_id,r.title,r.due_at"
                )
                rows = await cur.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "title": row[2],
                "due_at": row[3].isoformat(),
            }
            for row in rows
        ]

    async def mark_delivered(self, reminder_id: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE reminders SET status='delivered', delivered_at=%s WHERE id=%s",
                    (datetime.now(UTC), reminder_id),
                )

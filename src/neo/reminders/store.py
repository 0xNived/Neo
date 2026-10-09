from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


class SqliteReminderStore:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY,user_id TEXT,title TEXT,due_at TEXT,status TEXT,created_at TEXT,delivered_at TEXT)"
            )
            await db.commit()

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
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO reminders(id,user_id,title,due_at,status,created_at) VALUES(?,?,?,?,?,?)",
                (*item.values(), datetime.now(UTC).isoformat()),
            )
            await db.commit()
        return item

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT id,title,due_at,status,delivered_at FROM reminders WHERE user_id=? ORDER BY due_at DESC",
                    (user_id,),
                )
            ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "due_at": r[2],
                "status": r[3],
                "delivered_at": r[4],
            }
            for r in rows
        ]

    async def claim_due(self) -> list[dict]:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT id,user_id,title,due_at FROM reminders WHERE status='scheduled' AND due_at<=?",
                    (now,),
                )
            ).fetchall()
            claimed = []
            for r in rows:
                cursor = await db.execute(
                    "UPDATE reminders SET status='delivering' WHERE id=? AND status='scheduled'",
                    (r[0],),
                )
                if cursor.rowcount:
                    claimed.append(
                        {"id": r[0], "user_id": r[1], "title": r[2], "due_at": r[3]}
                    )
            await db.commit()
        return claimed

    async def mark_delivered(self, reminder_id: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE reminders SET status='delivered',delivered_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), reminder_id),
            )
            await db.commit()

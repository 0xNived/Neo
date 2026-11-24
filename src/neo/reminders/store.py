from __future__ import annotations

import json
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
            columns = {
                row[1]
                for row in await (
                    await db.execute("PRAGMA table_info(reminders)")
                ).fetchall()
            }
            additions = {
                "kind": "TEXT NOT NULL DEFAULT 'notification'",
                "payload": "TEXT NOT NULL DEFAULT '{}'",
                "delivery_channel": "TEXT NOT NULL DEFAULT 'in_app'",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT",
                "schedule_type": "TEXT NOT NULL DEFAULT 'one_shot'",
                "repeat_every_seconds": "INTEGER",
                "execution_mode": "TEXT NOT NULL DEFAULT 'deliver'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    await db.execute(
                        f"ALTER TABLE reminders ADD COLUMN {name} {definition}"
                    )
            await db.commit()

    async def create(
        self,
        user_id: str,
        title: str,
        due_at: str,
        *,
        kind: str = "notification",
        payload: dict | None = None,
        delivery_channel: str = "in_app",
        schedule_type: str = "one_shot",
        repeat_every_seconds: int | None = None,
        execution_mode: str = "deliver",
    ) -> dict:
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
            "kind": kind,
            "payload": payload or {},
            "delivery_channel": delivery_channel,
            "schedule_type": schedule_type,
            "repeat_every_seconds": repeat_every_seconds,
            "execution_mode": execution_mode,
            "status": "scheduled",
        }
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO reminders(id,user_id,title,due_at,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"],
                    item["user_id"],
                    item["title"],
                    item["due_at"],
                    item["kind"],
                    json.dumps(item["payload"]),
                    item["delivery_channel"],
                    item["schedule_type"],
                    item["repeat_every_seconds"],
                    item["execution_mode"],
                    item["status"],
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()
        return item

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT id,title,due_at,status,delivered_at,kind,payload,delivery_channel,attempts,last_error,schedule_type,repeat_every_seconds,execution_mode FROM reminders WHERE user_id=? ORDER BY due_at DESC",
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
                "kind": r[5],
                "payload": json.loads(r[6] or "{}"),
                "delivery_channel": r[7],
                "attempts": r[8],
                "last_error": r[9],
                "schedule_type": r[10],
                "repeat_every_seconds": r[11],
                "execution_mode": r[12],
            }
            for r in rows
        ]

    async def update_context(
        self,
        user_id: str,
        reminder_id: str,
        *,
        body: str | None = None,
        url: str | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        """Amend delivery context without changing the schedule or title."""
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT id,title,due_at,status,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode FROM reminders WHERE id=? AND user_id=?",
                    (reminder_id, user_id),
                )
            ).fetchone()
            if not row:
                return None
            payload = json.loads(row[5] or "{}")
            if body is not None:
                payload["body"] = body
            if url is not None:
                payload["url"] = url
            if metadata is not None:
                payload["metadata"] = metadata
            await db.execute(
                "UPDATE reminders SET payload=? WHERE id=? AND user_id=?",
                (json.dumps(payload), reminder_id, user_id),
            )
            await db.commit()
        return {
            "id": row[0], "title": row[1], "due_at": row[2], "status": row[3],
            "kind": row[4], "payload": payload, "delivery_channel": row[6],
            "schedule_type": row[7], "repeat_every_seconds": row[8],
            "execution_mode": row[9],
        }

    async def update(
        self, user_id: str, reminder_id: str, **changes
    ) -> dict | None:
        """Apply a partial edit without replacing the reminder record."""
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT id,title,due_at,status,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode "
                    "FROM reminders WHERE id=? AND user_id=?",
                    (reminder_id, user_id),
                )
            ).fetchone()
            if not row:
                return None
            payload = json.loads(row[5] or "{}")
            for key in ("body", "url", "metadata"):
                if key in changes:
                    payload[key] = changes[key]
            title = changes.get("title", row[1])
            due_at = changes.get("due_at", row[2])
            schedule_type = changes.get("schedule_type", row[7])
            repeat_every_seconds = changes.get(
                "repeat_every_seconds", row[8]
            )
            if schedule_type == "one_shot" and "repeat_every_seconds" not in changes:
                repeat_every_seconds = None
            await db.execute(
                "UPDATE reminders SET title=?,due_at=?,payload=?,schedule_type=?,repeat_every_seconds=?,status='scheduled',last_error=NULL "
                "WHERE id=? AND user_id=?",
                (
                    title,
                    due_at,
                    json.dumps(payload),
                    schedule_type,
                    repeat_every_seconds,
                    reminder_id,
                    user_id,
                ),
            )
            await db.commit()
        return {
            "id": row[0], "title": title, "due_at": due_at, "status": "scheduled",
            "kind": row[4], "payload": payload, "delivery_channel": row[6],
            "schedule_type": schedule_type,
            "repeat_every_seconds": repeat_every_seconds,
            "execution_mode": row[9],
        }

    async def claim_due(self) -> list[dict]:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT id,user_id,title,due_at,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode FROM reminders WHERE status='scheduled' AND due_at<=?",
                    (now,),
                )
            ).fetchall()
            claimed = []
            for r in rows:
                cursor = await db.execute(
                    "UPDATE reminders SET status='delivering',attempts=attempts+1 WHERE id=? AND status='scheduled'",
                    (r[0],),
                )
                if cursor.rowcount:
                    claimed.append(
                        {
                            "id": r[0],
                            "user_id": r[1],
                            "title": r[2],
                            "due_at": r[3],
                            "kind": r[4],
                            "payload": json.loads(r[5] or "{}"),
                            "delivery_channel": r[6],
                            "schedule_type": r[7],
                            "repeat_every_seconds": r[8],
                            "execution_mode": r[9],
                        }
                    )
            await db.commit()
        return claimed

    async def mark_failed(self, reminder_id: str, error: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE reminders SET status='failed',last_error=? WHERE id=?",
                (error[:500], reminder_id),
            )
            await db.commit()

    async def mark_ready(self, reminder_id: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE reminders SET status='ready',last_error=NULL WHERE id=?",
                (reminder_id,),
            )
            await db.commit()

    async def acknowledge(self, user_id: str, reminder_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "UPDATE reminders SET status=CASE WHEN schedule_type='interval' THEN 'scheduled' ELSE 'delivered' END, delivered_at=?, due_at=CASE WHEN schedule_type='interval' THEN datetime('now', '+' || repeat_every_seconds || ' seconds') ELSE due_at END WHERE id=? AND user_id=? AND status='ready'",
                (datetime.now(UTC).isoformat(), reminder_id, user_id),
            )
            await db.commit()
            return bool(cursor.rowcount)

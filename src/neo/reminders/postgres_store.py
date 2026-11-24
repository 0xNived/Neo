# ruff: noqa: SIM117
from __future__ import annotations

import json
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
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'notification'"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS delivery_channel TEXT NOT NULL DEFAULT 'in_app'"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS last_error TEXT"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS schedule_type TEXT NOT NULL DEFAULT 'one_shot'"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS repeat_every_seconds INTEGER"
                )
                await cur.execute(
                    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS execution_mode TEXT NOT NULL DEFAULT 'deliver'"
                )

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
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO reminders(id,user_id,title,due_at,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode,status,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                        datetime.now(UTC),
                    ),
                )
        return item

    async def list_for_user(self, user_id: str) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,title,due_at,status,delivered_at,kind,payload,delivery_channel,attempts,last_error,schedule_type,repeat_every_seconds,execution_mode FROM reminders WHERE user_id=%s ORDER BY due_at DESC",
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
                "kind": row[5],
                "payload": row[6] if isinstance(row[6], dict) else json.loads(row[6]),
                "delivery_channel": row[7],
                "attempts": row[8],
                "last_error": row[9],
                "schedule_type": row[10],
                "repeat_every_seconds": row[11],
                "execution_mode": row[12],
            }
            for row in rows
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
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,title,due_at,status,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode "
                    "FROM reminders WHERE id=%s AND user_id=%s FOR UPDATE",
                    (reminder_id, user_id),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                payload = row[5] if isinstance(row[5], dict) else json.loads(row[5])
                if body is not None:
                    payload["body"] = body
                if url is not None:
                    payload["url"] = url
                if metadata is not None:
                    payload["metadata"] = metadata
                await cur.execute(
                    "UPDATE reminders SET payload=%s WHERE id=%s AND user_id=%s",
                    (json.dumps(payload), reminder_id, user_id),
                )
        return {
            "id": row[0], "title": row[1], "due_at": row[2].isoformat(),
            "status": row[3], "kind": row[4], "payload": payload,
            "delivery_channel": row[6], "schedule_type": row[7],
            "repeat_every_seconds": row[8], "execution_mode": row[9],
        }

    async def update(
        self, user_id: str, reminder_id: str, **changes
    ) -> dict | None:
        """Apply a partial edit without replacing the reminder record."""
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,title,due_at,status,kind,payload,delivery_channel,schedule_type,repeat_every_seconds,execution_mode "
                    "FROM reminders WHERE id=%s AND user_id=%s FOR UPDATE",
                    (reminder_id, user_id),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                payload = row[5] if isinstance(row[5], dict) else json.loads(row[5])
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
                await cur.execute(
                    "UPDATE reminders SET title=%s,due_at=%s,payload=%s,schedule_type=%s,repeat_every_seconds=%s,status='scheduled',last_error=NULL "
                    "WHERE id=%s AND user_id=%s",
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
        return {
            "id": row[0], "title": title, "due_at": due_at.isoformat() if hasattr(due_at, "isoformat") else due_at,
            "status": "scheduled", "kind": row[4], "payload": payload,
            "delivery_channel": row[6], "schedule_type": schedule_type,
            "repeat_every_seconds": repeat_every_seconds,
            "execution_mode": row[9],
        }

    async def claim_due(self) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "WITH due AS (SELECT id FROM reminders WHERE status='scheduled' AND due_at<=NOW() FOR UPDATE SKIP LOCKED) UPDATE reminders r SET status='delivering',attempts=r.attempts+1 FROM due WHERE r.id=due.id RETURNING r.id,r.user_id,r.title,r.due_at,r.kind,r.payload,r.delivery_channel,r.schedule_type,r.repeat_every_seconds,r.execution_mode"
                )
                rows = await cur.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "title": row[2],
                "due_at": row[3].isoformat(),
                "kind": row[4],
                "payload": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                "delivery_channel": row[6],
                "schedule_type": row[7],
                "repeat_every_seconds": row[8],
                "execution_mode": row[9],
            }
            for row in rows
        ]

    async def mark_ready(self, reminder_id: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE reminders SET status='ready',last_error=NULL WHERE id=%s",
                    (reminder_id,),
                )

    async def acknowledge(self, user_id: str, reminder_id: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE reminders SET status=CASE WHEN schedule_type='interval' THEN 'scheduled' ELSE 'delivered' END, delivered_at=%s, due_at=CASE WHEN schedule_type='interval' THEN NOW() + (repeat_every_seconds * INTERVAL '1 second') ELSE due_at END WHERE id=%s AND user_id=%s AND status='ready'",
                    (datetime.now(UTC), reminder_id, user_id),
                )
                return bool(cur.rowcount)

    async def mark_failed(self, reminder_id: str, error: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE reminders SET status='failed',last_error=%s WHERE id=%s",
                    (error[:500], reminder_id),
                )

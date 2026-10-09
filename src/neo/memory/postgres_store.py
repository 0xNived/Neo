# ruff: noqa: SIM117
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import psycopg

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class PostgresMemoryStore:
    def __init__(self, database_url: str, ttl_days: int):
        self.database_url, self.ttl_days = database_url, ttl_days

    async def _connect(self):
        return await psycopg.AsyncConnection.connect(self.database_url)

    async def initialize(self) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS memories (id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.7, created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ, UNIQUE(user_id, category, content))"
                )
                await cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS memory_key TEXT")
                await cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS memories_owner_key_unique ON memories(user_id,category,memory_key) WHERE memory_key IS NOT NULL")
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tool_name TEXT NOT NULL, payload JSONB NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)"
                )
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS neo_migrations (name TEXT PRIMARY KEY, completed_at TIMESTAMPTZ NOT NULL)"
                )
                await cur.execute(
                    "DELETE FROM approvals WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id, tool_name, payload->>'session_id' ORDER BY created_at DESC) AS row_number FROM approvals WHERE status='pending') duplicates WHERE row_number > 1)"
                )

    async def migration_completed(self, name: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT 1 FROM neo_migrations WHERE name=%s", (name,))
                return bool(await cur.fetchone())

    async def mark_migration_completed(self, name: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO neo_migrations(name,completed_at) VALUES(%s,%s) ON CONFLICT(name) DO NOTHING",
                    (name, datetime.now(UTC)),
                )

    def _expiry(self, category: str, override: int | None) -> datetime | None:
        if category in {"identity", "birthday"}:
            return datetime.now(UTC) + timedelta(days=override or 3650)
        if category == "preference":
            return datetime.now(UTC) + timedelta(days=override or 365)
        return datetime.now(UTC) + timedelta(days=override or self.ttl_days)

    async def remember(
        self,
        user_id: str,
        content: str,
        category: str = "semantic",
        ttl_days: int | None = None,
        confidence: float = 0.7,
        memory_key: str | None = None,
    ) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO memories(user_id,category,content,confidence,created_at,expires_at,memory_key) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO UPDATE SET content=EXCLUDED.content,confidence=EXCLUDED.confidence,created_at=EXCLUDED.created_at,expires_at=EXCLUDED.expires_at,memory_key=EXCLUDED.memory_key",
                    (
                        user_id,
                        category,
                        content,
                        max(0.0, min(confidence, 1.0)),
                        datetime.now(UTC),
                        self._expiry(category, ttl_days),
                        memory_key,
                    ),
                )

    async def recall(self, user_id: str, query: str, limit: int = 6) -> list[str]:
        words = [word.lower() for word in query.split() if len(word) > 2]
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < NOW()"
                )
                await cur.execute(
                    "SELECT content FROM memories WHERE user_id=%s ORDER BY confidence DESC,id DESC LIMIT 100",
                    (user_id,),
                )
                rows = await cur.fetchall()
        return [
            row[0]
            for row in rows
            if not words or any(word in row[0].lower() for word in words)
        ][:limit]

    async def list_category(
        self, user_id: str, category: str, limit: int = 8
    ) -> list[str]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < NOW()"
                )
                await cur.execute(
                    "SELECT content FROM memories WHERE user_id=%s AND category=%s ORDER BY confidence DESC,id DESC LIMIT %s",
                    (user_id, category, limit),
                )
                return [row[0] for row in await cur.fetchall()]

    async def forget(self, user_id: str, needle: str) -> int:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "DELETE FROM memories WHERE user_id=%s AND content ILIKE %s",
                    (user_id, f"%{needle}%"),
                )
                return cur.rowcount

    async def create_approval(
        self, approval_id: str, user_id: str, tool_name: str, payload: dict
    ) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO approvals VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        approval_id,
                        user_id,
                        tool_name,
                        json.dumps(payload),
                        "pending",
                        datetime.now(UTC),
                    ),
                )

    async def list_pending_approvals(self, user_id: str) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,tool_name,payload,created_at FROM approvals WHERE user_id=%s AND status='pending' ORDER BY created_at DESC",
                    (user_id,),
                )
                rows = await cur.fetchall()
        return [
            {
                "id": row[0],
                "tool_name": row[1],
                "payload": row[2] if isinstance(row[2], dict) else json.loads(row[2]),
                "created_at": row[3].isoformat(),
            }
            for row in rows
        ]

    async def resolve_approval(self, approval_id: str, approved: bool) -> dict | None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT user_id,tool_name,payload,status FROM approvals WHERE id=%s FOR UPDATE",
                    (approval_id,),
                )
                row = await cur.fetchone()
                if not row or row[3] != "pending":
                    return None
                await cur.execute(
                    "UPDATE approvals SET status=%s WHERE id=%s",
                    ("approved" if approved else "denied", approval_id),
                )
        return {
            "user_id": row[0],
            "tool_name": row[1],
            "payload": row[2] if isinstance(row[2], dict) else json.loads(row[2]),
            "approved": approved,
        }

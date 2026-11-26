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
                await cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'owner'")
                await cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_session_id TEXT")
                await cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
                await cur.execute("UPDATE memories SET updated_at=created_at WHERE updated_at IS NULL")
                await cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS memories_owner_key_unique ON memories(user_id,category,memory_key) WHERE memory_key IS NOT NULL")
                await cur.execute("CREATE INDEX IF NOT EXISTS memories_owner_category_idx ON memories(user_id,category,updated_at DESC)")
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS memory_events (id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,category TEXT NOT NULL,memory_key TEXT,content TEXT NOT NULL,action TEXT NOT NULL,source_kind TEXT NOT NULL,source_session_id TEXT,occurred_at TIMESTAMPTZ NOT NULL)"
                )
                await cur.execute(
                    "CREATE INDEX IF NOT EXISTS memory_events_owner_lookup_idx ON memory_events(user_id,category,memory_key,occurred_at DESC)"
                )
                # Candidate rows are the durable, auditable first stage of
                # memory.  They are deliberately separate from `memories`:
                # an observation is not a profile fact until it has been
                # validated and promoted.
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS memory_candidates (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source_session_id TEXT,source_message TEXT NOT NULL,context_messages JSONB NOT NULL DEFAULT '[]'::jsonb,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'captured',extracted JSONB NOT NULL DEFAULT '[]'::jsonb,reason TEXT,created_at TIMESTAMPTZ NOT NULL,promoted_at TIMESTAMPTZ,next_attempt_at TIMESTAMPTZ)"
                )
                await cur.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS context_messages JSONB NOT NULL DEFAULT '[]'::jsonb")
                await cur.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ")
                await cur.execute(
                    "CREATE INDEX IF NOT EXISTS memory_candidates_owner_status_idx ON memory_candidates(user_id,status,created_at DESC)"
                )
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
        source_kind: str = "owner",
        source_session_id: str | None = None,
    ) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                if memory_key:
                    await cur.execute(
                        "SELECT 1 FROM memories WHERE user_id=%s AND category=%s AND memory_key=%s",
                        (user_id, category, memory_key),
                    )
                else:
                    await cur.execute(
                        "SELECT 1 FROM memories WHERE user_id=%s AND category=%s AND content=%s",
                        (user_id, category, content),
                    )
                action = "updated" if await cur.fetchone() else "created"
                values = (
                    user_id,
                    category,
                    content,
                    max(0.0, min(confidence, 1.0)),
                    datetime.now(UTC),
                    self._expiry(category, ttl_days),
                    memory_key,
                    source_kind,
                    source_session_id,
                )
                if memory_key:
                    # This targets the partial unique index created in initialize().
                    # PostgreSQL cannot infer a partial index from a bare ON CONFLICT.
                    query = (
                        "INSERT INTO memories(user_id,category,content,confidence,created_at,expires_at,memory_key,source_kind,source_session_id,updated_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(user_id,category,memory_key) WHERE memory_key IS NOT NULL "
                        "DO UPDATE SET content=EXCLUDED.content,confidence=EXCLUDED.confidence,"
                        "expires_at=EXCLUDED.expires_at,source_kind=EXCLUDED.source_kind,"
                        "source_session_id=EXCLUDED.source_session_id,updated_at=EXCLUDED.updated_at"
                    )
                else:
                    query = (
                        "INSERT INTO memories(user_id,category,content,confidence,created_at,expires_at,memory_key,source_kind,source_session_id,updated_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(user_id,category,content) "
                        "DO UPDATE SET confidence=GREATEST(memories.confidence,EXCLUDED.confidence),"
                        "expires_at=EXCLUDED.expires_at,source_kind=EXCLUDED.source_kind,"
                        "source_session_id=EXCLUDED.source_session_id,updated_at=EXCLUDED.updated_at"
                    )
                occurred_at = datetime.now(UTC)
                await cur.execute(query, (*values, occurred_at))
                await cur.execute(
                    "INSERT INTO memory_events(user_id,category,memory_key,content,action,source_kind,source_session_id,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (user_id, category, memory_key, content, action, source_kind, source_session_id, occurred_at),
                )

    async def capture_candidate(
        self,
        user_id: str,
        source_message: str,
        *,
        source_session_id: str | None = None,
        kind: str = "owner_message",
        context_messages: list[dict] | None = None,
        extracted: list[dict] | None = None,
        reason: str | None = None,
    ) -> str:
        """Persist a possible memory before any background consolidation.

        This is provenance, not an automatic promise that the message has
        become durable profile memory.
        """
        candidate_id = str(__import__("uuid").uuid4())
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "INSERT INTO memory_candidates(id,user_id,source_session_id,source_message,context_messages,kind,status,extracted,reason,created_at) VALUES(%s,%s,%s,%s,%s,%s,'captured',%s,%s,%s)",
                    (candidate_id, user_id, source_session_id, source_message[:4000], json.dumps((context_messages or [])[-6:]), kind, json.dumps(extracted or []), reason, datetime.now(UTC)),
                )
        return candidate_id

    async def mark_candidate_promoted(self, candidate_id: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE memory_candidates SET status='promoted',promoted_at=%s WHERE id=%s",
                    (datetime.now(UTC), candidate_id),
                )

    async def mark_candidate_dismissed(self, candidate_id: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE memory_candidates SET status='dismissed' WHERE id=%s AND status='captured'",
                    (candidate_id,),
                )

    async def defer_candidate(self, candidate_id: str) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "UPDATE memory_candidates SET next_attempt_at=NOW() + INTERVAL '5 minutes' WHERE id=%s AND status='captured'",
                    (candidate_id,),
                )

    async def list_candidates(self, user_id: str, status: str = "captured", limit: int = 32, ready_only: bool = False) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT id,source_session_id,source_message,context_messages,kind,status,extracted,reason,created_at,promoted_at,next_attempt_at FROM memory_candidates WHERE user_id=%s AND status=%s "
                    + ("AND (next_attempt_at IS NULL OR next_attempt_at<=NOW()) " if ready_only else "")
                    + "ORDER BY created_at ASC LIMIT %s",
                    (user_id, status, limit),
                )
                rows = await cur.fetchall()
        keys = ("id", "source_session_id", "source_message", "context_messages", "kind", "status", "extracted", "reason", "created_at", "promoted_at", "next_attempt_at")
        return [
            {
                key: (value.isoformat() if key.endswith("_at") and value else value)
                for key, value in zip(keys, row, strict=True)
            }
            for row in rows
        ]

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

    async def list_records(
        self, user_id: str, categories: list[str] | None = None, limit: int = 24
    ) -> list[dict]:
        """Return compact, provenance-bearing records for profile/debug tooling."""
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < NOW()"
                )
                if categories:
                    await cur.execute(
                        "SELECT category,content,confidence,memory_key,source_kind,source_session_id,created_at,updated_at,expires_at "
                        "FROM memories WHERE user_id=%s AND category = ANY(%s) "
                        "ORDER BY confidence DESC,updated_at DESC LIMIT %s",
                        (user_id, categories, limit),
                    )
                else:
                    await cur.execute(
                        "SELECT category,content,confidence,memory_key,source_kind,source_session_id,created_at,updated_at,expires_at "
                        "FROM memories WHERE user_id=%s ORDER BY confidence DESC,updated_at DESC LIMIT %s",
                        (user_id, limit),
                    )
                rows = await cur.fetchall()
        keys = ("category", "content", "confidence", "memory_key", "source_kind", "source_session_id", "created_at", "updated_at", "expires_at")
        return [
            {key: value.isoformat() if key.endswith("_at") and value else value for key, value in zip(keys, row, strict=True)}
            for row in rows
        ]

    async def list_history(
        self,
        user_id: str,
        category: str | None = None,
        memory_key: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Return immutable durable-memory write history for owner questions."""
        conditions = ["user_id=%s"]
        values: list[object] = [user_id]
        if category:
            conditions.append("category=%s")
            values.append(category)
        if memory_key:
            conditions.append("memory_key=%s")
            values.append(memory_key)
        values.append(limit)
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT category,memory_key,content,action,source_kind,source_session_id,occurred_at "
                    "FROM memory_events WHERE " + " AND ".join(conditions) + " "
                    "ORDER BY occurred_at DESC LIMIT %s",
                    tuple(values),
                )
                rows = await cur.fetchall()
        keys = ("category", "memory_key", "content", "action", "source_kind", "source_session_id", "occurred_at")
        return [
            {key: value.isoformat() if key == "occurred_at" and value else value for key, value in zip(keys, row, strict=True)}
            for row in rows
        ]

    async def forget(self, user_id: str, needle: str) -> int:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT category,memory_key,content,source_kind,source_session_id FROM memories WHERE user_id=%s AND content ILIKE %s",
                    (user_id, f"%{needle}%"),
                )
                removed = await cur.fetchall()
                await cur.execute(
                    "DELETE FROM memories WHERE user_id=%s AND content ILIKE %s",
                    (user_id, f"%{needle}%"),
                )
                deleted_count = cur.rowcount
                for category, memory_key, content, source_kind, source_session_id in removed:
                    await cur.execute(
                        "INSERT INTO memory_events(user_id,category,memory_key,content,action,source_kind,source_session_id,occurred_at) VALUES(%s,%s,%s,%s,'deleted',%s,%s,%s)",
                        (user_id, category, memory_key, content, source_kind, source_session_id, datetime.now(UTC)),
                    )
                return deleted_count

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

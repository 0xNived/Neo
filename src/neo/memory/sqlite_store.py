from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite


class SqliteMemoryStore:
    def __init__(self, path: Path, ttl_days: int):
        self.path, self.ttl_days = path, ttl_days

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.7, created_at TEXT NOT NULL, expires_at TEXT)"
            )
            columns = [
                row[1]
                for row in await (
                    await db.execute("PRAGMA table_info(memories)")
                ).fetchall()
            ]
            if "confidence" not in columns:
                await db.execute(
                    "ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.7"
                )
            if "memory_key" not in columns:
                await db.execute("ALTER TABLE memories ADD COLUMN memory_key TEXT")
            if "source_kind" not in columns:
                await db.execute("ALTER TABLE memories ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'owner'")
            if "source_session_id" not in columns:
                await db.execute("ALTER TABLE memories ADD COLUMN source_session_id TEXT")
            if "updated_at" not in columns:
                await db.execute("ALTER TABLE memories ADD COLUMN updated_at TEXT")
                await db.execute("UPDATE memories SET updated_at=created_at WHERE updated_at IS NULL")
            await db.execute(
                "DELETE FROM memories WHERE id NOT IN (SELECT MAX(id) FROM memories GROUP BY user_id,category,content)"
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS memories_unique ON memories(user_id,category,content)"
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS memories_owner_key_unique ON memories(user_id,category,memory_key) WHERE memory_key IS NOT NULL"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tool_name TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS memory_candidates (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source_session_id TEXT,source_message TEXT NOT NULL,context_messages TEXT NOT NULL DEFAULT '[]',kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'captured',extracted TEXT NOT NULL DEFAULT '[]',reason TEXT,created_at TEXT NOT NULL,promoted_at TEXT)"
            )
            columns = [row[1] for row in await (await db.execute("PRAGMA table_info(memory_candidates)")).fetchall()]
            if "context_messages" not in columns:
                await db.execute("ALTER TABLE memory_candidates ADD COLUMN context_messages TEXT NOT NULL DEFAULT '[]'")
            await db.execute(
                "CREATE TABLE IF NOT EXISTS memory_events (id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,category TEXT NOT NULL,memory_key TEXT,content TEXT NOT NULL,action TEXT NOT NULL,source_kind TEXT NOT NULL,source_session_id TEXT,occurred_at TEXT NOT NULL)"
            )
            await db.execute("CREATE INDEX IF NOT EXISTS memory_events_owner_lookup_idx ON memory_events(user_id,category,memory_key,occurred_at DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS memory_candidates_owner_status_idx ON memory_candidates(user_id,status,created_at DESC)")
            await db.execute(
                "DELETE FROM approvals WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id, tool_name, json_extract(payload, '$.session_id') ORDER BY created_at DESC) AS row_number FROM approvals WHERE status='pending') duplicates WHERE row_number > 1)"
            )
            await db.commit()

    async def capture_candidate(self, user_id: str, source_message: str, *, source_session_id: str | None = None, kind: str = "owner_message", context_messages: list[dict] | None = None, extracted: list[dict] | None = None, reason: str | None = None) -> str:
        import uuid
        candidate_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO memory_candidates(id,user_id,source_session_id,source_message,context_messages,kind,status,extracted,reason,created_at) VALUES(?,?,?,?,?,?,'captured',?,?,?)",
                (candidate_id, user_id, source_session_id, source_message[:4000], json.dumps((context_messages or [])[-6:]), kind, json.dumps(extracted or []), reason, datetime.now(UTC).isoformat()),
            )
            await db.commit()
        return candidate_id

    async def mark_candidate_promoted(self, candidate_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE memory_candidates SET status='promoted',promoted_at=? WHERE id=?", (datetime.now(UTC).isoformat(), candidate_id))
            await db.commit()

    async def mark_candidate_dismissed(self, candidate_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE memory_candidates SET status='dismissed' WHERE id=? AND status='captured'",
                (candidate_id,),
            )
            await db.commit()

    async def list_candidates(self, user_id: str, status: str = "captured", limit: int = 32) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute("SELECT id,source_session_id,source_message,context_messages,kind,status,extracted,reason,created_at,promoted_at FROM memory_candidates WHERE user_id=? AND status=? ORDER BY created_at ASC LIMIT ?", (user_id, status, limit))).fetchall()
        keys = ("id", "source_session_id", "source_message", "context_messages", "kind", "status", "extracted", "reason", "created_at", "promoted_at")
        return [dict(zip(keys, row, strict=True)) for row in rows]

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
        expires = datetime.now(UTC) + timedelta(days=ttl_days or self.ttl_days)
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            if memory_key:
                existing = await (
                    await db.execute(
                        "SELECT 1 FROM memories WHERE user_id=? AND category=? AND memory_key=?",
                        (user_id, category, memory_key),
                    )
                ).fetchone()
            else:
                existing = await (
                    await db.execute(
                        "SELECT 1 FROM memories WHERE user_id=? AND category=? AND content=?",
                        (user_id, category, content),
                    )
                ).fetchone()
            action = "updated" if existing else "created"
            values = (user_id, category, content, max(0.0, min(confidence, 1.0)), now, expires.isoformat(), memory_key, source_kind, source_session_id, now)
            if memory_key:
                await db.execute(
                    "INSERT INTO memories(user_id,category,content,confidence,created_at,expires_at,memory_key,source_kind,source_session_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(user_id,category,memory_key) WHERE memory_key IS NOT NULL DO UPDATE SET content=excluded.content,confidence=excluded.confidence,expires_at=excluded.expires_at,source_kind=excluded.source_kind,source_session_id=excluded.source_session_id,updated_at=excluded.updated_at",
                    values,
                )
            else:
                await db.execute(
                    "INSERT INTO memories(user_id,category,content,confidence,created_at,expires_at,memory_key,source_kind,source_session_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(user_id,category,content) DO UPDATE SET confidence=MAX(memories.confidence,excluded.confidence),expires_at=excluded.expires_at,source_kind=excluded.source_kind,source_session_id=excluded.source_session_id,updated_at=excluded.updated_at",
                    values,
                )
            await db.execute(
                "INSERT INTO memory_events(user_id,category,memory_key,content,action,source_kind,source_session_id,occurred_at) VALUES(?,?,?,?,?,?,?,?)",
                (user_id, category, memory_key, content, action, source_kind, source_session_id, now),
            )
            await db.commit()

    async def recall(self, user_id: str, query: str, limit: int = 6) -> list[str]:
        now = datetime.now(UTC).isoformat()
        words = [word.lower() for word in query.split() if len(word) > 2]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            rows = await (
                await db.execute(
                    "SELECT content FROM memories WHERE user_id=? ORDER BY confidence DESC, id DESC LIMIT 100",
                    (user_id,),
                )
            ).fetchall()
            await db.commit()
        return [
            row[0]
            for row in rows
            if not words or any(word in row[0].lower() for word in words)
        ][:limit]

    async def forget(self, user_id: str, needle: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT category,memory_key,content,source_kind,source_session_id FROM memories WHERE user_id=? AND content LIKE ?",
                    (user_id, f"%{needle}%"),
                )
            ).fetchall()
            cursor = await db.execute(
                "DELETE FROM memories WHERE user_id=? AND content LIKE ?",
                (user_id, f"%{needle}%"),
            )
            now = datetime.now(UTC).isoformat()
            for category, memory_key, content, source_kind, source_session_id in rows:
                await db.execute(
                    "INSERT INTO memory_events(user_id,category,memory_key,content,action,source_kind,source_session_id,occurred_at) VALUES(?,?,?,?, 'deleted',?,?,?)",
                    (user_id, category, memory_key, content, source_kind, source_session_id, now),
                )
            await db.commit()
            return cursor.rowcount

    async def list_category(
        self, user_id: str, category: str, limit: int = 8
    ) -> list[str]:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            rows = await (
                await db.execute(
                    "SELECT content FROM memories WHERE user_id=? AND category=? ORDER BY confidence DESC,id DESC LIMIT ?",
                    (user_id, category, limit),
                )
            ).fetchall()
            await db.commit()
        return [row[0] for row in rows]

    async def list_records(
        self, user_id: str, categories: list[str] | None = None, limit: int = 24
    ) -> list[dict]:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            if categories:
                placeholders = ",".join("?" for _ in categories)
                query = f"SELECT category,content,confidence,memory_key,source_kind,source_session_id,created_at,updated_at,expires_at FROM memories WHERE user_id=? AND category IN ({placeholders}) ORDER BY confidence DESC,updated_at DESC LIMIT ?"
                rows = await (await db.execute(query, (user_id, *categories, limit))).fetchall()
            else:
                rows = await (await db.execute("SELECT category,content,confidence,memory_key,source_kind,source_session_id,created_at,updated_at,expires_at FROM memories WHERE user_id=? ORDER BY confidence DESC,updated_at DESC LIMIT ?", (user_id, limit))).fetchall()
            await db.commit()
        keys = ("category", "content", "confidence", "memory_key", "source_kind", "source_session_id", "created_at", "updated_at", "expires_at")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    async def list_history(
        self,
        user_id: str,
        category: str | None = None,
        memory_key: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        conditions = ["user_id=?"]
        values: list[object] = [user_id]
        if category:
            conditions.append("category=?")
            values.append(category)
        if memory_key:
            conditions.append("memory_key=?")
            values.append(memory_key)
        values.append(limit)
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT category,memory_key,content,action,source_kind,source_session_id,occurred_at FROM memory_events WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY occurred_at DESC LIMIT ?",
                    tuple(values),
                )
            ).fetchall()
        keys = ("category", "memory_key", "content", "action", "source_kind", "source_session_id", "occurred_at")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    async def create_approval(
        self, approval_id: str, user_id: str, tool_name: str, payload: dict
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO approvals VALUES(?,?,?,?,?,?)",
                (
                    approval_id,
                    user_id,
                    tool_name,
                    json.dumps(payload),
                    "pending",
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def list_pending_approvals(self, user_id: str) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    "SELECT id,tool_name,payload,created_at FROM approvals WHERE user_id=? AND status='pending' ORDER BY created_at DESC",
                    (user_id,),
                )
            ).fetchall()
        return [
            {
                "id": row[0],
                "tool_name": row[1],
                "payload": json.loads(row[2]),
                "created_at": row[3],
            }
            for row in rows
        ]

    async def resolve_approval(self, approval_id: str, approved: bool) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT user_id,tool_name,payload,status FROM approvals WHERE id=?",
                    (approval_id,),
                )
            ).fetchone()
            if not row or row[3] != "pending":
                return None
            await db.execute(
                "UPDATE approvals SET status=? WHERE id=?",
                ("approved" if approved else "denied", approval_id),
            )
            await db.commit()
        return {
            "user_id": row[0],
            "tool_name": row[1],
            "payload": json.loads(row[2]),
            "approved": approved,
        }

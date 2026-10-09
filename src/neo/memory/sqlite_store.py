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
            await db.execute(
                "DELETE FROM memories WHERE id NOT IN (SELECT MAX(id) FROM memories GROUP BY user_id,category,content)"
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS memories_unique ON memories(user_id,category,content)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tool_name TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            await db.execute(
                "DELETE FROM approvals WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id, tool_name, json_extract(payload, '$.session_id') ORDER BY created_at DESC) AS row_number FROM approvals WHERE status='pending') duplicates WHERE row_number > 1)"
            )
            await db.commit()

    async def remember(
        self,
        user_id: str,
        content: str,
        category: str = "semantic",
        ttl_days: int | None = None,
        confidence: float = 0.7,
    ) -> None:
        expires = datetime.now(UTC) + timedelta(days=ttl_days or self.ttl_days)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO memories(user_id,category,content,confidence,created_at,expires_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,category,content) DO UPDATE SET confidence=MAX(memories.confidence,excluded.confidence),created_at=excluded.created_at,expires_at=excluded.expires_at",
                (
                    user_id,
                    category,
                    content,
                    max(0.0, min(confidence, 1.0)),
                    datetime.now(UTC).isoformat(),
                    expires.isoformat(),
                ),
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
            cursor = await db.execute(
                "DELETE FROM memories WHERE user_id=? AND content LIKE ?",
                (user_id, f"%{needle}%"),
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

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import UTC, datetime

import httpx
import psycopg

from .embeddings import embed
from .link_enrichment import fetch_page_context
from .references import normalize_references


class OrganizerStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def _connect(self):
        return await psycopg.AsyncConnection.connect(self.database_url)

    async def initialize(self) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("CREATE TABLE IF NOT EXISTS organizer_groups (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL)")
                await cur.execute("ALTER TABLE organizer_groups ADD COLUMN IF NOT EXISTS parent_id TEXT REFERENCES organizer_groups(id) ON DELETE SET NULL")
                await cur.execute("ALTER TABLE organizer_groups ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
                await cur.execute("CREATE TABLE IF NOT EXISTS organizer_items (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,group_id TEXT NOT NULL REFERENCES organizer_groups(id) ON DELETE CASCADE,kind TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL DEFAULT '',url TEXT,metadata JSONB NOT NULL DEFAULT '{}',checked BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)")
                await cur.execute("ALTER TABLE organizer_items ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
                await cur.execute("ALTER TABLE organizer_items ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT ''")
                await cur.execute("UPDATE organizer_items SET summary=LEFT(COALESCE(NULLIF(regexp_replace(content, '\\s+', ' ', 'g'), ''), title),220) WHERE summary='' ")
                await cur.execute("UPDATE organizer_items SET metadata=jsonb_set(COALESCE(metadata,'{}'::jsonb), '{summary}', to_jsonb(summary), true) WHERE NOT (metadata ? 'summary')")
                await cur.execute("UPDATE organizer_items SET metadata=COALESCE(metadata,'{}'::jsonb) || jsonb_build_object('schema_version',1,'summary',summary,'source',COALESCE(metadata->>'source','organizer'),'content_length',length(content),'has_url',(url IS NOT NULL))")
                await cur.execute("UPDATE organizer_items SET metadata=metadata || jsonb_build_object('record_type','wallet_address','network','litecoin','private',true) WHERE lower(title) LIKE '%%litecoin%%' OR (lower(greatest(content,'')) LIKE '%%ltc1%%' OR content ~ '(^|[^A-Za-z0-9])[LM][1-9A-HJ-NP-Za-km-z]{25,34}([^A-Za-z0-9]|$)')")
                # Merge duplicates created by the first Organizer UI before
                # applying the uniqueness constraint.  Items are retained in
                # the oldest collection rather than being discarded.
                await cur.execute("WITH ranked AS (SELECT id,user_id,name,first_value(id) OVER (PARTITION BY user_id,lower(name) ORDER BY created_at,id) AS keep_id,row_number() OVER (PARTITION BY user_id,lower(name) ORDER BY created_at,id) AS rn FROM organizer_groups) UPDATE organizer_items i SET group_id=ranked.keep_id FROM ranked WHERE i.group_id=ranked.id AND ranked.rn>1")
                await cur.execute("WITH ranked AS (SELECT id,row_number() OVER (PARTITION BY user_id,lower(name) ORDER BY created_at,id) AS rn FROM organizer_groups) DELETE FROM organizer_groups g USING ranked WHERE g.id=ranked.id AND ranked.rn>1")
                # Avoid future duplicates even when a write is retried.
                await cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS organizer_groups_owner_name_unique ON organizer_groups(user_id, lower(name))")
                await cur.execute("CREATE INDEX IF NOT EXISTS organizer_items_search_idx ON organizer_items USING GIN (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,'')))")
                await cur.execute("CREATE TABLE IF NOT EXISTS organizer_chunks (id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES organizer_items(id) ON DELETE CASCADE,ordinal INTEGER NOT NULL,content TEXT NOT NULL,metadata JSONB NOT NULL DEFAULT '{}',created_at TIMESTAMPTZ NOT NULL)")
                await cur.execute("ALTER TABLE organizer_chunks ADD COLUMN IF NOT EXISTS embedding JSONB")
                await cur.execute("CREATE INDEX IF NOT EXISTS organizer_chunks_search_idx ON organizer_chunks USING GIN (to_tsvector('simple', content))")

    async def groups(self, user_id: str) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT g.id,g.name,g.kind,g.parent_id,g.created_at,COUNT(i.id) FROM organizer_groups g LEFT JOIN organizer_items i ON i.group_id=g.id AND i.deleted_at IS NULL WHERE g.user_id=%s AND g.deleted_at IS NULL GROUP BY g.id ORDER BY g.created_at", (user_id,))
                return [{"id": r[0], "name": r[1], "kind": r[2], "parent_id": r[3], "created_at": r[4].isoformat(), "count": r[5]} for r in await cur.fetchall()]

    async def archived_groups(self, user_id: str) -> list[dict]:
        """Recoverable collections in Trash, including their archived items."""
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT g.id,g.name,g.kind,g.created_at,g.deleted_at,COUNT(i.id) "
                    "FROM organizer_groups g LEFT JOIN organizer_items i ON i.group_id=g.id "
                    "WHERE g.user_id=%s AND g.deleted_at IS NOT NULL GROUP BY g.id ORDER BY g.deleted_at DESC",
                    (user_id,),
                )
                return [{"id": r[0], "name": r[1], "kind": r[2], "created_at": r[3].isoformat(), "deleted_at": r[4].isoformat(), "count": r[5]} for r in await cur.fetchall()]

    async def create_group(self, user_id: str, name: str, kind: str, parent_id: str | None = None) -> dict:
        item={"id":str(uuid.uuid4()),"name":name.strip()[:80],"kind":kind,"parent_id":parent_id,"count":0}
        async with await self._connect() as db:
            async with db.cursor() as cur:
                # Model retries and duplicate clicks must not create duplicate
                # lists.  Treat a same-name group for the same owner as one.
                await cur.execute(
                    "SELECT id,name,kind FROM organizer_groups WHERE user_id=%s AND lower(name)=lower(%s) LIMIT 1",
                    (user_id, item["name"]),
                )
                existing = await cur.fetchone()
                if existing:
                    return {"id": existing[0], "name": existing[1], "kind": existing[2], "parent_id": parent_id, "count": 0, "existing": True}
                if parent_id:
                    await cur.execute("SELECT 1 FROM organizer_groups WHERE id=%s AND user_id=%s", (parent_id, user_id))
                    if not await cur.fetchone():
                        parent_id = None
                        item["parent_id"] = None
                await cur.execute("INSERT INTO organizer_groups(id,user_id,name,kind,created_at,parent_id) VALUES(%s,%s,%s,%s,%s,%s)",(item["id"],user_id,item["name"],kind,datetime.now(UTC),parent_id))
        return item

    async def delete_group(self, user_id: str, group_id: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE organizer_groups SET deleted_at=%s WHERE id=%s AND user_id=%s AND deleted_at IS NULL", (datetime.now(UTC), group_id, user_id))
                archived = cur.rowcount > 0
                if archived:
                    await cur.execute("UPDATE organizer_items SET deleted_at=%s WHERE group_id=%s AND user_id=%s AND deleted_at IS NULL", (datetime.now(UTC), group_id, user_id))
                return archived

    async def restore_group(self, user_id: str, group_id: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE organizer_groups SET deleted_at=NULL WHERE id=%s AND user_id=%s AND deleted_at IS NOT NULL", (group_id, user_id))
                restored = cur.rowcount > 0
                if restored:
                    await cur.execute("UPDATE organizer_items SET deleted_at=NULL,updated_at=%s WHERE group_id=%s AND user_id=%s", (datetime.now(UTC), group_id, user_id))
                return restored

    async def items(self, user_id: str, group_id: str) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT id,kind,title,content,url,metadata,summary,checked,created_at,updated_at FROM organizer_items WHERE user_id=%s AND group_id=%s AND deleted_at IS NULL ORDER BY checked,created_at DESC",(user_id,group_id))
                return [{"id":r[0],"kind":r[1],"title":r[2],"content":r[3],"url":r[4],"metadata":r[5] if isinstance(r[5],dict) else json.loads(r[5]),"summary":r[6],"checked":r[7],"created_at":r[8].isoformat(),"updated_at":r[9].isoformat()} for r in await cur.fetchall()]

    async def create_item(self, user_id: str, group_id: str, kind: str, title: str, content: str = "", url: str | None = None, extra_metadata: dict | None = None) -> dict:
        item_id=str(uuid.uuid4()); now=datetime.now(UTC)
        combined = f"{title} {content}".strip()
        tags = sorted(set(re.findall(r"(?<!\w)#([\w-]{2,40})", combined.lower())))
        links = sorted(set(re.findall(r"\[\[([^\]]{1,120})\]\]", content)))
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", combined.lower())
        stop_words = {"this", "that", "with", "from", "have", "your", "about", "would", "there", "here", "into", "then", "when", "what", "just", "some", "note"}
        keywords = list(dict.fromkeys(word for word in words if word not in stop_words))[:18]
        plain = re.sub(r"\s+", " ", re.sub(r"[#*_`>\[\]]", "", content)).strip()
        summary = (plain or title.strip())[:220]
        provided_metadata = extra_metadata or {}
        references = normalize_references(provided_metadata.get("references"))
        safe_extra_metadata = {
            key: value for key, value in provided_metadata.items() if key != "references"
        }
        metadata = {"schema_version": 1, "summary": summary, "tags": tags, "keywords": keywords, "links": links, "references": references, "source": "organizer", "content_length": len(content), "has_url": bool(url), **safe_extra_metadata}
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("INSERT INTO organizer_items(id,user_id,group_id,kind,title,content,url,metadata,summary,created_at,updated_at) SELECT %s,%s,id,%s,%s,%s,%s,%s,%s,%s,%s FROM organizer_groups WHERE id=%s AND user_id=%s",(item_id,user_id,kind,title.strip()[:160],content.strip()[:12000],url,json.dumps(metadata),summary,now,now,group_id,user_id))
        return {"id":item_id,"kind":kind,"title":title,"content":content,"url":url,"metadata":metadata,"summary":summary,"checked":False}

    async def update_item(
        self,
        user_id: str,
        item_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        append_context: str | None = None,
        url: str | None = None,
        clear_url: bool = False,
        references: list[dict] | None = None,
        replace_references: bool = False,
        metadata: dict | None = None,
    ) -> dict | None:
        """Edit one existing item without replacing, archiving, or duplicating it.

        `append_context` is intentionally distinct from `content`: chat can add
        a note to an existing record without risking the current details.
        References may hold public links, images, document URLs, or local file
        paths. A local path stays a reference only; this method never reads it.
        """
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT kind,title,content,url,metadata,checked,created_at FROM organizer_items WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR UPDATE",
                    (item_id, user_id),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                kind, old_title, old_content, old_url, old_metadata, checked, created_at = row
                old_metadata = old_metadata if isinstance(old_metadata, dict) else json.loads(old_metadata)
                next_title = (title.strip()[:160] if isinstance(title, str) and title.strip() else old_title)
                next_content = content.strip()[:12000] if isinstance(content, str) else old_content
                if isinstance(append_context, str) and append_context.strip():
                    next_content = "\n\n".join(part for part in (next_content, append_context.strip()) if part)[:12000]
                next_url = None if clear_url else (url.strip() if isinstance(url, str) and url.strip() else old_url)
                combined = f"{next_title} {next_content}".strip()
                tags = sorted(set(re.findall(r"(?<!\w)#([\w-]{2,40})", combined.lower())))
                links = sorted(set(re.findall(r"\[\[([^\]]{1,120})\]\]", next_content)))
                words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", combined.lower())
                stop_words = {"this", "that", "with", "from", "have", "your", "about", "would", "there", "here", "into", "then", "when", "what", "just", "some", "note"}
                keywords = list(dict.fromkeys(word for word in words if word not in stop_words))[:18]
                plain = re.sub(r"\s+", " ", re.sub(r"[#*_`>\[\]]", "", next_content)).strip()
                summary = (plain or next_title)[:220]
                next_metadata = dict(old_metadata)
                if metadata:
                    next_metadata.update({key: value for key, value in metadata.items() if key not in {"references", "summary", "tags", "keywords", "links"}})
                if references is not None:
                    reference_values = references if replace_references else [*old_metadata.get("references", []), *references]
                    next_metadata["references"] = normalize_references(reference_values)
                next_metadata.update({"schema_version": 1, "summary": summary, "tags": tags, "keywords": keywords, "links": links, "content_length": len(next_content), "has_url": bool(next_url)})
                now = datetime.now(UTC)
                await cur.execute(
                    "UPDATE organizer_items SET title=%s,content=%s,url=%s,metadata=%s,summary=%s,updated_at=%s WHERE id=%s AND user_id=%s",
                    (next_title, next_content, next_url, json.dumps(next_metadata), summary, now, item_id, user_id),
                )
        return {"id": item_id, "kind": kind, "title": next_title, "content": next_content, "url": next_url, "metadata": next_metadata, "summary": summary, "checked": checked, "created_at": created_at.isoformat(), "updated_at": now.isoformat()}

    async def enrich_link(self, user_id: str, item_id: str) -> None:
        """Fetch a public link after save; failures remain visible as metadata."""
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT url,title,content,metadata FROM organizer_items WHERE id=%s AND user_id=%s AND deleted_at IS NULL", (item_id, user_id))
                row = await cur.fetchone()
        if not row or not row[0]:
            return
        page = await fetch_page_context(row[0])
        metadata = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        metadata["link_enrichment"] = page
        if page.get("status") == "ready":
            imported = f"\n\n--- Imported link context ---\n{page['context']}"
            content = row[2] if "--- Imported link context ---" in row[2] else (row[2] + imported).strip()
            summary = (page.get("description") or page.get("context") or row[1])[:220]
            metadata["keywords"] = list(dict.fromkeys([*metadata.get("keywords", []), *page.get("keywords", [])]))[:30]
            metadata["summary"] = summary
            metadata["enriched_at"] = datetime.now(UTC).isoformat()
        else:
            content, summary = row[2], metadata.get("summary", row[1])
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE organizer_items SET content=%s,summary=%s,metadata=%s,updated_at=%s WHERE id=%s AND user_id=%s", (content, summary, json.dumps(metadata), datetime.now(UTC), item_id, user_id))
        await self.index_item(user_id, item_id)

    async def index_item(self, user_id: str, item_id: str) -> None:
        """Lightweight chunk index now; compatible with optional vectors later."""
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT title,summary,content,metadata FROM organizer_items WHERE id=%s AND user_id=%s AND deleted_at IS NULL", (item_id, user_id))
                row = await cur.fetchone()
                if not row:
                    return
                metadata = row[3] if isinstance(row[3], dict) else json.loads(row[3])
                reference_context = "\n".join(
                    " ".join(
                        part
                        for part in (
                            reference.get("type"),
                            reference.get("label"),
                            reference.get("note"),
                        )
                        if part
                    )
                    for reference in metadata.get("references", [])
                    if isinstance(reference, dict)
                )
                text = "\n".join(part for part in (row[0], row[1], row[2], reference_context) if part).strip()
                chunks = [text[pos:pos + 1600] for pos in range(0, len(text), 1400)] or [row[0]]
                await cur.execute("DELETE FROM organizer_chunks WHERE item_id=%s", (item_id,))
                for ordinal, chunk in enumerate(chunks):
                    await cur.execute("INSERT INTO organizer_chunks(id,item_id,ordinal,content,metadata,created_at) VALUES(%s,%s,%s,%s,%s,%s)", (str(uuid.uuid4()), item_id, ordinal, chunk, json.dumps({"source": "organizer", "chunk_size": len(chunk)}), datetime.now(UTC)))

    async def embed_item(self, user_id: str, item_id: str) -> None:
        """Optional local embeddings, intentionally excluding Crypto Wallets and tasks."""
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT c.id,c.content FROM organizer_chunks c JOIN organizer_items i ON i.id=c.item_id JOIN organizer_groups g ON g.id=i.group_id WHERE i.user_id=%s AND c.item_id=%s AND i.kind!='task' AND lower(g.name) NOT LIKE '%%crypto%%'", (user_id, item_id))
                rows = await cur.fetchall()
        if not rows:
            return
        vectors = await embed([row[1] for row in rows])
        async with await self._connect() as db:
            async with db.cursor() as cur:
                for row, vector in zip(rows, vectors):
                    await cur.execute("UPDATE organizer_chunks SET embedding=%s WHERE id=%s", (json.dumps(vector), row[0]))

    async def backfill_semantic_index(self, user_id: str, limit: int = 250) -> dict:
        """Index existing Organizer content after semantic search is enabled.

        The backfill is bounded and skips task/private-wallet material.  If
        local Ollama is not available, text chunks remain indexed for FTS and
        the method exits without making normal startup fail.
        """
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT i.id FROM organizer_items i JOIN organizer_groups g ON g.id=i.group_id "
                    "WHERE i.user_id=%s AND i.deleted_at IS NULL AND g.deleted_at IS NULL "
                    "AND i.kind!='task' AND lower(g.name) NOT LIKE '%%crypto%%' AND ("
                    "NOT EXISTS (SELECT 1 FROM organizer_chunks c WHERE c.item_id=i.id) OR "
                    "EXISTS (SELECT 1 FROM organizer_chunks c WHERE c.item_id=i.id AND c.embedding IS NULL)) "
                    "ORDER BY i.updated_at DESC LIMIT %s",
                    (user_id, limit),
                )
                item_ids = [row[0] for row in await cur.fetchall()]
        indexed = 0
        embedded = 0
        for item_id in item_ids:
            await self.index_item(user_id, item_id)
            indexed += 1
            try:
                await self.embed_item(user_id, item_id)
                embedded += 1
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                # Do not retry every record when the local embedding service
                # is offline; a later startup or explicit save can retry.
                break
        return {"candidates": len(item_ids), "indexed": indexed, "embedded": embedded}

    async def search(self, user_id: str, query: str, limit: int = 12) -> list[dict]:
        """Hybrid Organizer retrieval: Postgres FTS is always available; local
        embeddings improve semantic matches when they have been indexed.

        Vectors deliberately stay optional here.  Saved material remains
        searchable on a small VPS or while Ollama is offline.
        """
        query = query.strip()[:200]
        if not query:
            return []
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute(
                    "SELECT i.id,i.kind,i.title,i.content,i.url,i.metadata,i.checked,i.created_at,i.updated_at,g.name,ts_rank(to_tsvector('simple',coalesce(i.title,'') || ' ' || coalesce(i.content,'')),websearch_to_tsquery('simple',%s)) AS score FROM organizer_items i JOIN organizer_groups g ON g.id=i.group_id WHERE i.user_id=%s AND i.deleted_at IS NULL AND g.deleted_at IS NULL AND to_tsvector('simple',coalesce(i.title,'') || ' ' || coalesce(i.content,'')) @@ websearch_to_tsquery('simple',%s) ORDER BY score DESC,i.updated_at DESC LIMIT %s",
                    (query, user_id, query, max(limit * 3, 24)),
                )
                lexical_rows = await cur.fetchall()
                await cur.execute(
                    "SELECT c.item_id,c.embedding,i.id,i.kind,i.title,i.content,i.url,i.metadata,i.checked,i.created_at,i.updated_at,g.name "
                    "FROM organizer_chunks c JOIN organizer_items i ON i.id=c.item_id "
                    "JOIN organizer_groups g ON g.id=i.group_id "
                    "WHERE i.user_id=%s AND i.deleted_at IS NULL AND g.deleted_at IS NULL "
                    "AND c.embedding IS NOT NULL LIMIT 300",
                    (user_id,),
                )
                vector_rows = await cur.fetchall()

        def as_item(row: tuple, score: float = 0.0) -> dict:
            return {
                "id": row[0], "kind": row[1], "title": row[2], "content": row[3],
                "url": row[4], "metadata": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                "checked": row[6], "created_at": row[7].isoformat(), "updated_at": row[8].isoformat(),
                "group_name": row[9], "lexical_score": score, "semantic_score": 0.0,
            }

        merged: dict[str, dict] = {}
        maximum_lexical = max((float(row[10]) for row in lexical_rows), default=0.0)
        for row in lexical_rows:
            item = as_item(row, float(row[10]) / maximum_lexical if maximum_lexical else 0.0)
            merged[item["id"]] = item

        if vector_rows:
            try:
                query_vector = (await embed([query]))[0]
            except Exception:
                query_vector = []
            if query_vector:
                query_norm = math.sqrt(sum(value * value for value in query_vector))
                for row in vector_rows:
                    raw_vector = row[1] if isinstance(row[1], list) else json.loads(row[1])
                    vector_norm = math.sqrt(sum(value * value for value in raw_vector))
                    if not query_norm or not vector_norm:
                        continue
                    semantic = sum(a * b for a, b in zip(query_vector, raw_vector, strict=False)) / (query_norm * vector_norm)
                    item_row = (row[2], *row[3:])
                    item = merged.setdefault(item_row[0], as_item(item_row))
                    item["semantic_score"] = max(item["semantic_score"], float(semantic))

        now = datetime.now(UTC)
        for item in merged.values():
            semantic = max(0.0, item["semantic_score"])
            lexical = item["lexical_score"]
            if semantic and lexical:
                base = (semantic * 0.58) + (lexical * 0.42)
            else:
                base = semantic or lexical
            age_days = max(0.0, (now - datetime.fromisoformat(item["updated_at"])).total_seconds() / 86400)
            recency = 0.85 + (0.15 * math.exp(-age_days / 120))
            item["score"] = base * recency
        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:limit]

    async def records(self, user_id: str, record_type: str, network: str | None = None) -> list[dict]:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("SELECT id,title,metadata,created_at FROM organizer_items WHERE user_id=%s AND deleted_at IS NULL AND metadata->>'record_type'=%s AND (%s::text IS NULL OR metadata->>'network'=%s) ORDER BY created_at DESC", (user_id, record_type, network, network))
                rows = await cur.fetchall()
        return [{"id":row[0], "title":row[1], "metadata":row[2] if isinstance(row[2],dict) else json.loads(row[2]), "created_at":row[3].isoformat()} for row in rows]

    async def archive_item(self, user_id: str, item_id: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE organizer_items SET deleted_at=%s WHERE id=%s AND user_id=%s AND deleted_at IS NULL", (datetime.now(UTC), item_id, user_id))
                return cur.rowcount > 0

    async def restore_item(self, user_id: str, item_id: str) -> bool:
        async with await self._connect() as db:
            async with db.cursor() as cur:
                await cur.execute("UPDATE organizer_items SET deleted_at=NULL,updated_at=%s WHERE id=%s AND user_id=%s AND deleted_at IS NOT NULL", (datetime.now(UTC), item_id, user_id))
                return cur.rowcount > 0

    async def set_checked(self, user_id: str, item_id: str, checked: bool) -> None:
        async with await self._connect() as db:
            async with db.cursor() as cur: await cur.execute("UPDATE organizer_items SET checked=%s,updated_at=%s WHERE id=%s AND user_id=%s",(checked,datetime.now(UTC),item_id,user_id))

"""Read-only memory tools exposed to the agent runtime.

The model queries durable owner data through these tools instead of guessing
from chat history or claiming it cannot access Neo's memory.
"""
from __future__ import annotations

from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext


class MemoryService:
    def __init__(self, store):
        self.store = store

    def register(self, registry) -> None:
        registry.add_profile(
            IntegrationProfile(
                "memory",
                "Neo has durable owner memory. Use memory.list_profile for questions about "
                "known facts, preferences, or instructions. Use memory.search for a topic from "
                "past conversations. Use memory.history when the owner asks when a fact was saved "
                "or changed. Profile records include source and created/updated timestamps. "
                "Never claim memory is unavailable before using the applicable "
                "read-only memory tool.",
            )
        )

        async def list_profile(data: dict, context: ToolContext) -> dict:
            requested = data.get("categories") or [
                "identity",
                "birthday",
                "preference",
                "instruction",
            ]
            allowed = {"identity", "birthday", "preference", "instruction"}
            categories = [str(item) for item in requested if str(item) in allowed]
            if not categories:
                categories = sorted(allowed)
            if hasattr(self.store, "list_records"):
                records = await self.store.list_records(
                    context.user_id, categories=categories, limit=32
                )
                return {"ok": True, "data": records}
            profile = {
                category: await self.store.list_category(context.user_id, category, limit=12)
                for category in categories
            }
            return {"ok": True, "data": profile}

        async def search(data: dict, context: ToolContext) -> dict:
            query = str(data.get("query", "")).strip()
            if not query:
                return {"ok": False, "error": "A memory search query is required."}
            return {
                "ok": True,
                "data": await self.store.recall(context.user_id, query, limit=8),
            }

        async def save(data: dict, context: ToolContext) -> dict:
            content = str(data.get("content", "")).strip()
            if not content:
                return {"ok": False, "error": "Memory content is required."}
            category = str(data.get("category", "semantic"))
            allowed = {"identity", "birthday", "preference", "instruction", "semantic"}
            if category not in allowed:
                return {"ok": False, "error": "Unsupported memory category."}
            memory_key = str(data["memory_key"]).strip() if data.get("memory_key") else None
            await self.store.remember(
                context.user_id,
                content,
                category=category,
                confidence=float(data.get("confidence", 0.9)),
                memory_key=memory_key,
                source_kind="owner_explicit",
                source_session_id=context.session_id,
            )
            return {
                "ok": True,
                "data": {
                    "content": content,
                    "category": category,
                    "memory_key": memory_key,
                },
            }

        registry.register(
            Tool(
                "memory.list_profile",
                "List durable owner facts, preferences, instructions, and their timestamps",
                "memory",
                Risk.READ,
                {
                    "type": "object",
                    "properties": {
                        "categories": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["identity", "birthday", "preference", "instruction"],
                            },
                        }
                    },
                },
                "Use when asked what Neo remembers, or about the owner's profile, "
                "preferences, communication style, name, location, or birthday. Use returned "
                "created_at and updated_at when the owner asks when a fact was learned or changed.",
                list_profile,
            )
        )
        registry.register(
            Tool(
                "memory.search",
                "Search past durable owner memories by topic",
                "memory",
                Risk.READ,
                {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                "Use for a past fact when the topic is not a simple profile field. "
                "Search before saying Neo cannot recall something.",
                search,
            )
        )
        registry.register(
            Tool(
                "memory.save",
                "Save an explicit durable owner fact, preference, or instruction",
                "memory",
                Risk.WRITE,
                {
                    "type": "object",
                    "required": ["content", "category"],
                    "properties": {
                        "content": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["identity", "birthday", "preference", "instruction", "semantic"],
                        },
                        "memory_key": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
                "Use only when the owner explicitly asks Neo to remember, save, or add a durable "
                "fact or preference. Include the fact itself in content and choose a stable memory_key "
                "when one is clear. This write requires owner approval.",
                save,
            )
        )

        async def history(data: dict, context: ToolContext) -> dict:
            if not hasattr(self.store, "list_history"):
                return {"ok": False, "error": "Memory history is unavailable for this store."}
            return {
                "ok": True,
                "data": await self.store.list_history(
                    context.user_id,
                    category=str(data["category"]) if data.get("category") else None,
                    memory_key=str(data["memory_key"]) if data.get("memory_key") else None,
                    limit=min(max(int(data.get("limit", 20)), 1), 50),
                ),
            }

        registry.register(
            Tool(
                "memory.history",
                "Show immutable audit events for durable memory writes and deletes",
                "memory",
                Risk.READ,
                {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "memory_key": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                },
                "Use when asked when Neo saved, changed, or removed a durable owner fact. "
                "Report the returned occurred_at timestamp; do not infer dates from chat text.",
                history,
            )
        )

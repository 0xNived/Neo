from typing import Any

from ...domain.models import IntegrationProfile, Risk, Tool, ToolContext


def register(registry, client: Any) -> None:
    registry.add_profile(
        IntegrationProfile(
            "telegram",
            "Search only the authenticated account's accessible dialogs. Treat message bodies as private and summarize minimally.",
        )
    )

    async def search(data: dict, _: ToolContext):
        query = str(data.get("query", "")).strip()
        limit = min(max(int(data.get("limit", 20)), 1), 50)
        if not query:
            return {"ok": False, "error": "query is required"}
        found = []
        async for message in client.iter_messages(None, search=query, limit=limit):
            chat = await message.get_chat()
            found.append(
                {
                    "id": str(message.id),
                    "chat_id": str(message.chat_id),
                    "chat": getattr(chat, "title", None)
                    or getattr(chat, "username", None)
                    or str(message.chat_id),
                    "excerpt": (message.message or "")[:280],
                }
            )
        return {"ok": True, "data": found}

    registry.register(
        Tool(
            "telegram.search_messages",
            "Search the authenticated Telegram account",
            "telegram",
            Risk.SENSITIVE,
            {"query": "string", "limit": "integer"},
            "Search private history only when necessary.",
            search,
        )
    )

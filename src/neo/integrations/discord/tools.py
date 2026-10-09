from typing import Any

from ...domain.models import IntegrationProfile, Risk, Tool, ToolContext


def register(registry, client: Any, guild_ids: list[str]) -> None:
    registry.add_profile(
        IntegrationProfile(
            "discord",
            "Discord is bot-only. Use only bot-visible, allowlisted guild channels; never claim access to user DMs.",
        )
    )

    async def search(data: dict, _: ToolContext):
        query = str(data.get("query", "")).lower()
        found = []
        limit = min(max(int(data.get("limit", 20)), 1), 50)
        for guild in client.guilds:
            if guild_ids and str(guild.id) not in guild_ids:
                continue
            for channel in guild.text_channels:
                async for message in channel.history(limit=100):
                    if query in message.content.lower():
                        found.append(
                            {
                                "id": str(message.id),
                                "channel_id": str(channel.id),
                                "author": str(message.author),
                                "excerpt": message.content[:280],
                            }
                        )
                    if len(found) >= limit:
                        return {"ok": True, "data": found}
        return {"ok": True, "data": found}

    async def send(data: dict, _: ToolContext):
        channel_id, content = data.get("channel_id"), data.get("content")
        if (
            not isinstance(channel_id, str)
            or not isinstance(content, str)
            or not content.strip()
        ):
            return {"ok": False, "error": "channel_id and content are required"}
        channel = client.get_channel(int(channel_id)) or await client.fetch_channel(
            int(channel_id)
        )
        message = await channel.send(content[:2000])
        return {"ok": True, "data": {"id": str(message.id), "channel_id": channel_id}}

    registry.register(
        Tool(
            "discord.search_messages",
            "Search messages accessible to Neo's official Discord bot",
            "discord",
            Risk.READ,
            {"query": "string", "limit": "integer"},
            "Use for finding actionable server messages.",
            search,
        )
    )
    registry.register(
        Tool(
            "discord.send_message",
            "Send via Neo's official Discord bot",
            "discord",
            Risk.WRITE,
            {"channel_id": "string", "content": "string"},
            "Present recipient and exact text for approval before sending.",
            send,
        )
    )

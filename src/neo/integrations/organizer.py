from __future__ import annotations

from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext


def register(registry, store) -> None:
    registry.add_profile(IntegrationProfile("organizer", "The Organizer stores the owner's notes, bookmarks, shopping items, and to-dos. Use it when the owner asks to save, list, or manage those items."))

    async def create_group(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.create_group(context.user_id, str(data["name"]), str(data.get("kind", "custom")), data.get("parent_id"))}

    async def save_item(data: dict, context: ToolContext) -> dict:
        item = await store.create_item(context.user_id, str(data["group_id"]), str(data.get("kind", "note")), str(data["title"]), str(data.get("content", "")), data.get("url"))
        return {"ok": True, "data": item}

    async def list_items(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.items(context.user_id, str(data["group_id"]))}

    async def list_groups(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.groups(context.user_id)}

    async def search(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.search(context.user_id, str(data["query"]))}

    async def records(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.records(context.user_id, str(data["record_type"]), data.get("network"))}

    async def archive_item(data: dict, context: ToolContext) -> dict:
        return {"ok": await store.archive_item(context.user_id, str(data["item_id"]))}

    async def archive_group(data: dict, context: ToolContext) -> dict:
        return {"ok": await store.delete_group(context.user_id, str(data["group_id"]))}

    async def restore_item(data: dict, context: ToolContext) -> dict:
        return {"ok": await store.restore_item(context.user_id, str(data["item_id"]))}

    registry.register(Tool("organizer.create_group", "Create a named organizer collection or nested folder", "organizer", Risk.WRITE, {"type":"object","required":["name"],"properties":{"name":{"type":"string"},"kind":{"type":"string"},"parent_id":{"type":"string","description":"Optional parent collection id for a nested folder."}}}, "Use when the owner asks for a new notes, shopping, to-do, or bookmark group. Use parent_id when they clearly ask for a folder inside an existing collection.", create_group))
    registry.register(Tool("organizer.save_item", "Save a note, bookmark, task, or shopping item in an organizer group", "organizer", Risk.WRITE, {"type":"object","required":["group_id","title"],"properties":{"group_id":{"type":"string"},"kind":{"type":"string"},"title":{"type":"string"},"content":{"type":"string"},"url":{"type":"string"}}}, "Use when the owner asks to save something; ask which group only if none is clear.", save_item))
    registry.register(Tool("organizer.list_items", "List items saved in an organizer group", "organizer", Risk.READ, {"type":"object","required":["group_id"],"properties":{"group_id":{"type":"string"}}}, "Use when the owner asks what is in a saved group.", list_items))
    registry.register(Tool("organizer.list_groups", "List the owner's Organizer collections with IDs and item counts", "organizer", Risk.READ, {"type":"object","properties":{}}, "Use this first when the owner refers to a group by name or asks what collections, lists, notes, or tasks they have. Then use organizer.list_items with the matching group ID.", list_groups))
    registry.register(Tool("organizer.search", "Search notes, tasks, saved links, and their keywords across Organizer", "organizer", Risk.READ, {"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}, "Use for questions about previously saved information. Search first instead of saying you cannot find or access a note. Results include collection name, tags, and Obsidian-style [[note links]].", search))
    registry.register(Tool("organizer.list_records", "Query typed private records and return only metadata/count, never private values", "organizer", Risk.READ, {"type":"object","required":["record_type"],"properties":{"record_type":{"type":"string","enum":["wallet_address"]},"network":{"type":"string"}}}, "For questions about how many saved wallet addresses exist, always use this tool. It returns record metadata only; report the count and do not expose a private value unless the owner explicitly asks to show one.", records))
    registry.register(Tool("organizer.archive_group", "Move one exact Organizer collection and its items to recoverable Trash", "organizer", Risk.WRITE, {"type":"object","required":["group_id"],"properties":{"group_id":{"type":"string"}}}, "When the owner asks to delete/archive/remove a collection or list: first use organizer.list_groups, match the requested name, then use this tool. This requires approval and is recoverable; never use it to merely mark a task complete.", archive_group))
    registry.register(Tool("organizer.archive_item", "Move one exact Organizer item to recoverable Trash", "organizer", Risk.WRITE, {"type":"object","required":["item_id"],"properties":{"item_id":{"type":"string"}}}, "Use only after identifying the exact item to the owner. This moves it to Trash and requires approval; it is not a permanent delete.", archive_item))
    registry.register(Tool("organizer.restore_item", "Restore one exact Organizer item from Trash", "organizer", Risk.WRITE, {"type":"object","required":["item_id"],"properties":{"item_id":{"type":"string"}}}, "Use when the owner asks to restore a trashed item. Requires approval.", restore_item))

from __future__ import annotations

import asyncio

from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext


def register(registry, store) -> None:
    registry.add_profile(IntegrationProfile("organizer", "The Organizer stores the owner's notes, bookmarks, shopping items, and to-dos. Use it when the owner asks to save, list, or manage those items. Existing items are editable in place: resolve the exact item first, then use organizer.update_item for title, context, links, attachments, and metadata; never archive/recreate merely to edit."))

    async def create_group(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.create_group(context.user_id, str(data["name"]), str(data.get("kind", "custom")), data.get("parent_id"))}

    async def save_item(data: dict, context: ToolContext) -> dict:
        item = await store.create_item(context.user_id, str(data["group_id"]), str(data.get("kind", "note")), str(data["title"]), str(data.get("content", "")), data.get("url"), {"references": data.get("references")})
        await store.index_item(context.user_id, item["id"])

        async def index_semantics() -> None:
            try:
                await store.embed_item(context.user_id, item["id"])
            except Exception:
                # FTS/chunks are already available; local vector indexing is
                # an optional enhancement and must never fail the save.
                return

        asyncio.create_task(index_semantics())
        if item.get("url"):
            asyncio.create_task(store.enrich_link(context.user_id, item["id"]))
        return {"ok": True, "data": item}

    async def list_items(data: dict, context: ToolContext) -> dict:
        return {"ok": True, "data": await store.items(context.user_id, str(data["group_id"]))}

    async def update_item(data: dict, context: ToolContext) -> dict:
        item_id = str(data["item_id"])
        item = await store.update_item(
            context.user_id,
            item_id,
            title=data.get("title"),
            content=data.get("content"),
            append_context=data.get("append_context"),
            url=data.get("url"),
            clear_url=bool(data.get("clear_url", False)),
            references=data.get("references"),
            replace_references=bool(data.get("replace_references", False)),
            metadata=data.get("metadata"),
        )
        if not item:
            return {"ok": False, "error": "Organizer item was not found or is in Trash."}
        await store.index_item(context.user_id, item_id)

        async def index_semantics() -> None:
            try:
                await store.embed_item(context.user_id, item_id)
            except Exception:  # noqa: BLE001
                return

        asyncio.create_task(index_semantics())
        if data.get("url"):
            asyncio.create_task(store.enrich_link(context.user_id, item_id))
        return {"ok": True, "data": item}

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

    async def set_checked(data: dict, context: ToolContext) -> dict:
        item_id = str(data["item_id"])
        checked = bool(data["checked"])
        await store.set_checked(context.user_id, item_id, checked)
        return {"ok": True, "data": {"item_id": item_id, "checked": checked}}

    registry.register(Tool("organizer.create_group", "Create a named organizer collection or nested folder", "organizer", Risk.WRITE, {"type":"object","required":["name"],"properties":{"name":{"type":"string"},"kind":{"type":"string"},"parent_id":{"type":"string","description":"Optional parent collection id for a nested folder."}}}, "Use when the owner asks for a new notes, shopping, to-do, or bookmark group. Use parent_id when they clearly ask for a folder inside an existing collection.", create_group))
    registry.register(Tool("organizer.save_item", "Save a note, bookmark, task, or shopping item in an organizer group", "organizer", Risk.WRITE, {"type":"object","required":["group_id","title"],"properties":{"group_id":{"type":"string"},"kind":{"type":"string"},"title":{"type":"string"},"content":{"type":"string"},"url":{"type":"string"},"references":{"type":"array","items":{"type":"object","required":["type","value"],"properties":{"type":{"type":"string","enum":["web_link","image","document","local_path"]},"value":{"type":"string"},"label":{"type":"string"},"note":{"type":"string"}}}}}}, "Use when the owner asks to save something; ask which group only if none is clear. Save links, image/document URLs, and absolute local paths as references with optional context. Storing a path is only a reference; it does not grant permission to read the file.", save_item))
    registry.register(Tool("organizer.update_item", "Update the title, context, link, attachments, or metadata of one existing Organizer item", "organizer", Risk.WRITE, {"type":"object","required":["item_id"],"properties":{"item_id":{"type":"string"},"title":{"type":"string"},"content":{"type":"string","description":"Replace the full saved content only when the owner asks to replace it."},"append_context":{"type":"string","description":"Append context/details while preserving existing content."},"url":{"type":"string"},"clear_url":{"type":"boolean"},"metadata":{"type":"object"},"replace_references":{"type":"boolean"},"references":{"type":"array","items":{"type":"object","required":["type","value"],"properties":{"type":{"type":"string","enum":["web_link","image","document","local_path"]},"value":{"type":"string"},"label":{"type":"string"},"note":{"type":"string"}}}}}}, "Use when the owner asks to rename, edit, add context to, attach a link/image/document/path to, or otherwise update a saved item. First use organizer.search or organizer.list_items to resolve exactly one item ID. Use replace_references only when the owner asks to replace/remove the whole attachment list. Do not archive and recreate an item to edit it. This local write requires approval. A local path is stored only as a reference and does not grant file access.", update_item))
    registry.register(Tool("organizer.list_items", "List items saved in an organizer group", "organizer", Risk.READ, {"type":"object","required":["group_id"],"properties":{"group_id":{"type":"string"}}}, "Use when the owner asks what is in a saved group.", list_items))
    registry.register(Tool("organizer.list_groups", "List the owner's Organizer collections with IDs and item counts", "organizer", Risk.READ, {"type":"object","properties":{}}, "Use this first when the owner refers to a group by name or asks what collections, lists, notes, or tasks they have. Then use organizer.list_items with the matching group ID.", list_groups))
    registry.register(Tool("organizer.search", "Search notes, tasks, saved links, and their keywords across Organizer", "organizer", Risk.READ, {"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}, "Use for questions about previously saved information. Search first instead of saying you cannot find or access a note. Results include collection name, tags, and Obsidian-style [[note links]].", search))
    registry.register(Tool("organizer.list_records", "Query typed private records and return only metadata/count, never private values", "organizer", Risk.READ, {"type":"object","required":["record_type"],"properties":{"record_type":{"type":"string","enum":["wallet_address"]},"network":{"type":"string"}}}, "For questions about how many saved wallet addresses exist, always use this tool. It returns record metadata only; report the count and do not expose a private value unless the owner explicitly asks to show one.", records))
    registry.register(Tool("organizer.archive_group", "Move one exact Organizer collection and its items to recoverable Trash", "organizer", Risk.WRITE, {"type":"object","required":["group_id"],"properties":{"group_id":{"type":"string"}}}, "When the owner asks to delete/archive/remove a collection or list: first use organizer.list_groups, match the requested name, then use this tool. This requires approval and is recoverable; never use it to merely mark a task complete.", archive_group))
    registry.register(Tool("organizer.archive_item", "Move one exact Organizer item to recoverable Trash", "organizer", Risk.WRITE, {"type":"object","required":["item_id"],"properties":{"item_id":{"type":"string"}}}, "Use only after identifying the exact item to the owner. This moves it to Trash and requires approval; it is not a permanent delete.", archive_item))
    registry.register(Tool("organizer.restore_item", "Restore one exact Organizer item from Trash", "organizer", Risk.WRITE, {"type":"object","required":["item_id"],"properties":{"item_id":{"type":"string"}}}, "Use when the owner asks to restore a trashed item. Requires approval.", restore_item))
    registry.register(Tool("organizer.set_checked", "Mark one Organizer task done or not done", "organizer", Risk.WRITE, {"type":"object","required":["item_id","checked"],"properties":{"item_id":{"type":"string"},"checked":{"type":"boolean"}}}, "Use after organizer.list_items identifies the exact task. This is a reversible local checkbox toggle, so do it directly when the owner clearly asks to mark a task done, reopen it, or uncheck it.", set_checked))

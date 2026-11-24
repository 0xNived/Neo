import pytest

from neo.domain.models import Risk, ToolContext
from neo.integrations.organizer import register
from neo.tools.registry import ToolRegistry


class Store:
    def __init__(self):
        self.updated = None
        self.indexed = []

    async def update_item(self, user_id, item_id, **changes):
        self.updated = (user_id, item_id, changes)
        return {"id": item_id, "title": "SendNOW Ltc", "url": changes["url"]}

    async def index_item(self, _user_id, item_id):
        self.indexed.append(item_id)

    async def embed_item(self, _user_id, _item_id):
        return None

    async def enrich_link(self, _user_id, _item_id):
        return None


@pytest.mark.asyncio
async def test_update_item_supports_context_and_references_without_recreation():
    store = Store()
    registry = ToolRegistry()
    register(registry, store)

    tool = registry.tools["organizer.update_item"]
    result = await tool.execute(
        {
            "item_id": "item-1",
            "title": "SendNOW Ltc",
            "append_context": "Travel wallet; keep it private.",
            "url": "https://example.com/wallet-info",
            "references": [
                {"type": "image", "value": "https://example.com/qr.png", "label": "QR"}
            ],
        },
        ToolContext("nico", "session", "request"),
    )

    assert tool.risk == Risk.WRITE
    assert result["ok"] is True
    assert store.updated == (
        "nico",
        "item-1",
        {
            "title": "SendNOW Ltc",
            "content": None,
            "append_context": "Travel wallet; keep it private.",
            "url": "https://example.com/wallet-info",
            "clear_url": False,
            "references": [
                {"type": "image", "value": "https://example.com/qr.png", "label": "QR"}
            ],
            "replace_references": False,
            "metadata": None,
        },
    )
    assert store.indexed == ["item-1"]

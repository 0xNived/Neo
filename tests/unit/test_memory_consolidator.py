import pytest

from neo.memory.consolidator import MemoryConsolidator
from neo.memory.llm_extractor import MemoryCandidate
from neo.memory.sqlite_store import SqliteMemoryStore


class Extractor:
    async def extract(self, _message, _context_messages):
        return [MemoryCandidate("identity", "github_profile", "https://github.com/0xNived", 0.94)]


@pytest.mark.asyncio
async def test_consolidator_promotes_a_captured_candidate(tmp_path):
    store = SqliteMemoryStore(tmp_path / "neo.sqlite3", ttl_days=30)
    await store.initialize()
    await store.capture_candidate("nico", "That is my GitHub profile", source_session_id="web-1")

    result = await MemoryConsolidator(store, Extractor()).run_once("nico")

    assert result == {"inspected": 1, "promoted": 1}
    assert await store.list_candidates("nico") == []
    assert await store.list_category("nico", "identity") == [
        "The owner's github profile is https://github.com/0xNived."
    ]


@pytest.mark.asyncio
async def test_consolidator_reuses_captured_conversation_context(tmp_path):
    class ContextExtractor:
        async def extract(self, message, context_messages):
            assert message == "The first one is correct."
            assert context_messages[-1]["content"] == "Skrillex, Virtual Riot, or RIOT?"
            return [MemoryCandidate("preference", "music_artist_preference", "Skrillex", 0.95)]

    store = SqliteMemoryStore(tmp_path / "neo.sqlite3", ttl_days=30)
    await store.initialize()
    await store.capture_candidate(
        "nico",
        "The first one is correct.",
        source_session_id="web-1",
        context_messages=[{"role": "assistant", "content": "Skrillex, Virtual Riot, or RIOT?"}],
    )

    result = await MemoryConsolidator(store, ContextExtractor()).run_once("nico")

    assert result == {"inspected": 1, "promoted": 1}
    assert await store.list_category("nico", "preference") == [
        "The owner's music artist preference is Skrillex."
    ]

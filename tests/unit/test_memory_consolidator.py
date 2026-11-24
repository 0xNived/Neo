import pytest

from neo.memory.consolidator import MemoryConsolidator
from neo.memory.llm_extractor import MemoryCandidate
from neo.memory.sqlite_store import SqliteMemoryStore


class Extractor:
    async def extract(self, _message):
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

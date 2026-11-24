import pytest

from neo.domain.models import Risk, ToolContext
from neo.memory.service import MemoryService
from neo.memory.sqlite_store import SqliteMemoryStore
from neo.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_memory_service_exposes_read_only_profile_and_search_tools(tmp_path):
    store = SqliteMemoryStore(tmp_path / "neo.sqlite3", ttl_days=30)
    await store.initialize()
    await store.remember(
        "nico",
        "The owner's location is Nagpur, India.",
        "identity",
        memory_key="location",
        source_session_id="web-1",
    )
    registry = ToolRegistry()
    MemoryService(store).register(registry)
    context = ToolContext("nico", "web-1", "request")

    profile = await registry.tools["memory.list_profile"].execute({}, context)
    search = await registry.tools["memory.search"].execute({"query": "location"}, context)

    assert registry.tools["memory.list_profile"].risk == Risk.READ
    assert profile["ok"] is True
    assert profile["data"][0]["memory_key"] == "location"
    assert profile["data"][0]["source_session_id"] == "web-1"
    assert profile["data"][0]["created_at"]
    assert profile["data"][0]["updated_at"]
    assert search["data"] == ["The owner's location is Nagpur, India."]

    history = await registry.tools["memory.history"].execute(
        {"memory_key": "location"}, context
    )
    assert history["ok"] is True
    assert history["data"][0]["action"] == "created"
    assert history["data"][0]["occurred_at"]

    saved = await registry.tools["memory.save"].execute(
        {
            "content": "The owner does not want direct movie or TV spoilers.",
            "category": "preference",
            "memory_key": "spoiler_preference",
        },
        context,
    )
    assert registry.tools["memory.save"].risk == Risk.WRITE
    assert saved["ok"] is True
    assert "spoilers" in (await store.list_category("nico", "preference"))[0]


@pytest.mark.asyncio
async def test_memory_candidates_are_persisted_separately_from_profile_facts(tmp_path):
    store = SqliteMemoryStore(tmp_path / "neo.sqlite3", ttl_days=30)
    await store.initialize()

    candidate_id = await store.capture_candidate(
        "nico",
        "That is my GitHub profile: https://github.com/0xNived",
        source_session_id="web-1",
        kind="explicit_owner_fact",
        extracted=[],
        reason="llm_memory_extraction",
    )

    captured = await store.list_candidates("nico")
    assert captured[0]["id"] == candidate_id
    assert captured[0]["status"] == "captured"
    assert await store.list_category("nico", "identity") == []

    await store.remember(
        "nico",
        "The owner's GitHub profile is https://github.com/0xNived.",
        "identity",
        memory_key="github_profile",
        source_session_id="web-1",
    )
    await store.mark_candidate_promoted(candidate_id)
    assert await store.list_candidates("nico") == []

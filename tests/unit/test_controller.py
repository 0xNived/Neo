import pytest

from neo.brain.stub import StubBrain
from neo.controller.agent_controller import AgentController
from neo.memory.in_memory import InMemorySessionStore
from neo.memory.llm_extractor import LlmMemoryExtractor, MemoryCandidate
from neo.memory.sqlite_store import SqliteMemoryStore
from neo.tools.registry import ToolRegistry


class ErrorBrain:
    async def complete(self, _messages, _tools, _profiles):
        return {
            "kind": "message",
            "content": "Provider failed. Open technical details below.",
            "diagnostic": {"status": 503, "request_id": "provider-request"},
        }


@pytest.mark.asyncio
async def test_stub_response_is_saved():
    controller = AgentController(
        StubBrain(), InMemorySessionStore(), ToolRegistry(), False, 8
    )
    assert "Neo is wired" in await controller.handle_text("s", "u", "hello")


@pytest.mark.asyncio
async def test_provider_diagnostic_is_saved_with_assistant_message():
    sessions = InMemorySessionStore()
    controller = AgentController(ErrorBrain(), sessions, ToolRegistry(), False, 8)

    response = await controller.handle_text("error-session", "u", "hello")
    session = await sessions.get_or_create("error-session", "u")

    assert response.startswith("Provider failed")
    assert session.messages[-1]["diagnostic"]["status"] == 503


@pytest.mark.asyncio
async def test_owner_confirmation_uses_previous_artist_suggestions(tmp_path):
    class ArtistBrain:
        async def complete(self, *_):
            return {"kind": "message", "content": "My guesses are Skrillex, Virtual Riot, and RIOT."}

    class ArtistExtractor:
        likely_durable = staticmethod(LlmMemoryExtractor.likely_durable)

        async def extract(self, text, context_messages):
            if text == "The first one is correct, Skrillex it is.":
                assert context_messages[-1] == {
                    "role": "assistant",
                    "content": "My guesses are Skrillex, Virtual Riot, and RIOT.",
                }
                return [MemoryCandidate("preference", "music_artist_preference", "Skrillex", 0.94)]
            return []

    memory = SqliteMemoryStore(tmp_path / "neo.sqlite3", ttl_days=30)
    await memory.initialize()
    controller = AgentController(
        ArtistBrain(), InMemorySessionStore(), ToolRegistry(), False, 8,
        memory=memory, memory_extractor=ArtistExtractor(),
    )

    await controller.handle_text("s", "u", "Can you guess the kind of music I like?")
    assert await memory.list_category("u", "preference") == []
    assert len(await memory.list_candidates("u", status="dismissed")) == 1
    await controller.handle_text("s", "u", "The first one is correct, Skrillex it is.")

    assert await memory.list_category("u", "preference") == [
        "The owner's music artist preference is Skrillex."
    ]

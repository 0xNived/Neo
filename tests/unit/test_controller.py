import pytest

from neo.brain.stub import StubBrain
from neo.controller.agent_controller import AgentController
from neo.memory.in_memory import InMemorySessionStore
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

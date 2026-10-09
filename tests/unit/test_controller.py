import pytest

from neo.brain.stub import StubBrain
from neo.controller.agent_controller import AgentController
from neo.memory.in_memory import InMemorySessionStore
from neo.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_stub_response_is_saved():
    controller = AgentController(
        StubBrain(), InMemorySessionStore(), ToolRegistry(), False, 8
    )
    assert "Neo is wired" in await controller.handle_text("s", "u", "hello")

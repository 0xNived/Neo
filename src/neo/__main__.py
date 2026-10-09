import asyncio

from .brain.stub import StubBrain
from .configuration.settings import load_settings
from .controller.agent_controller import AgentController
from .memory.in_memory import InMemorySessionStore
from .tools.registry import ToolRegistry


async def run():
    settings = load_settings()
    controller = AgentController(
        StubBrain(),
        InMemorySessionStore(),
        ToolRegistry(),
        settings.allow_external_writes,
        settings.max_tool_rounds,
    )
    print(await controller.handle_text("local-session", "local-user", "Hello, Neo"))


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()

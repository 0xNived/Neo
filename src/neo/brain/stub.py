class StubBrain:
    async def complete(self, *_):
        return {
            "kind": "message",
            "content": "Neo is wired correctly. Configure an LLM provider to enable planning and tool calls.",
        }

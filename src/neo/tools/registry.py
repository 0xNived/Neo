from ..domain.models import IntegrationProfile, Tool


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.profiles: dict[str, IntegrationProfile] = {}

    def add_profile(self, profile: IntegrationProfile) -> None:
        self.profiles[profile.name] = profile

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        self.tools[tool.name] = tool

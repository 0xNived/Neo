from typing import Any, Protocol

from ...domain.models import IntegrationProfile, Risk, Tool, ToolContext


class McpClient(Protocol):
    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


async def register_mcp_server(
    registry, server_name: str, client: McpClient, risks: dict[str, Risk] | None = None
) -> None:
    registry.add_profile(
        IntegrationProfile(
            server_name,
            f"MCP server {server_name}: unknown tools are sensitive and need approval.",
        )
    )
    for item in await client.list_tools():
        raw = str(item["name"])

        async def execute(data: dict[str, Any], _: ToolContext, name: str = raw):
            return {"ok": True, "data": await client.call_tool(name, data)}

        registry.register(
            Tool(
                f"{server_name}.{raw}",
                str(item.get("description", "MCP tool")),
                server_name,
                (risks or {}).get(raw, Risk.SENSITIVE),
                item.get("inputSchema", {}),
                "Obey this integration's profile.",
                execute,
            )
        )

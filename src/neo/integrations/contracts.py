"""Shared contracts for built-in, OAuth, webhook, and MCP integrations.

The tool registry is transport-agnostic. An integration can be a native
adapter, OAuth-backed service, webhook, or MCP server; after registration the
agent sees the same narrow tool contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class IntegrationTransport(StrEnum):
    NATIVE = "native"
    OAUTH = "oauth"
    WEBHOOK = "webhook"
    MCP = "mcp"


class ConnectionState(StrEnum):
    READY = "ready"
    NEEDS_CONFIGURATION = "needs_configuration"
    DISABLED = "disabled"


@dataclass(frozen=True)
class IntegrationStatus:
    """Secret-free status suitable for the API and future settings UI."""

    id: str
    name: str
    transport: IntegrationTransport
    state: ConnectionState
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""

    def public(self) -> dict[str, object]:
        return asdict(self)

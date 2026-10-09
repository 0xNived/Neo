from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Risk(StrEnum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolContext:
    user_id: str
    session_id: str
    request_id: str


@dataclass(frozen=True)
class IntegrationProfile:
    name: str
    llm_guidance: str


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    integration: str
    risk: Risk
    schema: dict[str, Any]
    guidance: str
    execute: Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]


@dataclass
class Session:
    id: str
    user_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    references: dict[str, dict[str, str]] = field(default_factory=dict)

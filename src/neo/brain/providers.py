from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from ..domain.models import IntegrationProfile, Tool
from ..persona.profile import Persona
from .prompt_builder import PromptBuilder
from .response_validator import validate_reply
from .stub import StubBrain


def parse_model_reply(content: object, tool_names: set[str]) -> dict[str, Any]:
    """Free/remote models occasionally ignore JSON mode; never turn that into a 500."""
    if isinstance(content, dict):
        return validate_reply(content, tool_names)
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].removesuffix("```").strip()
    try:
        return validate_reply(json.loads(text), tool_names)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return validate_reply(json.loads(text[start : end + 1]), tool_names)
            except json.JSONDecodeError:
                pass
        return validate_reply(
            {
                "kind": "message",
                "content": text or "Neo received an empty response. Please try again.",
            },
            tool_names,
        )


def provider_error_reply(error: httpx.HTTPError) -> dict[str, Any]:
    """External model failures must never take down the local chat gateway."""
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
        return {
            "kind": "message",
            "content": "The configured model is rate-limited right now. Try again in a moment, or switch Neo to another provider/model.",
        }
    if isinstance(error, httpx.HTTPStatusError):
        return {
            "kind": "message",
            "content": "Neo's configured model provider is temporarily unavailable. Please try again shortly.",
        }
    return {
        "kind": "message",
        "content": "Neo couldn't reach the configured model provider. Check the provider connection and try again.",
    }


def provider_messages(
    messages: list[dict[str, Any]],
    *,
    native_tool_calls: bool = False,
) -> list[dict[str, Any]]:
    """Convert Neo's durable session format into valid provider chat messages."""
    normalized: list[dict[str, Any]] = []
    # Some sessions created before tool_call_id was persisted contain an
    # incomplete assistant/tool pair.  Do not replay those as native calls:
    # providers reject the whole request when a tool result is unpaired.
    persisted_tool_call_ids = {
        str(message["tool_call_id"])
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        if role == "tool":
            name = message.get("name", "tool")
            if native_tool_calls and message.get("tool_call_id"):
                body = (
                    content
                    if isinstance(content, str)
                    else json.dumps(content, ensure_ascii=False)
                )
                tool_message: dict[str, Any] = {
                    "role": "tool",
                    "name": native_tool_name(name),
                    "content": body,
                }
                # OpenAI-compatible APIs require a tool response to be tied to
                # the assistant tool call that immediately preceded it.  Older
                # Neo sessions did not persist this field, so keep the fallback
                # path below for those records instead of sending invalid JSON.
                tool_call_id = message.get("tool_call_id")
                tool_message["tool_call_id"] = str(tool_call_id)
                normalized.append(tool_message)
                continue
            ok = True
            if isinstance(content, dict):
                ok = bool(content.get("ok", True))
            body = json.dumps(content, ensure_ascii=False)
            normalized.append(
                {
                    "role": "system",
                    "content": (
                        f"TOOL RESULT from {name} (already executed; do not ask to run it again). "
                        f"ok={ok}. Result: {body}\n"
                        "Use this result now to answer the user."
                    ),
                }
            )
            continue

        if role == "assistant" and message.get("tool_calls") and native_tool_calls:
            raw_calls = message["tool_calls"]
            if not all(call.get("id") in persisted_tool_call_ids for call in raw_calls):
                # The corresponding outcome is still retained below as a
                # system result, which preserves conversational context.
                continue
            calls = []
            for call in raw_calls:
                function = call.get("function") or {}
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments) if arguments else {}
                    except json.JSONDecodeError:
                        arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                calls.append(
                    {
                        "id": call.get("id") or f"call_{len(calls)}",
                        "type": "function",
                        "function": {
                            "name": native_tool_name(str(function.get("name", ""))),
                            # This is a JSON *string* in the OpenAI tool-call
                            # protocol, not an object.
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                )
            normalized.append(
                {
                    "role": "assistant",
                    "content": content if isinstance(content, str) else "",
                    "tool_calls": calls,
                }
            )
            continue

        if role == "assistant" and message.get("tool_calls") and not native_tool_calls:
            continue

        if (
            role == "assistant"
            and isinstance(content, str)
            and content.startswith("(calling ")
            and content.endswith(")")
        ):
            continue

        normalized.append(
            {
                "role": role if role in {"system", "user", "assistant"} else "user",
                "content": content if isinstance(content, str) else json.dumps(content),
            }
        )
    return normalized


def native_tool_name(name: str) -> str:
    """Provider function names cannot contain dots; Neo's registry names can."""
    return name.replace(".", "_")


def native_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": native_tool_name(tool.name),
                "description": tool.description,
                "parameters": tool.schema,
            },
        }
        for tool in tools
    ]


def parse_openai_reply(message: dict[str, Any], tools: list[Tool]) -> dict[str, Any]:
    names = {tool.name for tool in tools}
    native_names = {native_tool_name(name): name for name in names}
    calls = message.get("tool_calls") or []
    if calls:
        function = calls[0].get("function", {})
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}
        name = native_names.get(function.get("name"))
        if name:
            return validate_reply(
                {"kind": "tool_call", "name": name, "input": arguments}, names
            )
    return parse_model_reply(message.get("content"), names)


def compose_system_messages(
    messages: list[dict[str, Any]],
    base_system: str,
    *,
    native_tool_calls: bool = False,
) -> list[dict[str, Any]]:
    """Controller system notes must lead so they override identity."""
    leading_system = [
        message
        for message in messages
        if message.get("role") == "system" and str(message.get("content", "")).strip()
    ]
    rest = [message for message in messages if message.get("role") != "system"]
    merged = base_system
    if leading_system:
        parts = [
            str(leading_system[0]["content"]),
            base_system,
            *[
                str(message["content"])
                for message in leading_system[1:]
                if str(message.get("content", "")).strip()
            ],
        ]
        merged = "\n\n".join(parts)
    return [
        {"role": "system", "content": merged},
        *provider_messages(rest, native_tool_calls=native_tool_calls),
    ]


def parse_ollama_reply(message: dict[str, Any], tools: list[Tool]) -> dict[str, Any]:
    names = {tool.name for tool in tools}
    calls = message.get("tool_calls") or []
    if calls:
        function = calls[0].get("function", {})
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        name = function.get("name") or calls[0].get("name")
        normalized = next(
            (
                tool_name
                for tool_name in names
                if tool_name == name
                or tool_name.replace(".", "_") == name
                or tool_name.replace(".", "_") == str(name or "")
            ),
            None,
        )
        if normalized:
            return validate_reply(
                {"kind": "tool_call", "name": normalized, "input": arguments},
                names,
            )
    return parse_model_reply(message.get("content"), names)


class OllamaBrain:
    def __init__(self, base_url: str, model: str, prompts: PromptBuilder):
        self.base_url, self.model, self.prompts = base_url.rstrip("/"), model, prompts

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[Tool],
        profiles: list[IntegrationProfile],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": compose_system_messages(
                messages,
                self.prompts.build(tools, profiles, native_tools=bool(tools)),
                native_tool_calls=bool(tools),
            ),
        }
        if tools:
            payload["tools"] = native_tools(tools)
        else:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as error:
            return provider_error_reply(error)
        return parse_ollama_reply(response.json().get("message") or {}, tools)


class OpenAICompatibleBrain:
    def __init__(self, base_url: str, api_key: str, model: str, prompts: PromptBuilder):
        self.base_url, self.api_key, self.model, self.prompts = (
            base_url.rstrip("/"),
            api_key,
            model,
            prompts,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[Tool],
        profiles: list[IntegrationProfile],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": compose_system_messages(
                messages,
                self.prompts.build(tools, profiles, native_tools=True),
                native_tool_calls=True,
            ),
        }
        if tools:
            payload["tools"] = native_tools(tools)
            payload["tool_choice"] = "auto"
        # Do not force JSON mode here.  Several OpenAI-compatible providers
        # (including the configured Groq model) reject it, while our tolerant
        # reply parser already handles normal text safely.
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                if response.status_code == 429:
                    await asyncio.sleep(1)
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                response.raise_for_status()
        except httpx.HTTPError as error:
            return provider_error_reply(error)
        return parse_openai_reply(response.json()["choices"][0]["message"], tools)


def build_brain(settings, provider: str | None = None, model: str | None = None):
    prompts = PromptBuilder(settings.owner_name, settings.owner_timezone, Persona())
    provider = provider or settings.llm_provider
    model = model or settings.llm_model
    if provider == "ollama" and not model:
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    api_key = (
        settings.llm_api_key
        if provider == settings.llm_provider
        else os.getenv(f"{provider.upper()}_API_KEY", "")
    )
    base_url = settings.llm_base_url
    if provider == "ollama":
        if settings.llm_provider != "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return OllamaBrain(
            base_url or "http://localhost:11434",
            model,
            prompts,
        )
    if provider == "groq":
        return OpenAICompatibleBrain(
            "https://api.groq.com/openai/v1",
            api_key or "",
            model,
            prompts,
        )
    if provider == "cerebras":
        return OpenAICompatibleBrain(
            "https://api.cerebras.ai/v1",
            api_key or "",
            model,
            prompts,
        )
    if provider == "openrouter":
        return OpenAICompatibleBrain(
            "https://openrouter.ai/api/v1",
            api_key or "",
            model,
            prompts,
        )
    if (
        provider == "openai_compatible"
        and settings.llm_base_url
        and settings.llm_api_key
    ):
        return OpenAICompatibleBrain(settings.llm_base_url, api_key, model, prompts)
    return StubBrain()

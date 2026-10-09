from __future__ import annotations

import json
from typing import Any


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _normalize_tool_name(name: Any, tool_names: set[str]) -> str | None:
    raw = str(name or "").strip()
    if not raw:
        return None
    if raw in tool_names:
        return raw
    lowered = raw.lower()
    candidates = {
        lowered,
        lowered.replace("_", "."),
        lowered.replace("-", "."),
        lowered.replace(" ", "."),
    }
    for tool in tool_names:
        if tool.lower() in candidates or tool.lower().replace(".", "_") == lowered:
            return tool
    return None


def _tool_input(reply: dict[str, Any]) -> dict[str, Any]:
    for key in ("input", "arguments", "parameters", "args", "function_args"):
        value = reply.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    function = reply.get("function")
    if isinstance(function, dict):
        if isinstance(function.get("arguments"), dict):
            return function["arguments"]
        if isinstance(function.get("parameters"), dict):
            return function["parameters"]
    return {}


def _message_content(reply: dict[str, Any]) -> str:
    for key in ("content", "text", "message", "response", "answer", "output"):
        value = reply.get(key)
        if isinstance(value, dict):
            nested = _message_content(value)
            if nested:
                return nested
            text = _as_text(value.get("text") or value.get("content")).strip()
            if text:
                return text
            continue
        text = _as_text(value).strip()
        if text:
            return text
    nested = reply.get("message")
    if isinstance(nested, dict):
        text = _as_text(nested.get("content")).strip()
        if text:
            return text
    return ""


def validate_reply(reply: Any, tool_names: set[str]) -> dict[str, Any]:
    if isinstance(reply, str):
        reply = {"kind": "message", "content": reply}
    if not isinstance(reply, dict):
        return {
            "kind": "message",
            "content": "Neo could not process that model response.",
        }

    kind = str(reply.get("kind") or reply.get("type") or "").lower()
    name = reply.get("name") or reply.get("tool") or reply.get("function_name")
    if isinstance(reply.get("function"), dict):
        name = name or reply["function"].get("name")

    normalized_name = _normalize_tool_name(name, tool_names)
    if kind in {"tool_call", "tool", "function_call", "function"} and normalized_name:
        return {
            "kind": "tool_call",
            "name": normalized_name,
            "input": _tool_input(reply),
        }
    if normalized_name and not _message_content(reply) and kind != "message":
        return {
            "kind": "tool_call",
            "name": normalized_name,
            "input": _tool_input(reply),
        }

    content = _message_content(reply)
    if content:
        lowered = content.lower()
        if "i'm dots" in lowered or "i am dots" in lowered or "dots studio" in lowered:
            return {"kind": "message", "content": "I'm Neo, your personal assistant."}
        if content.strip() in {"{}", "null", "none"}:
            return {
                "kind": "message",
                "content": "Neo received an empty response. Please try again.",
            }
        return {"kind": "message", "content": content}

    if normalized_name:
        return {
            "kind": "tool_call",
            "name": normalized_name,
            "input": _tool_input(reply),
        }

    for key in ("data", "result", "payload", "output"):
        nested = reply.get(key)
        if isinstance(nested, dict) and nested is not reply:
            return validate_reply(nested, tool_names)

    return {
        "kind": "message",
        "content": "Neo could not safely interpret that response.",
    }

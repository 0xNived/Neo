"""Small, fail-open structured-memory extraction pass.

This is deliberately separate from Neo's chat agent: memory writes should be
schema checked and may never make a normal reply fail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class MemoryCandidate:
    category: str
    key: str
    value: str
    confidence: float


class LlmMemoryExtractor:
    def __init__(self, settings):
        self.provider, self.model, self.api_key, self.base_url = (
            settings.llm_provider,
            settings.llm_model,
            settings.llm_api_key,
            settings.llm_base_url,
        )
        self.reasoning_effort = getattr(settings, "llm_reasoning_effort", None)

    @staticmethod
    def likely_durable(text: str) -> bool:
        lowered = text.casefold()
        return any(
            token in lowered
            for token in (
                "my name",
                "i am ",
                "i'm ",
                "i live ",
                "i live in",
                "i am from",
                "i'm from",
                "birthday",
                "i prefer",
                "i would prefer",
                "i like",
                "i love",
                "i hate",
                "always",
                "never",
                "from now on",
                "remember",
                "stop saying",
                "don't keep",
                "do not keep",
                "talk like",
                "be less",
                "be more",
                "github",
                "my repo",
                "my website",
                "my portfolio",
            )
        )

    async def extract(self, text: str) -> list[MemoryCandidate]:
        if not self.api_key or not self.likely_durable(text):
            return []
        base_urls = {
            "groq": "https://api.groq.com/openai/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "cerebras": "https://api.cerebras.ai/v1",
        }
        base_url = self.base_url or base_urls.get(self.provider)
        if not base_url:
            return []
        endpoint = (
            base_url.rstrip("/")
            if base_url.rstrip("/").endswith("/chat/completions")
            else f"{base_url.rstrip('/')}/chat/completions"
        )
        prompt = (
            "Extract only durable, useful owner memories from the user text. "
            'Return JSON only: {"memories":[{"category":"identity|preference|birthday|instruction",'
            '"key":"stable_snake_case_key","value":"short factual value","confidence":0.0}]}. '
            "Return an empty list for casual chat, transient feelings, guesses, secrets, financial "
            "identifiers, addresses, passwords, or anything ambiguous. An explicit city, region, or "
            "country where the owner says they live or are from is a durable identity fact: use key "
            "location and preserve only the stated place. Communication preferences are "
            "durable: use category preference and keys such as emoji_level, response_length, "
            "response_tone, formality, clarification_style, assistant_conversation_style, or "
            "assistant_avoidance. If the owner tells Neo to stop repeating a phrase, be less "
            "promotional, answer personal questions naturally, or otherwise change its conversational "
            "behavior, save that as a category preference with one of the assistant_* keys. For a "
            "preference comparison, use a stable key such as travel_destination and the chosen value "
            "only. Do not save a question about Neo's tastes as an owner preference unless it also "
            "contains an explicit instruction for how Neo should behave."
        )
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0,
                }
                if self.reasoning_effort:
                    payload["reasoning_effort"] = self.reasoning_effort
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            raw = response.json()["choices"][0]["message"].get("content", "")
            if raw.startswith("~~~"):
                raw = raw.split("\n", 1)[-1].removesuffix("~~~").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].removesuffix("```").strip()
            payload: dict[str, Any] = json.loads(raw)
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            return []
        result = []
        for item in payload.get("memories", []):
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", ""))
            key = str(item.get("key", ""))
            value = str(item.get("value", "")).strip()
            raw_confidence = str(item.get("confidence", ""))
            confidence = (
                float(raw_confidence)
                if raw_confidence.replace(".", "", 1).isdigit()
                else 0.0
            )
            if (
                category in {"identity", "preference", "birthday", "instruction"}
                and key.replace("_", "").isalnum()
                and value
                and 0.7 <= confidence <= 1
            ):
                result.append(MemoryCandidate(category, key[:80], value[:240], confidence))
        return result[:3]

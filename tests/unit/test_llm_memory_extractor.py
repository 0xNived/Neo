import json
from types import SimpleNamespace

import pytest

from neo.memory.llm_extractor import LlmMemoryExtractor


@pytest.mark.asyncio
async def test_extractor_passes_prior_turns_but_requires_latest_owner_confirmation(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"memories": [
                {"category": "preference", "key": "favorite_artist", "value": "Skrillex", "confidence": 0.94}
            ]})}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, url, headers, json):
            sent.update(url=url, headers=headers, payload=json)
            return Response()

    monkeypatch.setattr("neo.memory.llm_extractor.httpx.AsyncClient", Client)
    extractor = LlmMemoryExtractor(SimpleNamespace(
        llm_provider="openai_compatible",
        llm_model="test-model",
        llm_api_key="test-key",
        llm_base_url="https://example.test/v1",
    ))

    facts = await extractor.extract(
        "The first one is correct, Skrillex it is.",
        [
            {"role": "user", "content": "Can you guess the artists I like?"},
            {"role": "assistant", "content": "My guesses are Skrillex, Virtual Riot, and RIOT."},
        ],
    )

    submitted = json.loads(sent["payload"]["messages"][1]["content"])
    assert submitted["latest_owner_message"] == "The first one is correct, Skrillex it is."
    assert submitted["prior_conversation"][-1]["content"].startswith("My guesses")
    assert "Never save an assistant claim unless the latest owner message clearly confirms it" in sent["payload"]["messages"][0]["content"]
    assert [(fact.key, fact.value) for fact in facts] == [("liked_artist", "Skrillex")]

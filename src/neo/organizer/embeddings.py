from __future__ import annotations

import httpx


async def embed(texts: list[str]) -> list[list[float]]:
    """Local Ollama embeddings; raises on an unavailable service."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("http://127.0.0.1:11434/api/embed", json={"model": "nomic-embed-text", "input": texts})
        response.raise_for_status()
        return response.json()["embeddings"]

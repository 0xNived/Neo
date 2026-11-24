"""Background promotion for captured owner-memory candidates.

Captured messages are durable audit records.  This worker is deliberately
conservative: it only promotes schema-validated facts and never treats an
embedding or a keyword hit as permission to change the owner's profile.
"""
from __future__ import annotations

import asyncio
import json
import logging

from .llm_extractor import LlmMemoryExtractor

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    def __init__(self, store, extractor: LlmMemoryExtractor):
        self.store = store
        self.extractor = extractor

    async def run_once(self, user_id: str, limit: int = 16) -> dict[str, int]:
        promoted = 0
        inspected = 0
        for candidate in await self.store.list_candidates(user_id, limit=limit):
            inspected += 1
            extracted = candidate.get("extracted") or []
            if isinstance(extracted, str):
                try:
                    extracted = json.loads(extracted)
                except json.JSONDecodeError:
                    extracted = []
            facts = await self.extractor.extract(candidate["source_message"])
            if not facts:
                continue
            for fact in facts:
                await self.store.remember(
                    user_id,
                    f"The owner's {fact.key.replace('_', ' ')} is {fact.value}.",
                    fact.category,
                    confidence=fact.confidence,
                    memory_key=fact.key,
                    source_kind="consolidated_owner_message",
                    source_session_id=candidate.get("source_session_id"),
                )
            await self.store.mark_candidate_promoted(candidate["id"])
            promoted += 1
        return {"inspected": inspected, "promoted": promoted}

    async def run_forever(self, user_id: str, interval_seconds: int = 300) -> None:
        while True:
            try:
                result = await self.run_once(user_id)
                if result["promoted"]:
                    logger.info("Memory consolidation: %s", result)
            except Exception:
                logger.exception("Memory consolidation failed; candidates remain safe and retryable")
            await asyncio.sleep(interval_seconds)

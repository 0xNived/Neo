"""Shared due-job runner used by the gateway and optional worker process."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

SUPPORTED_IN_APP_KINDS = {"notification", "task", "content", "link"}


async def dispatch_due(store, item: dict) -> None:
    if item.get("execution_mode", "deliver") != "deliver":
        raise ValueError(
            f"Unsupported execution mode: {item.get('execution_mode')}"
        )
    if item.get("delivery_channel") != "in_app":
        raise ValueError(
            f"Unsupported delivery channel: {item.get('delivery_channel')}"
        )
    if item.get("kind") not in SUPPORTED_IN_APP_KINDS:
        raise ValueError(f"Unsupported scheduled job kind: {item.get('kind')}")
    await store.mark_ready(item["id"])


async def process_due(store) -> int:
    """Claim all due jobs once and make valid in-app jobs visible to the owner."""
    processed = 0
    for item in await store.claim_due():
        logger.info("Scheduled job due: %s (%s)", item["title"], item["kind"])
        try:
            await dispatch_due(store, item)
            processed += 1
        except Exception as error:
            logger.exception("Scheduled job failed: %s", item["id"])
            await store.mark_failed(item["id"], str(error))
    return processed


async def run_forever(store, interval_seconds: float = 1.0) -> None:
    while True:
        await process_due(store)
        await asyncio.sleep(interval_seconds)

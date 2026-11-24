import asyncio
import logging
import os

from neo.configuration.settings import load_settings
from neo.memory.consolidator import MemoryConsolidator
from neo.memory.llm_extractor import LlmMemoryExtractor
from neo.memory.postgres_store import PostgresMemoryStore
from neo.reminders.postgres_store import PostgresReminderStore
from neo.reminders.runner import run_forever
from neo.reminders.store import SqliteReminderStore

logger = logging.getLogger(__name__)

async def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    store = (
        PostgresReminderStore(settings.database_url)
        if settings.database_url
        else SqliteReminderStore(settings.database_path)
    )
    await store.initialize()
    memory = PostgresMemoryStore(settings.database_url, settings.memory_ttl_days) if settings.database_url else None
    if memory:
        await memory.initialize()
    tasks = [asyncio.create_task(run_forever(store))]
    jobs = ["reminder delivery"]
    if memory and settings.llm_api_key:
        tasks.append(
            asyncio.create_task(
                MemoryConsolidator(memory, LlmMemoryExtractor(settings)).run_forever(settings.owner_name)
            )
        )
        jobs.append("memory consolidation")
    logger.info(
        "Neo worker running (%s; database=%s). Press Ctrl+C to stop.",
        ", ".join(jobs),
        "PostgreSQL" if settings.database_url else "SQLite fallback",
    )
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())

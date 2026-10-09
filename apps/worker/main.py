import asyncio
import logging
import os

from neo.configuration.settings import load_settings
from neo.reminders.postgres_store import PostgresReminderStore
from neo.reminders.store import SqliteReminderStore

logger = logging.getLogger(__name__)


async def run():
    settings = load_settings()
    store = (
        PostgresReminderStore(settings.database_url)
        if settings.database_url
        else SqliteReminderStore(settings.database_path)
    )
    await store.initialize()
    logging.basicConfig(level=logging.INFO)
    while True:
        for item in await store.claim_due():
            logger.info("Reminder due: %s", item["title"])
            await store.mark_delivered(item["id"])
        await asyncio.sleep(1)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())

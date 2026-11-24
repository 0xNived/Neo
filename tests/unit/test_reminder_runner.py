import pytest

from neo.reminders.runner import process_due


class DueStore:
    def __init__(self):
        self.ready: list[str] = []
        self.failed: list[tuple[str, str]] = []

    async def claim_due(self):
        return [
            {
                "id": "r1",
                "title": "Check mail",
                "kind": "notification",
                "delivery_channel": "in_app",
                "execution_mode": "deliver",
            }
        ]

    async def mark_ready(self, reminder_id):
        self.ready.append(reminder_id)

    async def mark_failed(self, reminder_id, error):
        self.failed.append((reminder_id, error))


@pytest.mark.asyncio
async def test_due_jobs_become_ready_for_in_app_delivery():
    store = DueStore()

    processed = await process_due(store)

    assert processed == 1
    assert store.ready == ["r1"]
    assert not store.failed

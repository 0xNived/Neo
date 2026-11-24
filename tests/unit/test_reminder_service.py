import pytest

from neo.domain.models import Risk, ToolContext
from neo.reminders.service import ReminderService
from neo.reminders.store import SqliteReminderStore
from neo.tools.registry import ToolRegistry


class ReminderStore:
    def __init__(self):
        self.created = None

    async def list_for_user(self, user_id: str):
        return [{"id": "r1", "title": "Call Sam", "user_id": user_id}]

    async def create(self, user_id: str, title: str, due_at: str, **job):
        self.created = {"user_id": user_id, "title": title, "due_at": due_at, **job}
        return self.created

    async def update_context(self, user_id: str, reminder_id: str, **context):
        return {"id": reminder_id, "user_id": user_id, "title": "Keep title", "payload": context}

    async def update(self, user_id: str, reminder_id: str, **changes):
        return {"id": reminder_id, "user_id": user_id, "title": changes.get("title", "Keep title"), **changes}


@pytest.mark.asyncio
async def test_reminder_service_registers_read_only_list_tool():
    registry = ToolRegistry()
    ReminderService(ReminderStore(), "Asia/Calcutta").register(registry)

    tool = registry.tools["reminders.list"]
    assert tool.risk == Risk.READ
    result = await tool.execute({}, ToolContext("nico", "session", "request"))
    assert result["ok"] is True
    assert result["data"][0]["title"] == "Call Sam"


@pytest.mark.asyncio
async def test_scheduler_creates_typed_link_job():
    store = ReminderStore()
    registry = ToolRegistry()
    ReminderService(store, "Asia/Calcutta").register(registry)

    result = await registry.tools["scheduler.schedule"].execute(
        {
            "title": "Watch this",
            "due_at": "2030-01-01T10:00:00+05:30",
            "kind": "link",
            "body": "A useful video",
            "url": "https://www.youtube.com/watch?v=example",
        },
        ToolContext("nico", "session", "request"),
    )

    assert result["ok"] is True
    assert store.created["kind"] == "link"
    assert store.created["payload"]["url"].startswith("https://")
    assert store.created["delivery_channel"] == "in_app"


@pytest.mark.asyncio
async def test_scheduler_rejects_unsupported_or_unsafe_jobs():
    registry = ToolRegistry()
    ReminderService(ReminderStore(), "Asia/Calcutta").register(registry)
    tool = registry.tools["scheduler.schedule"]
    context = ToolContext("nico", "session", "request")

    agent = await tool.execute(
        {"title": "Run freely", "due_at": "2030-01-01T10:00:00+05:30", "kind": "agent"},
        context,
    )
    unsafe_link = await tool.execute(
        {
            "title": "Open",
            "due_at": "2030-01-01T10:00:00+05:30",
            "kind": "link",
            "url": "file:///secret",
        },
        context,
    )

    assert agent["ok"] is False
    assert unsafe_link["ok"] is False


@pytest.mark.asyncio
async def test_sqlite_job_waits_until_owner_acknowledges(tmp_path):
    store = SqliteReminderStore(tmp_path / "neo.sqlite3")
    await store.initialize()
    job = await store.create(
        "nico",
        "Watch later",
        "2100-01-01T10:00:00+05:30",
        kind="link",
        payload={"body": "Video", "url": "https://example.com/video"},
    )

    await store.mark_ready(job["id"])
    ready = (await store.list_for_user("nico"))[0]
    assert ready["status"] == "ready"
    assert ready["payload"]["url"] == "https://example.com/video"

    assert await store.acknowledge("someone-else", job["id"]) is False
    assert await store.acknowledge("nico", job["id"]) is True
    delivered = (await store.list_for_user("nico"))[0]
    assert delivered["status"] == "delivered"


@pytest.mark.asyncio
async def test_interval_job_reschedules_after_owner_acknowledges(tmp_path):
    store = SqliteReminderStore(tmp_path / "neo.sqlite3")
    await store.initialize()
    job = await store.create(
        "nico",
        "Stretch",
        "2100-01-01T10:00:00+05:30",
        schedule_type="interval",
        repeat_every_seconds=300,
    )

    await store.mark_ready(job["id"])
    assert await store.acknowledge("nico", job["id"]) is True
    scheduled = (await store.list_for_user("nico"))[0]
    assert scheduled["status"] == "scheduled"
    assert scheduled["schedule_type"] == "interval"
    assert scheduled["repeat_every_seconds"] == 300


@pytest.mark.asyncio
async def test_reminder_context_update_keeps_title_and_time(tmp_path):
    store = SqliteReminderStore(tmp_path / "neo.sqlite3")
    await store.initialize()
    created = await store.create(
        "nico", "Look at my to-do list", "2100-01-01T10:00:00+05:30"
    )
    updated = await store.update_context(
        "nico", created["id"], body="TO-DO complete kar or tu chomu h"
    )

    assert updated["title"] == "Look at my to-do list"
    assert updated["due_at"] == created["due_at"]
    assert updated["payload"]["body"] == "TO-DO complete kar or tu chomu h"


@pytest.mark.asyncio
async def test_reminder_update_moves_the_existing_job(tmp_path):
    store = SqliteReminderStore(tmp_path / "neo.sqlite3")
    await store.initialize()
    created = await store.create(
        "nico", "Look at my to-do list", "2100-01-01T10:00:00+05:30"
    )

    updated = await store.update(
        "nico", created["id"], due_at="2100-01-01T12:10:00+05:30"
    )

    assert updated["id"] == created["id"]
    assert updated["title"] == created["title"]
    assert updated["due_at"] == "2100-01-01T12:10:00+05:30"
    assert (await store.list_for_user("nico"))[0]["due_at"] == updated["due_at"]


@pytest.mark.asyncio
async def test_reminder_service_exposes_context_update_tool():
    registry = ToolRegistry()
    ReminderService(ReminderStore(), "Asia/Calcutta").register(registry)

    result = await registry.tools["reminders.update_context"].execute(
        {"reminder_id": "r1", "body": "Keep the title; add this context."},
        ToolContext("nico", "session", "request"),
    )

    assert result["ok"] is True
    assert result["data"]["title"] == "Keep title"
    assert result["data"]["payload"]["body"].startswith("Keep the title")


@pytest.mark.asyncio
async def test_reminder_service_exposes_full_update_tool():
    registry = ToolRegistry()
    ReminderService(ReminderStore(), "Asia/Calcutta").register(registry)

    result = await registry.tools["reminders.update"].execute(
        {"reminder_id": "r1", "due_at": "2100-01-01T12:10:00+05:30"},
        ToolContext("nico", "session", "request"),
    )

    assert result["ok"] is True
    assert result["data"]["due_at"] == "2100-01-01T06:40:00+00:00"

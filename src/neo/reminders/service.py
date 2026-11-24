from datetime import UTC, datetime
from urllib.parse import urlparse

from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext
from .store import SqliteReminderStore

SUPPORTED_KINDS = {"notification", "task", "content", "link"}


def normalize_job_input(data: dict, *, default_kind: str = "notification") -> dict:
    kind = str(data.get("kind") or default_kind).strip().lower()
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"Unsupported scheduled job kind: {kind}")
    url = str(data.get("url") or "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Scheduled links must use a valid http or https URL")
    if kind == "link" and not url:
        raise ValueError("A link job requires a URL")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError("metadata must be an object")
    schedule_type = str(data.get("schedule_type") or "one_shot").strip().lower()
    if schedule_type not in {"one_shot", "interval"}:
        raise ValueError("schedule_type must be one_shot or interval")
    repeat_every_seconds = data.get("repeat_every_seconds")
    if schedule_type == "interval":
        if not isinstance(repeat_every_seconds, int) or repeat_every_seconds < 60:
            raise ValueError("Interval jobs require repeat_every_seconds of at least 60")
    elif repeat_every_seconds is not None:
        raise ValueError("repeat_every_seconds is only valid for interval jobs")
    return {
        "kind": kind,
        "payload": {
            "body": str(data.get("body") or "").strip(),
            "url": url or None,
            "metadata": metadata,
        },
        "delivery_channel": "in_app",
        "schedule_type": schedule_type,
        "repeat_every_seconds": repeat_every_seconds,
        # Execution is deliberately delivery-only until a separately
        # authorized external handler exists.
        "execution_mode": "deliver",
    }


def normalize_context_update(data: dict) -> dict:
    """Validate an update that must not change a job's title or schedule."""
    url = data.get("url")
    if url is not None:
        url = str(url).strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Scheduled links must use a valid http or https URL")
        else:
            url = None
    metadata = data.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise TypeError("metadata must be an object")
    body = data.get("body")
    if body is not None:
        body = str(body).strip()
    if body is None and url is None and metadata is None:
        raise ValueError("Provide body, url, or metadata to update reminder context")
    return {"body": body, "url": url, "metadata": metadata}


def normalize_reminder_update(data: dict) -> dict:
    """Validate a partial edit to an existing scheduled job."""
    update: dict = {}
    if "title" in data:
        title = str(data["title"] or "").strip()
        if not title:
            raise ValueError("Reminder title cannot be empty")
        update["title"] = title
    if "due_at" in data:
        due_at = str(data["due_at"] or "").strip()
        try:
            due = datetime.fromisoformat(due_at)
        except ValueError as error:
            raise ValueError("due_at must be an ISO-8601 timestamp with timezone") from error
        if due.tzinfo is None or due.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("due_at must be a future ISO-8601 timestamp with timezone")
        update["due_at"] = due.astimezone(UTC).isoformat()
    context = normalize_context_update(data) if any(key in data for key in ("body", "url", "metadata")) else {}
    update.update({key: value for key, value in context.items() if value is not None})
    if "schedule_type" in data:
        schedule_type = str(data["schedule_type"] or "").strip().lower()
        if schedule_type not in {"one_shot", "interval"}:
            raise ValueError("schedule_type must be one_shot or interval")
        update["schedule_type"] = schedule_type
    if "repeat_every_seconds" in data:
        repeat = data["repeat_every_seconds"]
        if repeat is not None and (not isinstance(repeat, int) or repeat < 60):
            raise ValueError("repeat_every_seconds must be at least 60")
        update["repeat_every_seconds"] = repeat
    if update.get("schedule_type") == "interval" and not update.get("repeat_every_seconds"):
        raise ValueError("Interval jobs require repeat_every_seconds")
    if not update:
        raise ValueError("Provide at least one reminder field to update")
    return update


class ReminderService:
    def __init__(self, store: SqliteReminderStore, timezone: str):
        self.store, self.timezone = store, timezone

    def register(self, registry):
        registry.add_profile(
            IntegrationProfile(
                "reminders",
                f"The scheduler is enabled. Owner timezone: {self.timezone}. Use reminders.list to answer questions about saved jobs. Use reminders.create for a simple reminder and scheduler.schedule for a timed notification, task prompt, content item, or link. Jobs may be one_shot or interval (repeat_every_seconds >= 60). Use ISO-8601 due_at with timezone and confirm required missing details before creation. Only in-app delivery is currently available; there is no autonomous external-agent execution.",
            )
        )

        async def list_reminders(_data: dict, context: ToolContext):
            return {"ok": True, "data": await self.store.list_for_user(context.user_id)}

        async def create(data: dict, context: ToolContext):
            try:
                job = normalize_job_input(data)
                return {
                    "ok": True,
                    "data": await self.store.create(
                        context.user_id,
                        str(data.get("title", "")),
                        str(data.get("due_at", "")),
                        **job,
                    ),
                }
            except (TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}

        async def schedule(data: dict, context: ToolContext):
            try:
                job = normalize_job_input(data)
                return {
                    "ok": True,
                    "data": await self.store.create(
                        context.user_id,
                        str(data.get("title", "")),
                        str(data.get("due_at", "")),
                        **job,
                    ),
                }
            except (TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}

        async def update_context(data: dict, context: ToolContext):
            try:
                updated = await self.store.update_context(
                    context.user_id,
                    str(data["reminder_id"]),
                    **normalize_context_update(data),
                )
                if not updated:
                    return {"ok": False, "error": "Scheduled job not found"}
                return {"ok": True, "data": updated}
            except (TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}

        async def update(data: dict, context: ToolContext):
            try:
                updated = await self.store.update(
                    context.user_id,
                    str(data["reminder_id"]),
                    **normalize_reminder_update(data),
                )
                if not updated:
                    return {"ok": False, "error": "Scheduled job not found"}
                return {"ok": True, "data": updated}
            except (TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}

        registry.register(
            Tool(
                "reminders.update",
                "Edit an existing scheduled job, including its title, time, repeat schedule, or delivery context",
                "reminders",
                Risk.WRITE,
                {
                    "type": "object",
                    "required": ["reminder_id"],
                    "properties": {
                        "reminder_id": {"type": "string"},
                        "title": {"type": "string"},
                        "due_at": {"type": "string"},
                        "body": {"type": "string"},
                        "url": {"type": "string"},
                        "metadata": {"type": "object"},
                        "schedule_type": {"type": "string", "enum": ["one_shot", "interval"]},
                        "repeat_every_seconds": {"type": "integer", "minimum": 60},
                    },
                },
                "Requires approval. First use reminders.list to identify the exact job ID. Use this to move, rename, repeat, or otherwise edit an existing reminder. Keep fields not mentioned by the owner unchanged.",
                update,
            )
        )

        registry.register(
            Tool(
                "reminders.list",
                "List the owner's scheduled and delivered reminders",
                "reminders",
                Risk.READ,
                {"type": "object", "properties": {}},
                "Use for questions such as 'what are my reminders?', 'any reminders?', or 'show scheduled reminders'. This is read-only and does not need approval.",
                list_reminders,
            )
        )

        registry.register(
            Tool(
                "reminders.update_context",
                "Add or replace the context/body/link for one existing scheduled job without changing its title or time",
                "reminders",
                Risk.WRITE,
                {
                    "type": "object",
                    "required": ["reminder_id"],
                    "properties": {
                        "reminder_id": {"type": "string"},
                        "body": {"type": "string"},
                        "url": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                },
                "Requires approval. First use reminders.list to identify the exact scheduled job ID. Use when the owner asks to add or change context while keeping the existing title and time unchanged.",
                update_context,
            )
        )

        registry.register(
            Tool(
                "reminders.create",
                "Create a durable owner reminder",
                "reminders",
                Risk.WRITE,
                {
                    "type": "object",
                    "required": ["title", "due_at"],
                    "properties": {
                        "title": {"type": "string"},
                        "due_at": {"type": "string"},
                        "body": {"type": "string"},
                        "url": {"type": "string"},
                        "schedule_type": {"type": "string", "enum": ["one_shot", "interval"]},
                        "repeat_every_seconds": {"type": "integer", "minimum": 60},
                    },
                },
                "Requires approval. Use only for an explicit reminder request with a specific time/date; never use for saving notes, links, addresses, tasks, or credentials.",
                create,
            )
        )

        registry.register(
            Tool(
                "scheduler.schedule",
                "Schedule an in-app notification, task prompt, content item, or link",
                "reminders",
                Risk.WRITE,
                {
                    "type": "object",
                    "required": ["title", "due_at", "kind"],
                    "properties": {
                        "title": {"type": "string"},
                        "due_at": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["notification", "task", "content", "link"],
                        },
                        "body": {"type": "string"},
                        "url": {"type": "string"},
                        "metadata": {"type": "object"},
                        "schedule_type": {"type": "string", "enum": ["one_shot", "interval"]},
                        "repeat_every_seconds": {"type": "integer", "minimum": 60},
                    },
                },
                "Requires approval. Use for timed content or task prompts; use interval only when the owner explicitly asks to repeat. A link kind requires an http(s) URL. Do not claim external apps or agent runs are supported yet.",
                schedule,
            )
        )

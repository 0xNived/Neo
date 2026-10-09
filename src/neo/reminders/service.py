from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext
from .store import SqliteReminderStore


class ReminderService:
    def __init__(self, store: SqliteReminderStore, timezone: str):
        self.store, self.timezone = store, timezone

    def register(self, registry):
        registry.add_profile(
            IntegrationProfile(
                "reminders",
                f"Reminders are enabled. Owner timezone: {self.timezone}. Use ISO-8601 due_at with timezone. Confirm title and time before creation.",
            )
        )

        async def create(data: dict, context: ToolContext):
            try:
                return {
                    "ok": True,
                    "data": await self.store.create(
                        context.user_id,
                        str(data.get("title", "")),
                        str(data.get("due_at", "")),
                    ),
                }
            except ValueError as error:
                return {"ok": False, "error": str(error)}

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
                    },
                },
                "Requires approval. Use only for an explicit reminder request with a specific time/date; never use for saving notes, links, addresses, tasks, or credentials.",
                create,
            )
        )

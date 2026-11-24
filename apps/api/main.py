import asyncio
import json
import logging
import os
import re
import traceback
import uuid
from pathlib import Path

import aiosqlite
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from neo.brain.providers import build_brain
from neo.configuration.settings import load_settings
from neo.controller.agent_controller import AgentController
from neo.integrations import organizer as organizer_tools
from neo.integrations.browser import BrowserService
from neo.integrations.catalog import builtin_statuses
from neo.integrations.web_research import WebResearchService
from neo.link_previews import preview_url
from neo.memory.llm_extractor import LlmMemoryExtractor
from neo.memory.postgres_sessions import PostgresSessionStore
from neo.memory.postgres_store import PostgresMemoryStore
from neo.memory.service import MemoryService
from neo.memory.sqlite_sessions import SqliteSessionStore
from neo.memory.sqlite_store import SqliteMemoryStore
from neo.organizer.obsidian import export_vault
from neo.organizer.store import OrganizerStore
from neo.reminders.postgres_store import PostgresReminderStore
from neo.reminders.runner import run_forever
from neo.reminders.service import ReminderService, normalize_job_input
from neo.reminders.store import SqliteReminderStore
from neo.tools.registry import ToolRegistry

settings = load_settings()
if settings.database_url:
    memory = PostgresMemoryStore(settings.database_url, settings.memory_ttl_days)
    sessions = PostgresSessionStore(settings.database_url)
    reminders = PostgresReminderStore(settings.database_url)
    organizer = OrganizerStore(settings.database_url)
else:
    memory = SqliteMemoryStore(settings.database_path, settings.memory_ttl_days)
    sessions = SqliteSessionStore(settings.database_path)
    reminders = SqliteReminderStore(settings.database_path)
    organizer = None
registry = ToolRegistry()
MemoryService(memory).register(registry)
ReminderService(reminders, settings.owner_timezone).register(registry)
WebResearchService().register(registry)
if settings.browser_enabled:
    BrowserService(settings).register(registry)
if organizer:
    organizer_tools.register(registry, organizer)
normal_brain = build_brain(settings)
controller = AgentController(
    normal_brain,
    sessions,
    registry,
    settings.allow_external_writes,
    settings.max_tool_rounds,
    memory,
    settings.owner_timezone,
    organizer,
    LlmMemoryExtractor(settings) if settings.database_url else None,
)
app = FastAPI(title="Neo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe_diagnostic_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"\b(?:sk|gsk|sk-or-v1)-[A-Za-z0-9_-]{12,}\b",
        "[REDACTED_API_KEY]",
        text,
    )
    return text[:12000]


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, error: Exception):
    reference = str(uuid.uuid4())
    logging.getLogger("neo").exception("Unhandled gateway error [%s]", reference)
    diagnostic = {
        "source": "neo_gateway",
        "reference": reference,
        "error_type": type(error).__name__,
        "message": safe_diagnostic_text(error),
    }
    if settings.environment == "development":
        diagnostic["traceback"] = safe_diagnostic_text(
            "".join(traceback.format_exception(error))
        )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Neo hit an internal gateway error.",
            "diagnostic": diagnostic,
        },
    )

@app.middleware("http")
async def prevent_stale_frontend(request, call_next):
    response = await call_next(request)
    if request.url.path.endswith((".html", ".js", ".css")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


async def migrate_legacy_sqlite() -> None:
    """Copy the existing local data once, so switching databases is not a reset."""
    if not settings.database_url or await memory.migration_completed("sqlite-v1"):
        return
    if not settings.database_path.exists():
        await memory.mark_migration_completed("sqlite-v1")
        return
    async with aiosqlite.connect(settings.database_path) as db:
        tables = {
            row[0]
            for row in await (
                await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "memories" in tables:
            rows = await (
                await db.execute(
                    "SELECT user_id,content,category,confidence FROM memories"
                )
            ).fetchall()
            for user_id, content, category, confidence in rows:
                await memory.remember(user_id, content, category, confidence=confidence)
        if "sessions" in tables:
            rows = await (
                await db.execute(
                    "SELECT id,user_id,messages_json,references_json FROM sessions"
                )
            ).fetchall()
            for session_id, user_id, messages, references in rows:
                session = await sessions.get_or_create(session_id, user_id)
                session.messages = json.loads(messages)
                session.references = json.loads(references)
                await sessions.save(session)
    await memory.mark_migration_completed("sqlite-v1")


@app.on_event("startup")
async def startup():
    await memory.initialize()
    await sessions.initialize()
    await reminders.initialize()
    if organizer:
        await organizer.initialize()
    await migrate_legacy_sqlite()
    app.state.reminder_runner = asyncio.create_task(run_forever(reminders))
    if organizer:
        async def backfill_organizer_semantics() -> None:
            try:
                result = await organizer.backfill_semantic_index(settings.owner_name)
                logging.getLogger("neo").info("Organizer semantic backfill: %s", result)
            except Exception:
                logging.getLogger("neo").warning(
                    "Organizer semantic backfill skipped; lexical search remains available.",
                    exc_info=True,
                )

        asyncio.create_task(backfill_organizer_semantics())


@app.on_event("shutdown")
async def shutdown():
    runner = getattr(app.state, "reminder_runner", None)
    if runner:
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass


def owner(key: str | None):
    if settings.owner_api_key and key != settings.owner_api_key:
        raise HTTPException(401, "Owner authentication required")


class Chat(BaseModel):
    session_id: str
    text: str


class SessionTitle(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class Memory(BaseModel):
    content: str
    category: str = "semantic"


class Approval(BaseModel):
    approved: bool


@app.get("/v1/previews")
async def preview(url: str, x_neo_owner_key: str | None = Header(default=None)):
    """Return safe Open Graph metadata for a public chat link."""
    owner(x_neo_owner_key)
    return await preview_url(url)


class ReminderRequest(BaseModel):
    title: str
    due_at: str
    kind: str = "notification"
    body: str = ""
    url: str | None = None
    metadata: dict = Field(default_factory=dict)
    schedule_type: str = "one_shot"
    repeat_every_seconds: int | None = None

class OrganizerGroup(BaseModel):
    name: str
    kind: str = "notes"
    parent_id: str | None = None


class OrganizerReference(BaseModel):
    type: str
    value: str
    label: str = ""
    note: str = ""


class OrganizerItem(BaseModel):
    group_id: str
    kind: str = "note"
    title: str
    content: str = ""
    url: str | None = None
    metadata: dict = Field(default_factory=dict)
    references: list[OrganizerReference] = Field(default_factory=list)


@app.post("/v1/chat")
async def chat(body: Chat, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    response = await controller.handle_text(
        body.session_id,
        settings.owner_name,
        body.text,
    )
    session = await sessions.get_or_create(body.session_id, settings.owner_name)
    last_assistant = next(
        (
            message
            for message in reversed(session.messages)
            if message.get("role") == "assistant"
            and message.get("content") == response
        ),
        {},
    )
    return {
        "response": response,
        "diagnostic": last_assistant.get("diagnostic"),
    }


@app.post("/v1/memories")
async def remember(body: Memory, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    await memory.remember(settings.owner_name, body.content, body.category)
    return {"ok": True}


@app.get("/v1/memories")
async def memories(
    q: str = "",
    category: str | None = None,
    x_neo_owner_key: str | None = Header(default=None),
):
    owner(x_neo_owner_key)
    if category:
        return {"memories": await memory.list_category(settings.owner_name, category)}
    return {"memories": await memory.recall(settings.owner_name, q)}


@app.post("/v1/approvals/{approval_id}")
async def resolve_approval(
    approval_id: str, body: Approval, x_neo_owner_key: str | None = Header(default=None)
):
    owner(x_neo_owner_key)
    return await controller.approve_action(approval_id, body.approved)


@app.get("/v1/approvals")
async def list_approvals(x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    return {"approvals": await memory.list_pending_approvals(settings.owner_name)}


@app.get("/v1/reminders")
async def list_reminders(x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    return {"reminders": await reminders.list_for_user(settings.owner_name)}


@app.post("/v1/reminders")
async def create_reminder(
    body: ReminderRequest, x_neo_owner_key: str | None = Header(default=None)
):
    owner(x_neo_owner_key)
    try:
        job = normalize_job_input(body.model_dump())
        return await reminders.create(
            settings.owner_name, body.title, body.due_at, **job
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/reminders/{reminder_id}/acknowledge")
async def acknowledge_reminder(
    reminder_id: str, x_neo_owner_key: str | None = Header(default=None)
):
    owner(x_neo_owner_key)
    acknowledged = await reminders.acknowledge(settings.owner_name, reminder_id)
    if not acknowledged:
        raise HTTPException(404, "Scheduled job is not ready or does not exist")
    return {"ok": True}


@app.get("/v1/sessions")
async def list_sessions(
    x_neo_owner_key: str | None = Header(default=None),
):
    owner(x_neo_owner_key)
    return {
        "sessions": await sessions.list_for_user(settings.owner_name)
    }


@app.get("/v1/sessions/{session_id}")
async def get_session(
    session_id: str,
    x_neo_owner_key: str | None = Header(default=None),
):
    owner(x_neo_owner_key)
    session = await sessions.get_or_create(session_id, settings.owner_name)
    return {"id": session.id, "messages": session.messages}


@app.delete("/v1/sessions/{session_id}")
async def delete_session(
    session_id: str,
    x_neo_owner_key: str | None = Header(default=None),
):
    owner(x_neo_owner_key)
    return {
        "ok": await sessions.delete(session_id, settings.owner_name)
    }


@app.patch("/v1/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: SessionTitle,
    x_neo_owner_key: str | None = Header(default=None),
):
    owner(x_neo_owner_key)
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(422, "Conversation title cannot be empty")
    renamed = await sessions.rename(session_id, settings.owner_name, title)
    if not renamed:
        raise HTTPException(404, "Conversation not found")
    return {"ok": True, "title": title}


@app.get("/v1/status")
async def status(x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    return {
        "name": "Neo",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "tools": list(controller.tools.tools),
        "environment": settings.environment,
    }


@app.get("/v1/integrations")
async def integrations(x_neo_owner_key: str | None = Header(default=None)):
    """Secret-free setup state for the settings UI and agent setup."""
    owner(x_neo_owner_key)
    return {"integrations": [item.public() for item in builtin_statuses(settings)]}

def workspace():
    if not organizer:
        raise HTTPException(501, "Organizer requires the configured Postgres database")
    return organizer

@app.get("/v1/organizer/groups")
async def organizer_groups(x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"groups": await workspace().groups(settings.owner_name)}

@app.get("/v1/organizer/groups/trash")
async def organizer_trash(x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"groups": await workspace().archived_groups(settings.owner_name)}

@app.post("/v1/organizer/groups")
async def organizer_group(body: OrganizerGroup, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return await workspace().create_group(settings.owner_name, body.name, body.kind, body.parent_id)

@app.get("/v1/organizer/groups/{group_id}/items")
async def organizer_items(group_id: str, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"items": await workspace().items(settings.owner_name, group_id)}

@app.get("/v1/organizer/search")
async def organizer_search(q: str, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"items": await workspace().search(settings.owner_name, q)}

@app.delete("/v1/organizer/groups/{group_id}")
async def delete_organizer_group(group_id: str, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"ok": await workspace().delete_group(settings.owner_name, group_id)}

@app.post("/v1/organizer/groups/{group_id}/restore")
async def restore_organizer_group(group_id: str, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"ok": await workspace().restore_group(settings.owner_name, group_id)}

@app.post("/v1/organizer/items")
async def organizer_item(body: OrganizerItem, background_tasks: BackgroundTasks, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    metadata = {
        **body.metadata,
        "references": [reference.model_dump() for reference in body.references],
    }
    item = await workspace().create_item(settings.owner_name, body.group_id, body.kind, body.title, body.content, body.url, metadata)
    background_tasks.add_task(workspace().index_item, settings.owner_name, item["id"])
    background_tasks.add_task(workspace().embed_item, settings.owner_name, item["id"])
    if body.url:
        background_tasks.add_task(workspace().enrich_link, settings.owner_name, item["id"])
    return item

@app.post("/v1/organizer/items/{item_id}/checked")
async def organizer_checked(item_id: str, body: Approval, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); await workspace().set_checked(settings.owner_name, item_id, body.approved); return {"ok": True}

@app.delete("/v1/organizer/items/{item_id}")
async def archive_organizer_item(item_id: str, x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key); return {"ok": await workspace().archive_item(settings.owner_name, item_id)}

@app.post("/v1/organizer/obsidian/export")
async def export_obsidian(x_neo_owner_key: str | None = Header(default=None)):
    owner(x_neo_owner_key)
    vault = os.getenv("OBSIDIAN_VAULT_PATH")
    if not vault:
        raise HTTPException(400, "Set OBSIDIAN_VAULT_PATH in .env first")
    return {"ok": True, "exported": await export_vault(workspace(), settings.owner_name, vault)}
web_root = Path(__file__).resolve().parents[1] / "web"
app.mount("/", StaticFiles(directory=web_root, html=True), name="web")

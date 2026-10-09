from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from ..brain.protocols import Brain
from ..domain.models import ToolContext
from ..memory.extractor import memories_from_message
from ..memory.llm_extractor import LlmMemoryExtractor, MemoryCandidate
from ..memory.in_memory import InMemorySessionStore
from ..observability.logging import event
from ..policies.default import allow
from ..tools.registry import ToolRegistry


class AgentController:
    def __init__(
        self,
        brain: Brain,
        sessions: InMemorySessionStore,
        tools: ToolRegistry,
        allow_external_writes: bool,
        max_tool_rounds: int,
        memory=None,
        owner_timezone: str = "Asia/Calcutta",
        organizer=None,
        memory_extractor: LlmMemoryExtractor | None = None,
    ):
        self.brain = brain
        self.sessions = sessions
        self.tools = tools
        self.allow_external_writes = allow_external_writes
        self.max_tool_rounds = max_tool_rounds
        self.memory = memory
        self.owner_timezone = owner_timezone
        self.organizer = organizer
        self.memory_extractor = memory_extractor

    @staticmethod
    def _sensitive_identifier_response(text: str) -> str | None:
        """Keep financial identifiers out of reminders and automatic memory."""
        has_wallet = bool(
            re.search(r"\b(?:ltc1[ac-hj-np-z02-9]{20,}|[LM][1-9A-HJ-NP-Za-km-z]{25,34})\b", text, re.IGNORECASE)
        )
        asks_to_save = bool(re.search(r"\b(save|remember|store|keep)\b", text, re.IGNORECASE))
        if has_wallet and asks_to_save:
            return (
                "I won't turn a financial address into a reminder or automatic memory. "
                "Neo does not have an encrypted vault yet; use a password manager for the address. "
                "I can save a non-sensitive label or note in Organizer if you want."
            )
        return None

    async def _financial_note_request(self, user_id: str, text: str) -> tuple[dict, str] | None:
        """An explicit request may save an address as an Organizer note only."""
        if not self.organizer or not re.search(r"\b(save|store|keep)\b", text, re.IGNORECASE):
            return None
        match = re.search(r"\b(?:ltc1[ac-hj-np-z02-9]{20,}|[LM][1-9A-HJ-NP-Za-km-z]{25,34})\b", text, re.IGNORECASE)
        if not match:
            return None
        groups = await self.organizer.groups(user_id)
        group = next((item for item in groups if item["name"].casefold() == "crypto wallets"), None)
        if not group:
            return None
        return ({"group_id": group["id"], "kind": "note", "title": "Litecoin address", "content": match.group(0)}, group["name"])

    def _current_time_response(self, text: str) -> str | None:
        lowered = text.lower().replace("'", "")
        asks_time = any(item in lowered for item in ("what time", "whats the time", "time is it", "current time"))
        asks_day = any(item in lowered for item in ("what day", "whats the day", "what date", "todays date"))
        if "birthday" in lowered or "bday" in lowered or not (asks_time or asks_day):
            return None
        now = datetime.now(ZoneInfo(self.owner_timezone))
        if asks_time:
            hour = now.strftime("%I").lstrip("0") or "12"
            return f"It's {hour}:{now:%M %p} on {now:%A, %B} {now.day}."
        return f"Today is {now:%A, %B} {now.day}."

    def _birthday_response(self, text: str, birthdays: list[str]) -> str | None:
        if "birthday" not in text.lower() and "bday" not in text.lower():
            return None
        match = next((re.search(r"(\d{2})-(\d{2})", item) for item in birthdays), None)
        if not match or not match.group(1):
            return None
        month, day = int(match.group(1)), int(match.group(2))
        now = datetime.now(ZoneInfo(self.owner_timezone))
        year = now.year + int((month, day) < (now.month, now.day))
        try:
            birthday = datetime(year, month, day, tzinfo=ZoneInfo(self.owner_timezone))
        except ValueError:
            return None
        return f"Your next birthday is {birthday:%A, %B} {birthday.day}, {birthday.year}."

    async def _organizer_task_request(self, user_id: str, text: str) -> tuple[dict, str] | None:
        """Route an explicit “in my X list add Y” request without LLM guesswork."""
        if not self.organizer:
            return None
        match = re.search(
            r"\b(?:in|to)\s+(?:my\s+)?(?P<group>[\w -]+?)(?:\s+list)?\s+(?:add|save)\s*[-:–]?\s*(?P<title>.+)$",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        wanted = re.sub(r"\s+", " ", match.group("group").strip()).casefold()
        title = match.group("title").strip()
        if not title:
            return None
        groups = await self.organizer.groups(user_id)
        group = next((item for item in groups if item["name"].casefold() == wanted), None)
        if not group:
            return None
        return (
            {"group_id": group["id"], "kind": "task", "title": title, "content": ""},
            group["name"],
        )

    async def _organizer_overview(self, user_id: str, text: str) -> str | None:
        if not self.organizer:
            return None
        lowered = text.casefold()
        asks_lists = any(phrase in lowered for phrase in ("what is on my to do list", "what's on my to do list", "what is on my todo list", "what's on my todo list", "my lists", "what lists", "check my list", "show my task lists"))
        if not asks_lists:
            return None
        groups = await self.organizer.groups(user_id)
        if not groups:
            return "You don't have any Organizer collections yet."
        todo = [group for group in groups if group["kind"] == "task" or "todo" in group["name"].casefold() or "to-do" in group["name"].casefold()]
        if todo:
            summary = ", ".join(f"{group['name']} ({group['count']} items)" for group in todo)
            return f"I checked your Organizer. Your task lists are: {summary}."
        summary = ", ".join(f"{group['name']} ({group['count']})" for group in groups)
        return f"I checked your Organizer collections: {summary}."

    async def _task_status_request(self, user_id: str, text: str) -> str | None:
        """Resolve simple task completion requests against the owner's open tasks."""
        if not self.organizer:
            return None
        lowered = text.casefold()
        has_action = re.search(r"\b(mark|set|complete|finish|undo|unmark)\b", lowered)
        has_state = re.search(r"\b(done|complete|finished|undone|open|unmark)\b", lowered)
        if not has_action or not has_state:
            return None
        done = not bool(re.search(r"\b(undo|unmark|undone|open)\b", lowered))
        tasks = []
        for group in await self.organizer.groups(user_id):
            if group["kind"] == "task" or "todo" in group["name"].casefold() or "to-do" in group["name"].casefold():
                tasks.extend(await self.organizer.items(user_id, group["id"]))
        requested_number = re.search(r"\b(?:task\s*)?(\d+)\b", lowered)
        if requested_number:
            index = int(requested_number.group(1)) - 1
            target = tasks[index] if 0 <= index < len(tasks) else None
        else:
            target = next((item for item in tasks if item["title"].casefold() in lowered), None)
            if target is None and re.search(r"\b(it|this)\b", lowered):
                target = next((item for item in tasks if item["checked"] != done), None)
        if not target:
            return None
        await self.organizer.set_checked(user_id, target["id"], done)
        return f"Marked **{target['title']}** as {'done' if done else 'not done'}."

    @staticmethod
    def _clarification_for_incomplete_tool(name: str, data: dict) -> str | None:
        """Reject placeholder tool input before it becomes an approval request."""
        if name != "reminders.create":
            return None
        title = str(data.get("title", "")).strip()
        due_at = str(data.get("due_at", "")).strip()
        valid_title = bool(title and title not in {"?", "reminder", "none", "n/a"})
        try:
            due = datetime.fromisoformat(due_at)
            valid_due = due.tzinfo is not None
        except ValueError:
            valid_due = False
        if valid_title and valid_due:
            return None
        if not valid_title and not valid_due:
            return "What should I remind you about, and when? For example: ‘remind me to call Sam today at 3 PM.’"
        if not valid_title:
            return "What should the reminder be about?"
        return "What time should I set it for? Please use a time like ‘today at 3 PM’ or a date and time."

    @staticmethod
    def _model_safe_messages(messages: list[dict]) -> list[dict]:
        """Keep sensitive values out of the LLM while retaining a usable UI history.

        This is a data-boundary scrubber, not an intent parser: the Organizer
        handles exact retrieval; the model only sees that a private value was
        previously displayed.
        """
        wallet_pattern = re.compile(r"\b(?:ltc1[ac-hj-np-z02-9]{20,}|[LM][1-9A-HJ-NP-Za-km-z]{25,34})\b", re.IGNORECASE)
        safe_messages = []
        for message in messages:
            copy = dict(message)
            content = copy.get("content")
            if copy.get("private_to_model") or (isinstance(content, str) and wallet_pattern.search(content)):
                copy["content"] = "[A private wallet address was displayed to the owner. Do not repeat or discuss its value unless the owner explicitly asks to retrieve it.]"
            copy.pop("private_to_model", None)
            safe_messages.append(copy)
        return safe_messages

    @staticmethod
    def _communication_preferences(text: str) -> list[MemoryCandidate]:
        """Explicit delivery preferences must work even when the extractor is offline."""
        lowered = text.casefold()
        candidates = []
        if re.search(r"\b(no|less|fewer|not many)\s+emoji|\bdon't\s+like.*emoji|\bhate.*emoji", lowered):
            candidates.append(MemoryCandidate("preference", "emoji_level", "minimal or no emojis", 0.95))
        elif re.search(r"\b(more|lots of|many)\s+emoji", lowered):
            candidates.append(MemoryCandidate("preference", "emoji_level", "use emojis naturally", 0.9))
        if re.search(r"\b(concise|short|brief|direct)\s+(answers|replies|response|tone)?", lowered):
            candidates.append(MemoryCandidate("preference", "response_length", "concise and direct", 0.93))
        if re.search(r"\b(casual|chill|relaxed|friendly)\s+(tone|style|reply|replies)?", lowered):
            candidates.append(MemoryCandidate("preference", "response_tone", "casual and friendly", 0.9))
        if re.search(r"\b(formal|professional)\s+(tone|style|reply|replies)?", lowered):
            candidates.append(MemoryCandidate("preference", "response_tone", "professional and clear", 0.9))
        return candidates

    async def handle_text(self, session_id: str, user_id: str, text: str) -> str:
        session = await self.sessions.get_or_create(session_id, user_id)
        financial_note = await self._financial_note_request(user_id, text)
        if financial_note and self.memory:
            input_data, group_name = financial_note
            approval_id = str(uuid.uuid4())
            await self.memory.create_approval(
                approval_id, user_id, "organizer.save_item",
                {"input": input_data, "session_id": session_id, "group_name": group_name, "sensitive": True},
            )
            # Do not persist the raw address in chat history. It appears only
            # in the approved Organizer item the owner explicitly requested.
            session.messages.extend([
                {"role": "user", "content": "[Owner requested an Organizer note containing a financial identifier; content redacted.]"},
                {"role": "assistant", "content": "Ready to save the wallet address to **Crypto Wallets** as a note. It will be stored in your local PostgreSQL database and is not encrypted at rest. Approve it in the Actions panel to continue."},
            ])
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
            return session.messages[-1]["content"]
        sensitive = self._sensitive_identifier_response(text)
        if sensitive:
            # Retain only a redacted audit marker, never the raw identifier.
            session.messages.append({"role": "user", "content": "[Owner attempted to save a financial identifier; content redacted.]"})
            session.messages.append({"role": "assistant", "content": sensitive})
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
            return sensitive
        session.messages.append({"role": "user", "content": text})
        if self.memory:
            candidates = await self.memory_extractor.extract(text) if self.memory_extractor else []
            explicit_style = self._communication_preferences(text)
            keys = {candidate.key for candidate in explicit_style}
            candidates = [*explicit_style, *[candidate for candidate in candidates if candidate.key not in keys]]
            if candidates:
                for candidate in candidates:
                    content = f"The owner's {candidate.key.replace('_', ' ')} is {candidate.value}."
                    await self.memory.remember(user_id, content, candidate.category, confidence=candidate.confidence, memory_key=candidate.key)
            else:
                # Offline/provider-failure fallback: limited heuristics keep
                # basic identity and explicit preference support available.
                for category, content, confidence in memories_from_message(text):
                    await self.memory.remember(user_id, content, category, confidence=confidence)
            profile = [
                *await self.memory.list_category(user_id, "identity", limit=4),
                *await self.memory.list_category(user_id, "preference", limit=8),
                *await self.memory.list_category(user_id, "instruction", limit=6),
            ]
            context = list(dict.fromkeys([*profile, *await self.memory.recall(user_id, text)]))
        else:
            context = []
        birthdays = [] if not self.memory else await self.memory.list_category(user_id, "birthday", limit=1)
        instant = self._birthday_response(text, birthdays) or self._current_time_response(text)
        if instant:
            session.messages.append({"role": "assistant", "content": instant})
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
            return instant

        task_status = await self._task_status_request(user_id, text)
        if task_status:
            session.messages.append({"role": "assistant", "content": task_status})
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
            return task_status

        overview = await self._organizer_overview(user_id, text)
        if overview:
            session.messages.append({"role": "assistant", "content": overview})
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
            return overview

        organizer_task = await self._organizer_task_request(user_id, text)
        if organizer_task and self.memory:
            input_data, group_name = organizer_task
            approval_id = str(uuid.uuid4())
            await self.memory.create_approval(
                approval_id,
                user_id,
                "organizer.save_item",
                {"input": input_data, "session_id": session_id, "group_name": group_name},
            )
            call_id = str(uuid.uuid4())
            session.messages.extend([
                {"role": "assistant", "content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "organizer_save_item", "arguments": input_data}}]},
                {"role": "tool", "name": "organizer.save_item", "tool_call_id": call_id, "content": {"ok": False, "error": "human approval required", "approval_id": approval_id}},
            ])
            response = f"Ready to add **{input_data['title']}** to your **{group_name}** list. Approve it in the Actions panel."
            session.messages.append({"role": "assistant", "content": response})
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
            return response

        for _ in range(self.max_tool_rounds):
            messages = ([{"role": "system", "content": "Relevant owner memories: " + " | ".join(context)}] if context else []) + self._model_safe_messages(session.messages)
            reply = await self.brain.complete(messages, list(self.tools.tools.values()), list(self.tools.profiles.values()))
            if reply["kind"] == "message":
                content = reply["content"]
                session.messages.append({"role": "assistant", "content": content})
                if hasattr(self.sessions, "save"):
                    await self.sessions.save(session)
                return content
            tool = self.tools.tools.get(reply["name"])
            if not tool:
                result = {"ok": False, "error": "unknown tool"}
            else:
                permitted, reason = allow(tool, self.allow_external_writes)
                if permitted:
                    result = await tool.execute(reply.get("input", {}), ToolContext(user_id, session_id, str(uuid.uuid4())))
                elif reason == "human approval required" and self.memory:
                    clarification = self._clarification_for_incomplete_tool(tool.name, reply.get("input", {}))
                    if clarification:
                        session.messages.append({"role": "assistant", "content": clarification})
                        if hasattr(self.sessions, "save"):
                            await self.sessions.save(session)
                        return clarification
                    approval_id = str(uuid.uuid4())
                    await self.memory.create_approval(approval_id, user_id, tool.name, {"input": reply.get("input", {}), "session_id": session_id})
                    result = {"ok": False, "error": reason, "approval_id": approval_id}
                else:
                    result = {"ok": False, "error": reason}
            event("tool.completed", tool=reply["name"], ok=result.get("ok", False), user_id=user_id)
            call_id = str(uuid.uuid4())
            session.messages.extend([
                {"role": "assistant", "content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": reply["name"].replace(".", "_"), "arguments": reply.get("input", {})}}]},
                {"role": "tool", "name": reply["name"], "tool_call_id": call_id, "content": result},
            ])
            if result.get("error") == "human approval required":
                response = "I've prepared that action. Approve or decline it in the Actions panel."
                session.messages.append({"role": "assistant", "content": response})
                if hasattr(self.sessions, "save"):
                    await self.sessions.save(session)
                return response
            if hasattr(self.sessions, "save"):
                await self.sessions.save(session)
        raise RuntimeError("Maximum tool rounds reached")

    async def approve_action(self, approval_id: str, approved: bool) -> dict:
        if not self.memory:
            raise RuntimeError("Approval storage is not configured")
        record = await self.memory.resolve_approval(approval_id, approved)
        if not record:
            return {"ok": False, "error": "approval not found or already resolved"}
        if not approved:
            return {"ok": False, "error": "action denied by owner"}
        tool = self.tools.tools.get(record["tool_name"])
        if not tool:
            return {"ok": False, "error": "tool is no longer available"}
        payload = record["payload"]
        result = await tool.execute(payload["input"], ToolContext(record["user_id"], payload["session_id"], str(uuid.uuid4())))
        # The pending result was saved in the session before approval. Replace
        # it with the actual result so later chat turns do not retry it.
        session = await self.sessions.get_or_create(payload["session_id"], record["user_id"])
        for message in reversed(session.messages):
            if (
                message.get("role") == "tool"
                and message.get("name") == record["tool_name"]
                and isinstance(message.get("content"), dict)
                and message["content"].get("approval_id") == approval_id
            ):
                message["content"] = result
                break
        session.messages.append(
            {"role": "system", "content": f"Approved action completed: {record['tool_name']}. Result: {result}"}
        )
        if hasattr(self.sessions, "save"):
            await self.sessions.save(session)
        if result.get("error") == "due_at must be a future ISO-8601 timestamp with timezone":
            return {"ok": False, "error": "That reminder time has already passed. Ask Neo for a new future time (or tomorrow at that time)."}
        if result.get("ok"):
            if record["tool_name"] == "organizer.save_item":
                group_name = payload.get("group_name", "Organizer")
                result["message"] = f"Added **{payload['input'].get('title', 'item')}** to your **{group_name}** list."
            elif record["tool_name"] == "organizer.create_group":
                result["message"] = f"Created the **{payload['input'].get('name', 'new')}** collection."
            elif record["tool_name"] == "organizer.archive_item":
                result["message"] = "Moved the selected item to **Trash**. It is recoverable and was not permanently deleted."
            elif record["tool_name"] == "organizer.archive_group":
                result["message"] = "Moved the collection and its items to **Trash**. It is recoverable and was not permanently deleted."
            elif record["tool_name"] == "organizer.restore_item":
                result["message"] = "Restored the selected item from **Trash**."
            elif record["tool_name"] == "reminders.create":
                result["message"] = f"Scheduled reminder: **{payload['input'].get('title', 'reminder')}**."
            else:
                result["message"] = "Approved and completed."
        return result

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _flag(value: str | None, default: bool = False) -> bool:
    return default if value is None else value.lower() == "true"


@dataclass(frozen=True)
class Settings:
    environment: str
    max_tool_rounds: int
    allow_external_writes: bool
    discord_mode: str
    discord_guild_ids: list[str]
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_session_path: Path
    owner_name: str
    owner_timezone: str
    owner_api_key: str | None
    memory_ttl_days: int
    database_path: Path
    database_url: str | None
    llm_provider: str
    llm_model: str
    llm_base_url: str | None
    llm_api_key: str | None


def load_settings() -> Settings:
    load_dotenv()
    mode = os.getenv("DISCORD_MODE", "bot")
    if mode != "bot":
        raise ValueError(
            "Only DISCORD_MODE=bot is supported; Discord user-account automation is forbidden."
        )
    raw_id = os.getenv("TELEGRAM_API_ID")
    provider = os.getenv("LLM_PROVIDER", "stub").lower()
    key = os.getenv(f"{provider.upper()}_API_KEY")
    base = os.getenv("LLM_BASE_URL") or (
        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if provider == "ollama"
        else None
    )
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv(f"{provider.upper()}_MODEL")
        or ("qwen2.5:3b-instruct" if provider == "ollama" else "")
    )
    return Settings(
        os.getenv("NEO_ENV", "development"),
        int(os.getenv("MAX_TOOL_ROUNDS", "8")),
        _flag(os.getenv("ALLOW_EXTERNAL_WRITES")),
        mode,
        [
            item.strip()
            for item in os.getenv("DISCORD_ALLOWED_GUILD_IDS", "").split(",")
            if item.strip()
        ],
        int(raw_id) if raw_id else None,
        os.getenv("TELEGRAM_API_HASH"),
        Path(os.getenv("TELEGRAM_SESSION_PATH", ".neo-data/telegram")),
        os.getenv("NEO_OWNER_NAME", "Owner"),
        os.getenv("NEO_OWNER_TIMEZONE", "Asia/Calcutta"),
        os.getenv("NEO_OWNER_API_KEY"),
        int(os.getenv("NEO_MEMORY_TTL_DAYS", "90")),
        Path(os.getenv("NEO_DATABASE_PATH", ".neo-data/neo.sqlite3")),
        os.getenv("DATABASE_URL"),
        provider,
        model,
        base,
        key,
    )

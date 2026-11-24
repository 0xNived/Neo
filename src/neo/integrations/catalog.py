"""Built-in integration status without exposing credentials to the browser."""

from __future__ import annotations

from ..configuration.settings import Settings
from .contracts import ConnectionState, IntegrationStatus, IntegrationTransport


def builtin_statuses(settings: Settings) -> list[IntegrationStatus]:
    """Return setup state, not a claim that a remote account is connected."""

    discord_ready = bool(settings.discord_bot_token)
    telegram_ready = bool(settings.telegram_api_id and settings.telegram_api_hash)
    return [
        IntegrationStatus(
            "organizer",
            "Organizer",
            IntegrationTransport.NATIVE,
            ConnectionState.READY
            if settings.database_url
            else ConnectionState.NEEDS_CONFIGURATION,
            ("notes", "tasks", "links", "semantic retrieval"),
            "Uses PostgreSQL when configured.",
        ),
        IntegrationStatus(
            "discord_bot",
            "Discord bot",
            IntegrationTransport.NATIVE,
            ConnectionState.READY if discord_ready else ConnectionState.NEEDS_CONFIGURATION,
            ("server search", "approved bot messages"),
            "Official bot account only; never a user-token self-bot.",
        ),
        IntegrationStatus(
            "discord_oauth",
            "Discord sign-in / OAuth",
            IntegrationTransport.OAUTH,
            ConnectionState.DISABLED,
            ("identity", "approved OAuth scopes"),
            "Planned: account connection, not user-account automation.",
        ),
        IntegrationStatus(
            "telegram",
            "Telegram",
            IntegrationTransport.NATIVE,
            ConnectionState.READY if telegram_ready else ConnectionState.NEEDS_CONFIGURATION,
            ("authenticated account search",),
            "Requires API credentials and an interactive first sign-in.",
        ),
        IntegrationStatus(
            "browser",
            "Rendered web pages",
            IntegrationTransport.NATIVE,
            ConnectionState.READY
            if settings.browser_enabled
            else ConnectionState.NEEDS_CONFIGURATION,
            ("JavaScript-rendered public pages", "visible page extraction"),
            (
                "Uses an isolated Playwright browser; it does not sign in, submit forms, "
                "or see account-specific availability."
            ),
        ),
        IntegrationStatus(
            "vision",
            "Image understanding",
            IntegrationTransport.NATIVE,
            ConnectionState.DISABLED,
            ("image captioning", "OCR", "image-grounded retrieval"),
            (
                "Configuration is reserved, but the upload/import worker is not "
                "implemented yet. A vision-capable model will be required."
            ),
        ),
        IntegrationStatus(
            "mcp",
            "MCP servers",
            IntegrationTransport.MCP,
            ConnectionState.DISABLED,
            ("third-party tools",),
            "Each server is configured explicitly; unknown tools are approval-gated.",
        ),
    ]

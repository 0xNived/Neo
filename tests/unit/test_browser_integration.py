from types import SimpleNamespace

import pytest

from neo.domain.models import ToolContext
from neo.integrations.browser import BrowserService
from neo.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_disabled_browser_returns_setup_help_without_importing_playwright():
    registry = ToolRegistry()
    BrowserService(
        SimpleNamespace(
            browser_enabled=False,
            browser_headless=True,
            browser_timeout_seconds=20,
        )
    ).register(registry)

    result = await registry.tools["browser.inspect"].execute(
        {"url": "https://example.com"},
        ToolContext("owner", "session", "request"),
    )

    assert result["ok"] is False
    assert "NEO_BROWSER_ENABLED" in result["error"]


@pytest.mark.asyncio
async def test_browser_rejects_private_target_before_launching():
    registry = ToolRegistry()
    BrowserService(
        SimpleNamespace(
            browser_enabled=True,
            browser_headless=True,
            browser_timeout_seconds=20,
        )
    ).register(registry)

    result = await registry.tools["browser.inspect"].execute(
        {"url": "http://127.0.0.1:8000"},
        ToolContext("owner", "session", "request"),
    )

    assert result["ok"] is False
    assert "Private network" in result["error"]

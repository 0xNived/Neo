"""A bounded Playwright reader for JavaScript-rendered public pages."""

from __future__ import annotations

import asyncio
import os
import threading

from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext
from ..link_previews import public_http_url


class BrowserService:
    def __init__(self, settings) -> None:
        self.enabled = settings.browser_enabled
        self.headless = settings.browser_headless
        self.timeout_ms = settings.browser_timeout_seconds * 1000
        self._playwright_lock = threading.Lock()

    def register(self, registry) -> None:
        registry.add_profile(
            IntegrationProfile(
                "browser",
                (
                    "A bounded public-page browser is available for JavaScript-heavy "
                    "sites. Use browser.inspect only after normal web fetching is "
                    "insufficient. It uses an isolated profile with no owner login, "
                    "never submits forms, and may not reveal account-, pincode-, or "
                    "location-specific stock."
                ),
            )
        )

        async def inspect(data: dict, _context: ToolContext) -> dict:
            if not self.enabled:
                return {
                    "ok": False,
                    "error": "Browser rendering is disabled. Set NEO_BROWSER_ENABLED=true after installing Playwright.",
                }
            try:
                url = await public_http_url(str(data.get("url", "")))
            except ValueError as error:
                return {"ok": False, "error": str(error)}

            selector = str(data.get("selector") or "body").strip()[:240]
            if not selector:
                selector = "body"
            try:
                return await asyncio.to_thread(self._inspect_sync, url, selector)
            except ModuleNotFoundError:
                return {
                    "ok": False,
                    "error": "Playwright is not installed. Install Neo's browser extra and Chromium first.",
                }
            except (OSError, NotImplementedError) as error:
                return {"ok": False, "error": str(error)[:300]}

        registry.register(
            Tool(
                "browser.inspect",
                "Render a public JavaScript-heavy page in an isolated browser and extract visible text",
                "browser",
                Risk.READ,
                {
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string", "format": "uri"},
                        "selector": {
                            "type": "string",
                            "description": "Optional CSS selector; defaults to body.",
                        },
                    },
                },
                (
                    "Use only for a public page after web.fetch_url is incomplete "
                    "because JavaScript must render it. Read-only: do not use this "
                    "to log in, submit a form, purchase, or claim account-specific stock."
                ),
                inspect,
            )
        )

    def _inspect_sync(self, url: str, selector: str) -> dict:
        """Run Playwright outside Neo's PostgreSQL-compatible Selector loop.

        Windows' Selector event loop is needed by psycopg, while Playwright's
        async transport needs subprocess support. Its synchronous API in a
        worker thread cleanly isolates those incompatible requirements.
        """
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        previous_policy = asyncio.get_event_loop_policy()
        try:
            with self._playwright_lock:
                if os.name == "nt":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=self.headless)
                    context = browser.new_context()
                    page = context.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_timeout(750)
                        locator = page.locator(selector).first
                        locator.wait_for(state="attached", timeout=self.timeout_ms)
                        content = locator.inner_text()[:12_000]
                        return {
                            "ok": True,
                            "data": {
                                "url": page.url,
                                "title": page.title()[:240],
                                "selector": selector,
                                "content": content,
                                "profile": "isolated",
                                "note": (
                                    "Public rendered page only. Availability can still depend on a "
                                    "selected size, pincode, or signed-in account."
                                ),
                            },
                        }
                    finally:
                        context.close()
                        browser.close()
        except PlaywrightTimeoutError:
            return {"ok": False, "error": "The rendered page or requested element timed out."}
        except PlaywrightError as error:
            return {"ok": False, "error": str(error)[:300]}
        except NotImplementedError:
            return {"ok": False, "error": "The Windows browser worker could not start."}
        finally:
            if os.name == "nt":
                asyncio.set_event_loop_policy(previous_policy)

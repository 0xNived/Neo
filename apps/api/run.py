"""Windows-safe launcher for Neo's FastAPI gateway."""

from __future__ import annotations

import asyncio
import os

import uvicorn


def selector_loop_factory(use_subprocess: bool = False):
    """Uvicorn 0.53 defaults to Proactor on Windows; psycopg needs Selector."""
    return asyncio.SelectorEventLoop()


def main() -> None:
    # psycopg's async implementation is incompatible with Windows' default
    # Proactor loop. Set this before Uvicorn creates its server event loop.
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        "apps.api.main:app",
        host="127.0.0.1",
        port=int(os.getenv("NEO_PORT", "8000")),
        reload=os.getenv("NEO_RELOAD", "false").lower() == "true",
        loop="apps.api.run:selector_loop_factory",
    )


if __name__ == "__main__":
    main()

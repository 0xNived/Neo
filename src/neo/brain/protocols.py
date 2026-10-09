from typing import Any, Protocol

from ..domain.models import IntegrationProfile, Tool


class Brain(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[Tool],
        profiles: list[IntegrationProfile],
    ) -> dict[str, Any]: ...

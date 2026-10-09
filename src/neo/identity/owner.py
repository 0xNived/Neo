from dataclasses import dataclass


@dataclass(frozen=True)
class OwnerProfile:
    name: str
    api_key: str | None
    timezone: str

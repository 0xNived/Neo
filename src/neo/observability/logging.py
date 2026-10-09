import json
import logging
import re

_secret = re.compile(
    r"token|secret|password|authorization|cookie|api[_-]?key", re.IGNORECASE
)


def event(name: str, **fields: object) -> None:
    safe = {
        key: ("[REDACTED]" if _secret.search(key) else value)
        for key, value in fields.items()
    }
    logging.getLogger("neo").info(json.dumps({"event": name, **safe}, default=str))

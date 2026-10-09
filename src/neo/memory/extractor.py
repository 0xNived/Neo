import re
from datetime import UTC, datetime


def memories_from_message(text: str) -> list[tuple[str, str, float]]:
    found = []
    name = re.search(
        r"\bmy name is\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2}?)(?=\s+and\b|\s+i\b|[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if name:
        found.append(
            ("identity", f"The owner's name is {name.group(1).strip()}.", 0.98)
        )
    conditional_preference = re.search(
        r"\b(?:i\s+would\s+prefer|i'd\s+prefer)\s+(.{2,140}?)(?:[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if conditional_preference:
        value = re.sub(r"\s+too\s*$", "", conditional_preference.group(1).strip(), flags=re.IGNORECASE)
        found.append(("preference", f"The owner prefers {value}.", 0.88))
    preference = re.search(
        r"\bi (love|like|prefer|want|always want|hate|dislike|can't stand)\s+(.{2,140}?)(?:[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if preference and not conditional_preference:
        found.append(
            (
                "preference",
                f"The owner {preference.group(1).lower()} {preference.group(2).strip()}.",
                0.85,
            )
        )
    standing = re.search(
        r"\b(always|never|don't|do not|stop|less|more|shorter|longer)\b"
        r"\s+(.{3,120}?)(?:[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if standing and not preference:
        found.append(
            (
                "preference",
                f"Standing preference: owner says {standing.group(0).strip()}.",
                0.8,
            )
        )
    correction = re.search(
        r"\b(from now on|in the future|going forward|next time)\s*,?\s+(.{3,140}?)(?:[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if correction:
        found.append(
            (
                "preference",
                f"Owner asked to change behavior: {correction.group(2).strip()}.",
                0.9,
            )
        )
    birthday = re.search(
        r"\b(?:my\s+)?(?:birthday|bday)(?:\s+is|\s*[:=-])?\s+"
        r"([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)"
        r"|\b(?:i\s+was\s+)?born\s+on\s+"
        r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+\d{4})?)",
        text,
        re.IGNORECASE,
    )
    if birthday:
        raw = re.sub(
            r"(st|nd|rd|th)\b",
            "",
            birthday.group(1) or birthday.group(2),
            flags=re.IGNORECASE,
        )
        for pattern in (
            "%B %d, %Y",
            "%B %d %Y",
            "%B %d",
            "%d %B %Y",
            "%d %B",
        ):
            try:
                parsed = datetime.strptime(raw, pattern).replace(tzinfo=UTC)
                found.append(
                    (
                        "birthday",
                        f"The owner's birthday is {parsed:%m-%d}.",
                        0.99,
                    )
                )
                break
            except ValueError:
                continue
    return found

"""Validation for saved context references.

References are metadata, not capabilities: storing a local path never grants
Neo permission to read that file, and a remote URL is fetched only by an
explicit enrichment/import feature.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from urllib.parse import urlparse

REFERENCE_TYPES = {"web_link", "image", "document", "local_path"}


def normalize_references(references: object) -> list[dict[str, str]]:
    if references is None:
        return []
    if not isinstance(references, list):
        raise TypeError("references must be a list")
    if len(references) > 20:
        raise ValueError("A saved item can have at most 20 references")
    normalized: list[dict[str, str]] = []
    for reference in references:
        if not isinstance(reference, dict):
            raise TypeError("Each reference must be an object")
        reference_type = str(reference.get("type") or "").strip().lower()
        value = str(reference.get("value") or "").strip()
        label = str(reference.get("label") or "").strip()
        note = str(reference.get("note") or "").strip()
        if reference_type not in REFERENCE_TYPES:
            raise ValueError(f"Unsupported reference type: {reference_type}")
        if not value:
            raise ValueError("Each reference needs a value")
        if reference_type == "local_path":
            is_windows_path = PureWindowsPath(value).is_absolute()
            if not is_windows_path and not Path(value).is_absolute():
                raise ValueError("local_path references must use an absolute path")
        else:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("web, image, and document references need an http(s) URL")
        normalized.append(
            {
                "type": reference_type,
                "value": value[:2048],
                "label": label[:160],
                "note": note[:1000],
            }
        )
    return normalized

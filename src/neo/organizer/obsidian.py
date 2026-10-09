"""Opt-in Markdown export for a local Obsidian vault."""
from __future__ import annotations

import re
from pathlib import Path


def _safe(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "-", value).strip(" .")[:100] or "Untitled"


async def export_vault(store, user_id: str, vault_path: str) -> int:
    root = Path(vault_path).expanduser().resolve() / "Neo"
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    for group in await store.groups(user_id):
        folder = root / _safe(group["name"])
        folder.mkdir(exist_ok=True)
        for item in await store.items(user_id, group["id"]):
            meta = item.get("metadata", {})
            frontmatter = {"neo_id": item["id"], "type": item["kind"], "saved": item["created_at"], "tags": meta.get("tags", [])}
            lines = ["---", *[f"{key}: {value}" for key, value in frontmatter.items()], "---", "", f"# {item['title']}", "", item.get("content", "")]
            if item.get("url"):
                lines.extend(["", f"Source: {item['url']}"])
            (folder / f"{_safe(item['title'])}.md").write_text("\n".join(lines), encoding="utf-8")
            count += 1
    return count

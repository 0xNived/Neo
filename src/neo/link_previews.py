"""Safe Open Graph metadata lookup for chat link previews.

This fetches only public HTML pages.  Media bytes are never proxied through
Neo; the browser loads an image or video directly from the public source.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

_MAX_HTML_BYTES = 750_000
_MAX_REDIRECTS = 3


def _is_public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


async def public_http_url(value: str) -> str:
    """Validate a public http(s) address before Neo makes a server-side request."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http(s) links can be previewed.")
    if parsed.username or parsed.password or parsed.hostname.lower() in {
        "localhost",
        "localhost.localdomain",
    }:
        raise ValueError("Local links cannot be previewed.")
    try:
        literal_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not _is_public_ip(str(literal_ip)):
            raise ValueError("Private network links cannot be previewed.")
        return parsed.geturl()

    try:
        addresses = await asyncio.get_running_loop().run_in_executor(
            None, socket.getaddrinfo, parsed.hostname, parsed.port or 443
        )
        if not addresses or not all(_is_public_ip(row[4][0]) for row in addresses):
            raise ValueError("Private network links cannot be previewed.")
    except (OSError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("That host could not be resolved for a preview.") from error
    return parsed.geturl()


def _clean(value: str, limit: int) -> str:
    return " ".join(unescape(value).split())[:limit]


class _OpenGraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self._title_parts: list[str] = []
        self._inside_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self._inside_title = True
        if tag.lower() != "meta":
            return
        key = (attributes.get("property") or attributes.get("name") or "").lower()
        value = attributes.get("content", "")
        if key and value and key not in self.meta:
            self.meta[key] = value

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(self._title_parts)


async def _safe_related_url(base_url: str, value: str) -> str | None:
    if not value:
        return None
    try:
        return await public_http_url(urljoin(base_url, value))
    except ValueError:
        return None


async def preview_url(value: str) -> dict:
    """Return a small, safe preview payload suitable for the chat UI."""
    try:
        current = await public_http_url(value)
    except ValueError as error:
        return {"ok": False, "error": str(error)}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0),
            follow_redirects=False,
            headers={"User-Agent": "NeoLinkPreview/1.0"},
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                async with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            return {"ok": False, "error": "The preview link redirected without a destination."}
                        current = await public_http_url(urljoin(current, location))
                        continue
                    if response.status_code >= 400:
                        return {"ok": False, "error": f"That site returned HTTP {response.status_code}."}
                    if "html" not in response.headers.get("content-type", "").lower():
                        return {"ok": False, "error": "That link is not an HTML page."}
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) >= _MAX_HTML_BYTES:
                            break
                parser = _OpenGraphParser()
                parser.feed(body.decode("utf-8", errors="replace"))
                parser.close()
                title = _clean(
                    parser.meta.get("og:title")
                    or parser.meta.get("twitter:title")
                    or parser.title
                    or urlparse(current).hostname
                    or current,
                    180,
                )
                description = _clean(
                    parser.meta.get("og:description")
                    or parser.meta.get("twitter:description")
                    or parser.meta.get("description", ""),
                    300,
                )
                image_url = await _safe_related_url(
                    current,
                    parser.meta.get("og:image") or parser.meta.get("twitter:image", ""),
                )
                video_url = await _safe_related_url(
                    current,
                    parser.meta.get("og:video") or parser.meta.get("twitter:player:stream", ""),
                )
                return {
                    "ok": True,
                    "url": current,
                    "host": urlparse(current).hostname or "",
                    "title": title,
                    "description": description,
                    "image_url": image_url,
                    "video_url": video_url,
                }
    except (httpx.HTTPError, ValueError) as error:
        return {"ok": False, "error": str(error)[:220]}
    return {"ok": False, "error": "The preview followed too many redirects."}

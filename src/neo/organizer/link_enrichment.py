from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from urllib.parse import urlparse

import httpx


async def public_web_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.hostname in {"localhost", "localhost.localdomain"}:
        return False
    try:
        addresses = await __import__("asyncio").get_running_loop().run_in_executor(None, socket.getaddrinfo, parsed.hostname, None)
        return all(not ipaddress.ip_address(row[4][0]).is_private and not ipaddress.ip_address(row[4][0]).is_loopback for row in addresses)
    except (OSError, ValueError):
        return False


def page_context(html: str, url: str) -> dict:
    def meta(name: str) -> str:
        match = re.search(rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)', html, re.I)
        return unescape(match.group(1)).strip() if match else ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    description = meta("og:description") or meta("description")
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()
    context = text[:6000]
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", f"{title} {description} {context}".lower())
    stop = {"this","that","with","from","have","your","about","would","there","their","which","will","more","also","into","https","http","html"}
    keywords = list(dict.fromkeys(word for word in words if word not in stop))[:24]
    return {"title": title, "description": description[:700], "context": context, "keywords": keywords, "source_url": url}


async def fetch_page_context(url: str) -> dict:
    if not await public_web_url(url):
        return {"status": "blocked", "reason": "Only public http(s) links can be enriched."}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8, headers={"User-Agent": "NeoLinkIndexer/1.0"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", ""):
                return {"status": "unsupported", "reason": "This link is not an HTML page."}
            return {"status": "ready", **page_context(response.text[:700_000], str(response.url))}
    except (httpx.HTTPError, ValueError) as error:
        return {"status": "failed", "reason": str(error)[:180]}

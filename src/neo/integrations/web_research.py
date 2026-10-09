from __future__ import annotations

import asyncio
import ipaddress
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ..domain.models import IntegrationProfile, Risk, Tool, ToolContext


class _SearchResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._href = ""
        self._title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        data = dict(attrs)
        if tag == "a" and "result__a" in (data.get("class") or ""):
            self._href, self._title = data.get("href") or "", []

    def handle_data(self, data: str):
        if self._href:
            self._title.append(data)

    def handle_endtag(self, tag: str):
        if tag == "a" and self._href:
            target = parse_qs(urlparse(self._href).query).get("uddg", [self._href])[0]
            title = " ".join(self._title).strip()
            if title and target.startswith(("http://", "https://")):
                self.results.append({"title": title, "url": unquote(target)})
            self._href, self._title = "", []


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript"}:
            self._ignored = max(0, self._ignored - 1)

    def handle_data(self, data: str):
        if not self._ignored and data.strip():
            self.parts.append(data.strip())


def _news_rss_results(xml_text: str) -> list[dict[str, str]]:
    """RSS fallback for modern search-result markup changes."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    results = []
    for item in root.findall("./channel/item")[:5]:
        title, url = item.findtext("title", "").strip(), item.findtext("link", "").strip()
        if title and url.startswith(("https://", "http://")):
            results.append({"title": title, "url": url})
    return results


def _public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http(s) URLs can be fetched")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local URLs are not allowed")
    try:
        if ipaddress.ip_address(parsed.hostname).is_private:
            raise ValueError("Private network URLs are not allowed")
    except ValueError as error:
        if "not allowed" in str(error):
            raise
    return value


class WebResearchService:
    def register(self, registry) -> None:
        registry.add_profile(
            IntegrationProfile(
                "web_research",
                "Web research is available. Search first, cite source URLs, and fetch a supplied public URL only when needed.",
            )
        )

        async def search(data: dict, context: ToolContext) -> dict:
            queries = [str(item).strip() for item in data.get("queries", [])][:4]
            if not queries:
                return {"ok": False, "error": "At least one search query is required"}

            async def one(query: str) -> dict:
                async with httpx.AsyncClient(
                    timeout=15, follow_redirects=True
                ) as client:
                    response = await client.get(
                        "https://html.duckduckgo.com/html/", params={"q": query}
                    )
                    response.raise_for_status()
                    parser = _SearchResults()
                    parser.feed(response.text)
                    results = parser.results[:5]
                    if not results:
                        response = await client.get(
                            "https://news.google.com/rss/search",
                            params={"q": f"{query} when:1d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
                            headers={"User-Agent": "NeoResearch/0.1"},
                        )
                        response.raise_for_status()
                        results = _news_rss_results(response.text)
                return {"query": query, "results": results}

            try:
                return {
                    "ok": True,
                    "data": await asyncio.gather(*(one(q) for q in queries)),
                }
            except httpx.HTTPError as error:
                return {"ok": False, "error": f"Search provider unavailable: {error}"}

        async def fetch_url(data: dict, context: ToolContext) -> dict:
            try:
                url = _public_url(str(data.get("url", "")))
                async with httpx.AsyncClient(
                    timeout=20, follow_redirects=True
                ) as client:
                    response = await client.get(
                        url, headers={"User-Agent": "NeoResearch/0.1"}
                    )
                    response.raise_for_status()
                parser = _TextExtractor()
                parser.feed(response.text)
                return {
                    "ok": True,
                    "data": {
                        "url": str(response.url),
                        "content": " ".join(parser.parts)[:12000],
                    },
                }
            except (ValueError, httpx.HTTPError) as error:
                return {"ok": False, "error": str(error)}

        registry.register(
            Tool(
                "web.search",
                "Search the public web with one to four focused queries",
                "web_research",
                Risk.READ,
                {
                    "type": "object",
                    "required": ["queries"],
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}}
                    },
                },
                "Use for current information or broad research.",
                search,
            )
        )
        registry.register(
            Tool(
                "web.fetch_url",
                "Fetch readable text from a supplied public web page",
                "web_research",
                Risk.READ,
                {
                    "type": "object",
                    "required": ["url"],
                    "properties": {"url": {"type": "string", "format": "uri"}},
                },
                "Never fetch local or private network URLs.",
                fetch_url,
            )
        )

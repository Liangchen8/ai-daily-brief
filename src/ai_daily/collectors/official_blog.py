from __future__ import annotations

import hashlib
import asyncio
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from .base import BaseCollector


class _JsonScriptParser(HTMLParser):
    """只读取页面内公开 JSON/JSON-LD，不依赖页面 CSS 类名或选择器。"""

    def __init__(self):
        super().__init__()
        self._capture = False
        self._parts: list[str] = []
        self.payloads: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        if attributes.get("type") in {"application/ld+json", "application/json"} or attributes.get("id") == "__NEXT_DATA__":
            self._capture = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self.payloads.append("".join(self._parts))
            self._capture = False


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class OfficialBlogCollector(BaseCollector):
    name = "official_blog"

    def _extract(self, html: str, source) -> list[dict[str, Any]]:
        parser = _JsonScriptParser()
        parser.feed(html)
        articles: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in parser.payloads:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for node in _walk(payload):
                title = node.get("headline") or node.get("title") or node.get("name")
                published = _date(node.get("datePublished") or node.get("publishedAt") or node.get("published_at"))
                raw_url = node.get("url") or node.get("mainEntityOfPage") or node.get("canonicalUrl")
                if isinstance(raw_url, dict):
                    raw_url = raw_url.get("@id") or raw_url.get("url")
                if not isinstance(title, str) or not isinstance(raw_url, str) or not published:
                    continue
                url = urljoin(source.url, raw_url)
                key = (title.strip(), url)
                if key in seen:
                    continue
                seen.add(key)
                articles.append({"title": title.strip(), "url": url, "published": published, "summary": str(node.get("description") or node.get("summary") or "")})
        return articles

    async def _one(self, client: httpx.AsyncClient, source) -> list:
        try:
            response = await self.request(client, source.url)
            articles = self._extract(response.text, source)
            result = []
            for article in articles:
                if not self.recent(article["published"], 36):
                    continue
                item_id = hashlib.sha1(f"{source.name}:{article['url']}".encode()).hexdigest()[:20]
                result.append(self.item(
                    item_id=item_id, type="news", title=article["title"], content=article["summary"], url=article["url"],
                    source=source.name, source_type="official_blog", published_at=article["published"],
                    source_score=source.authority_weight, raw_metadata={"official_page": source.url},
                ))
            self.record_health(
                "success" if result else ("ok_zero_recent_items" if articles else "parse_failed"),
                source=source.name, requested_url=source.url, fetched_items=len(articles), recent_items=len(result),
            )
            return result
        except httpx.HTTPStatusError as exc:
            self.record_health("http_failed", source=source.name, requested_url=source.url, status_code=exc.response.status_code)
            return []
        except Exception as exc:
            self.record_health("parse_failed", source=source.name, requested_url=source.url, error_type=type(exc).__name__)
            return []

    async def collect(self) -> list:
        sources = [source for source in self.config.sources if source.enabled and source.type == "official_blog"]
        if not sources:
            return []
        async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "AI-Daily-Brief/0.1"}) as client:
            batches = await asyncio.gather(*(self._one(client, source) for source in sources))
        return [item for batch in batches for item in batch]

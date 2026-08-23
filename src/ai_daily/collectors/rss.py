from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from .base import BaseCollector


def _entry_datetime(entry) -> datetime:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                result = parsedate_to_datetime(value)
                return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, IndexError):
                pass
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


class RSSCollector(BaseCollector):
    name = "rss"

    async def _one(self, client: httpx.AsyncClient, source) -> list:
        try:
            response = await self.request(client, source.url)
            parsed = feedparser.parse(response.content)
            if getattr(parsed, "bozo", False) and not parsed.entries:
                self.record_health(
                    "parse_failed", source=source.name, requested_url=source.url,
                    error_type=type(getattr(parsed, "bozo_exception", None)).__name__,
                )
                return []
            result = []
            for entry in parsed.entries:
                published = _entry_datetime(entry)
                if not self.recent(published, 36):
                    continue
                url = str(entry.get("link", "")).strip()
                if not url:
                    continue
                title = str(entry.get("title", "")).strip()
                content = str(entry.get("summary", entry.get("description", "")))
                raw_id = str(entry.get("id", url))
                item_id = hashlib.sha1(f"{source.name}:{raw_id}".encode()).hexdigest()[:20]
                result.append(self.item(
                    item_id=item_id,
                    type="news",
                    title=title,
                    content=content,
                    url=url,
                    source=source.name,
                    source_type="rss",
                    published_at=published,
                    author=str(entry.get("author", "")),
                    source_score=source.authority_weight,
                    raw_metadata={"feed_url": source.url},
                ))
            self.record_health(
                "success" if result else "ok_zero_recent_items",
                source=source.name,
                requested_url=source.url,
                fetched_items=len(parsed.entries),
                recent_items=len(result),
            )
            return result
        except httpx.HTTPStatusError as exc:
            self.record_health(
                "http_failed", source=source.name, requested_url=source.url,
                status_code=exc.response.status_code,
            )
            return []
        except Exception as exc:
            self.record_health(
                "parse_failed", source=source.name, requested_url=source.url,
                error_type=type(exc).__name__,
            )
            return []

    async def collect(self) -> list:
        sources = [source for source in self.config.sources if source.enabled and source.type == "rss"]
        async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "AI-Daily-Brief/0.1"}) as client:
            batches = await asyncio.gather(*(self._one(client, source) for source in sources))
        return [item for batch in batches for item in batch]

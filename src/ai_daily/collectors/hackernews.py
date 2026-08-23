from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

import httpx

from .base import BaseCollector


class HackerNewsCollector(BaseCollector):
    name = "hackernews"

    def _is_ai(self, title: str) -> bool:
        text = title.lower()
        terms = [term.lower() for term in self.config.high_topics + self.config.medium_topics]
        return any(term in text for term in terms) or any(x in text for x in ("llm", "gpt", "openai", "anthropic", "ai "))

    async def collect(self) -> list:
        urls = [
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            "https://hacker-news.firebaseio.com/v0/beststories.json",
        ]
        try:
            async with httpx.AsyncClient() as client:
                ids = set()
                for url in urls:
                    response = await self.request(client, url)
                    ids.update(response.json()[:100])
                async def get_story(story_id):
                    response = await self.request(client, f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                    return response.json()
                stories = await asyncio.gather(*(get_story(story_id) for story_id in ids), return_exceptions=True)
            result = []
            for story in stories:
                if not isinstance(story, dict) or story.get("type") != "story" or not story.get("url"):
                    continue
                title = str(story.get("title", ""))
                if not self._is_ai(title):
                    continue
                published = datetime.fromtimestamp(int(story.get("time", 0)), tz=timezone.utc)
                if not self.recent(published, 36):
                    continue
                result.append(self.item(
                    item_id=f"hn-{story.get('id')}", type="news", title=title,
                    content=str(story.get("text", "")), url=story["url"], source="Hacker News",
                    source_type="hackernews", published_at=published, author=str(story.get("by", "")),
                    likes=int(story.get("score", 0)), comments=int(story.get("descendants", 0)),
                    source_score=65, raw_metadata={"hn_id": story.get("id"), "discussion_url": f"https://news.ycombinator.com/item?id={story.get('id')}"},
                ))
            self.record_health("success" if result else "ok_zero_recent_items", source="Hacker News", fetched_items=len(stories), recent_items=len(result))
            return result
        except Exception as exc:
            self.record_health("parse_failed", source="Hacker News", error_type=type(exc).__name__)
            return []

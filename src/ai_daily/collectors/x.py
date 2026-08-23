from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import BaseCollector


class XCollector(BaseCollector):
    name = "x"

    async def collect(self) -> list:
        token = self.config.env("X_BEARER_TOKEN")
        if not token:
            self.logger.info("collector=%s disabled reason=%s", self.name, "missing_X_BEARER_TOKEN")
            self.record_health("disabled", source="X", reason="missing_token")
            return []
        headers = {"Authorization": f"Bearer {token}"}
        result = []
        try:
            async with httpx.AsyncClient(headers=headers) as client:
                for person in [p for p in self.config.people if p.enabled and p.platforms.get("x")]:
                    lookup = await self.request(client, "https://api.x.com/2/users/by/username/" + person.platforms["x"])
                    user_id = lookup.json().get("data", {}).get("id")
                    if not user_id:
                        continue
                    response = await self.request(client, f"https://api.x.com/2/users/{user_id}/tweets", params={"max_results": 50, "tweet.fields": "created_at,public_metrics,text"})
                    for tweet in response.json().get("data", []):
                        created = str(tweet.get("created_at", "")).replace("Z", "+00:00")
                        published = datetime.fromisoformat(created).astimezone(timezone.utc)
                        if not self.recent(published, 48):
                            continue
                        metrics = tweet.get("public_metrics", {})
                        result.append(self.item(
                            item_id=f"x-{tweet.get('id')}", type="social", title=tweet.get("text", "")[:120], content=tweet.get("text", ""),
                            url=f"https://x.com/{person.platforms['x']}/status/{tweet.get('id')}", source=person.name, source_type="x",
                            published_at=published, author=person.name, likes=metrics.get("like_count", 0), comments=metrics.get("reply_count", 0), reposts=metrics.get("retweet_count", 0), source_score=person.weight,
                        ))
            self.record_health("success" if result else "ok_zero_recent_items", source="X", fetched_items=len(result), recent_items=len(result))
            return result
        except Exception as exc:
            self.record_health("parse_failed", source="X", error_type=type(exc).__name__)
            return result

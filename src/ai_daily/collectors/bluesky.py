from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import BaseCollector


class BlueskyCollector(BaseCollector):
    name = "bluesky"

    async def _person(self, client: httpx.AsyncClient, person) -> list:
        handle = person.platforms.get("bluesky")
        if not handle:
            self.record_health("account_not_configured", source=person.name)
            return []
        try:
            response = await self.request(client, "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed", params={"actor": handle, "limit": 50})
            result = []
            for row in response.json().get("feed", []):
                post = row.get("post", {})
                record = post.get("record", {})
                created = str(record.get("createdAt", "")).replace("Z", "+00:00")
                if not created:
                    continue
                published = datetime.fromisoformat(created).astimezone(timezone.utc)
                if not self.recent(published, 48):
                    continue
                uri = str(post.get("uri", ""))
                rkey = uri.rsplit("/", 1)[-1]
                url = f"https://bsky.app/profile/{handle}/post/{rkey}"
                text = str(record.get("text", ""))
                result.append(self.item(
                    item_id=f"bsky-{post.get('cid', rkey)}", type="social", title=text[:120], content=text,
                    url=url, source=person.name, source_type="bluesky", published_at=published, author=person.name,
                    likes=int(post.get("likeCount", 0)), comments=int(post.get("replyCount", 0)), reposts=int(post.get("repostCount", 0)),
                    source_score=person.weight, raw_metadata={"handle": handle, "cid": post.get("cid")},
                ))
            self.record_health(
                "success" if result else "ok_zero_recent_items", source=person.name,
                requested_url="https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                handle=handle, fetched_items=len(response.json().get("feed", [])), recent_items=len(result),
            )
            return result
        except httpx.HTTPStatusError as exc:
            self.record_health(
                "http_failed", source=person.name,
                requested_url="https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                handle=handle, status_code=exc.response.status_code,
            )
            return []
        except Exception as exc:
            self.record_health("parse_failed", source=person.name, handle=handle, error_type=type(exc).__name__)
            return []

    async def collect(self) -> list:
        enabled_people = [person for person in self.config.people if person.enabled]
        people = [person for person in enabled_people if person.platforms.get("bluesky")]
        for person in enabled_people:
            if not person.platforms.get("bluesky"):
                self.record_health("account_not_configured", source=person.name)
        if not people:
            return []
        async with httpx.AsyncClient() as client:
            import asyncio
            batches = await asyncio.gather(*(self._person(client, person) for person in people))
        return [item for batch in batches for item in batch]

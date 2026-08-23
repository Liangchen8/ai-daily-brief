from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from .base import BaseCollector


class ArxivCollector(BaseCollector):
    name = "arxiv"
    categories = ("cs.AI", "cs.LG", "cs.CL", "stat.ML")

    def _is_relevant(self, text: str) -> bool:
        lowered = text.lower()
        return any(term.lower() in lowered for term in self.config.high_topics + self.config.medium_topics)

    async def collect(self) -> list:
        query = "+OR+".join(f"cat:{category}" for category in self.categories)
        url = f"https://export.arxiv.org/api/query?search_query={query}&start=0&max_results=100&sortBy=submittedDate&sortOrder=descending"
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        configured_max = int(self.config.env("ARXIV_LOOKBACK_HOURS", "168") or 168)
        windows = tuple(window for window in (48, 96, 168) if window <= configured_max) or (48,)
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "AI-Daily-Brief/0.1 (research digest; contact=maintainer)"}) as client:
                response = await self.request(client, url)
            root = ET.fromstring(response.content)
            result = []
            for entry in root.findall("atom:entry", ns):
                title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
                abstract = " ".join((entry.findtext("atom:summary", "", ns) or "").split())
                published_text = entry.findtext("atom:published", "", ns).replace("Z", "+00:00")
                published = datetime.fromisoformat(published_text).astimezone(timezone.utc)
                if not self.recent(published, windows[-1]):
                    continue
                paper_url = entry.findtext("atom:id", "", ns)
                arxiv_id = paper_url.rstrip("/").split("/")[-1]
                authors = [node.findtext("atom:name", "", ns) for node in entry.findall("atom:author", ns)]
                result.append(self.item(
                    item_id=f"arxiv-{hashlib.sha1(arxiv_id.encode()).hexdigest()[:16]}", type="paper",
                    title=title, content=abstract, url=paper_url, source="arXiv", source_type="arxiv",
                    published_at=published, author=", ".join(filter(None, authors)), source_score=90,
                    raw_metadata={"arxiv_id": arxiv_id, "categories": [x.get("term") or x.text for x in entry.findall("atom:category", ns)]},
                ))
            result, lookback_hours, reason = self.adaptive_paper_window(result, windows=windows)
            self.record_health(
                "success" if result else "ok_zero_recent_items", source="arXiv", requested_url=url,
                fetched_items=len(root.findall("atom:entry", ns)), recent_items=len(result), lookback_hours=lookback_hours,
                reason=reason,
            )
            self.logger.info("collector=%s arxiv_lookback_used=%s reason=%s", self.name, lookback_hours, reason)
            return result
        except httpx.HTTPStatusError as exc:
            self.record_health("http_failed", source="arXiv", requested_url=url, status_code=exc.response.status_code)
            return []
        except ET.ParseError as exc:
            self.record_health("parse_failed", source="arXiv", requested_url=url, error_type=type(exc).__name__)
            return []
        except Exception as exc:
            self.record_health("parse_failed", source="arXiv", requested_url=url, error_type=type(exc).__name__)
            return []

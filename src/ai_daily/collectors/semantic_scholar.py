from __future__ import annotations

import logging

import httpx

from .base import BaseCollector


class SemanticScholarCollector(BaseCollector):
    name = "semantic_scholar"

    async def collect(self) -> list:
        return []

    async def enrich(self, items: list) -> list:
        api_key = self.config.env("SEMANTIC_SCHOLAR_API_KEY")
        if not api_key or not items:
            self.logger.info("collector=%s skipped reason=%s", self.name, "missing_optional_key")
            self.record_health("disabled_missing_optional_key" if not api_key else "ok_zero_recent_items", source="Semantic Scholar")
            return items
        headers = {"x-api-key": api_key}
        async with httpx.AsyncClient(headers=headers) as client:
            for item in items:
                paper_id = item.raw_metadata.get("arxiv_id") or item.raw_metadata.get("paper_id")
                if not paper_id:
                    continue
                try:
                    response = await self.request(client, f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{paper_id}", params={"fields": "citationCount,influentialCitationCount,venue,year,authors"})
                    item.raw_metadata["semantic_scholar"] = response.json()
                except Exception as exc:
                    self.logger.warning("collector=%s item=%s failed error_type=%s", self.name, item.id, type(exc).__name__)
        self.record_health("success", source="Semantic Scholar", fetched_items=len(items), recent_items=len(items))
        return items

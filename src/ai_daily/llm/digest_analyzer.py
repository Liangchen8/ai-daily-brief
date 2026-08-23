from __future__ import annotations

import logging

from ..models import ContentItem, DigestResult, EventCluster
from .router import ModelRouter


class DigestAnalyzer:
    def __init__(self, router: ModelRouter, logger: logging.Logger | None = None):
        self.router = router
        self.logger = logger or logging.getLogger("ai_daily")

    async def analyze(self, news: list[EventCluster], papers: list[ContentItem], social: list[ContentItem]) -> DigestResult | None:
        prompt = f"""从给定已入选内容中生成日报结构选择。只可返回已有 ID。返回 JSON：top_news_ids、top_paper_ids、top_social_ids、conflicts（没有则空数组）、watchlist（最多三条）。新闻={[(x.id,x.title) for x in news]} 论文={[(x.id,x.title) for x in papers]} 社交={[(x.id,x.title) for x in social]}"""
        try:
            return await self.router.generate_structured("digest", prompt, DigestResult)
        except Exception as exc:
            self.logger.warning("task_type=digest skipped error_type=%s", type(exc).__name__)
            return None


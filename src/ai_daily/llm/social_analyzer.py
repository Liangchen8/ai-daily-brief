from __future__ import annotations

import logging

from ..models import ContentItem, SocialAnalysis
from .router import ModelRouter


class SocialAnalyzer:
    def __init__(self, router: ModelRouter, logger: logging.Logger | None = None):
        self.router = router
        self.logger = logger or logging.getLogger("ai_daily")

    async def analyze(self, item: ContentItem) -> SocialAnalysis | None:
        prompt = f"""分析真实社交媒体帖子，明确区分事实、作者观点和模型分析。返回 JSON：item_id、author、original_view、core_argument、context、why_it_matters、fact_or_opinion、source_url。不得补写原帖没有的事实。ID={item.id}\n作者={item.author}\n原文={item.content[:4000]}\n原帖链接={item.url}"""
        try:
            result = await self.router.generate_structured("social_analysis", prompt, SocialAnalysis)
            result.item_id = item.id
            result.author = item.author
            result.source_url = str(item.url)
            return result
        except Exception as exc:
            self.logger.warning("task_type=social_analysis item=%s skipped error_type=%s", item.id, type(exc).__name__)
            return None


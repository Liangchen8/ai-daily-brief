from __future__ import annotations

import logging

from ..models import EventCluster, NewsAnalysis
from .router import ModelRouter


class NewsAnalyzer:
    def __init__(self, router: ModelRouter, logger: logging.Logger | None = None):
        self.router = router
        self.logger = logger or logging.getLogger("ai_daily")

    async def analyze(self, cluster: EventCluster) -> NewsAnalysis | None:
        allowed_urls = cluster.urls
        prompt = f"""分析以下真实新闻事件，严格区分事实和分析。只能引用给定 URL。返回 JSON，字段为 cluster_id、what_happened、why_it_matters、key_points、product_implication、confidence、source_urls。\nkey_points 必须是纯字符串数组，例如：{{"key_points":["第一条关键点","第二条关键点"]}}；禁止输出对象数组，例如 [{{"type":"fact","detail":"..."}}]。\nsource_urls 必须是输入中原样出现的纯 URL 字符串数组，例如：{{"source_urls":["https://example.com/news"]}}；禁止 Markdown 链接、HTML 链接、重写 URL 或任何非 URL 文本。cluster_id={cluster.id}\n输入：{[(item.title, item.content[:1000], str(item.url)) for item in cluster.items]}"""
        try:
            result = await self.router.generate_structured("news_analysis", prompt, NewsAnalysis)
            result.cluster_id = cluster.id
            result.source_urls = [url for url in result.source_urls if url in allowed_urls] or allowed_urls
            return result
        except Exception as exc:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.exception("task_type=news_analysis cluster=%s skipped error_type=%s", cluster.id, type(exc).__name__)
            else:
                self.logger.warning("task_type=news_analysis cluster=%s skipped error_type=%s", cluster.id, type(exc).__name__)
            return None

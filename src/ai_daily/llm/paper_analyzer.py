from __future__ import annotations

import logging

from ..models import ContentItem, PaperAnalysis
from .router import ModelRouter


class PaperAnalyzer:
    def __init__(self, router: ModelRouter, logger: logging.Logger | None = None):
        self.router = router
        self.logger = logger or logging.getLogger("ai_daily")

    async def analyze(self, item: ContentItem) -> PaperAnalysis | None:
        url = str(item.url)
        github = item.raw_metadata.get("github_url")
        prompt = f"""面向 AI 产品经理分析论文。回答过去方法、问题、核心创新、方法、实验是否支持结论、限制和 Agent/RAG/MCP/Skills/Coding Agent 产品价值。返回 JSON 字段：item_id、problem、previous_method、core_idea、innovation、method、experiment_result、limitations、product_implication、recommended_to_read、source_url、github_url。只能使用给定链接。ID={item.id}\n标题={item.title}\n摘要={item.content[:6000]}\n论文链接={url}\nGitHub候选={github}"""
        try:
            result = await self.router.generate_structured("paper_analysis", prompt, PaperAnalysis)
            result.item_id = item.id
            result.source_url = url
            result.github_url = github if github else None
            return result
        except Exception as exc:
            self.logger.warning("task_type=paper_analysis item=%s skipped error_type=%s", item.id, type(exc).__name__)
            return None


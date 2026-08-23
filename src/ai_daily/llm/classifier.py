from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..models import ClassificationResult, ContentItem
from .router import ModelRouter


class BatchClassification(BaseModel):
    results: list[ClassificationResult] = Field(default_factory=list)


class Classifier:
    def __init__(self, router: ModelRouter, logger: logging.Logger | None = None):
        self.router = router
        self.logger = logger or logging.getLogger("ai_daily")

    async def classify(self, items: list[ContentItem]) -> list[ClassificationResult]:
        if not items:
            return []
        lines = [f"ID={item.id}\n标题={item.title}\n内容={item.content[:1200]}" for item in items]
        prompt = """你是 AI 行业信息初筛器。只根据输入内容判断是否值得进入中文 AI 日报。\n返回 JSON：{\"results\":[{\"item_id\":\"原ID\",\"relevant\":true,\"importance\":0-100,\"reason\":\"简短原因\",\"topic\":\"主题\"}]}。不得新增 ID，不得编造事实。\n\n""" + "\n\n".join(lines)
        try:
            batch = await self.router.generate_structured("filter", prompt, BatchClassification)
            allowed = {item.id for item in items}
            return [result for result in batch.results if result.item_id in allowed]
        except Exception as exc:
            self.logger.warning("task_type=filter skipped error_type=%s", type(exc).__name__)
            return []


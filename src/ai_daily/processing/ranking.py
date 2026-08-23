from __future__ import annotations

import math
from datetime import datetime, timezone

from ..models import ContentItem, ContentType


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(value, 2)))


def _recency(item: ContentItem, now: datetime) -> float:
    age = max(0, (now - item.published_at.astimezone(timezone.utc)).total_seconds() / 3600)
    return _clamp(100 * math.exp(-age / 36))


def _engagement(item: ContentItem) -> float:
    raw = math.log1p(item.likes + item.comments * 2 + item.reposts * 3) * 15
    return _clamp(raw)


def _relevance(item: ContentItem) -> float:
    return _clamp(item.relevance_score or 0)


def rank_items(items: list[ContentItem], config, now: datetime | None = None) -> list[ContentItem]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for item in items:
        item.recency_score = _recency(item, now)
        item.engagement_score = _engagement(item)
        cluster_size = int(item.raw_metadata.get("cluster_size", 1))
        # 单一来源没有 cross-source 加分；同一事件被多个来源讨论时逐步增加。
        item.cross_source_score = _clamp(100 * min(1, max(0, cluster_size - 1) / 3))
        if item.type == ContentType.NEWS:
            weights = config.ranking_weights("news")
            item.heat_score = _clamp(
                item.source_score * weights.get("authority", 0)
                + item.engagement_score * weights.get("engagement", 0)
                + item.cross_source_score * weights.get("cross_source", 0)
                + item.recency_score * weights.get("recency", 0)
                + _relevance(item) * weights.get("relevance", 0)
            )
        elif item.type == ContentType.PAPER:
            weights = config.ranking_weights("paper")
            trending = 100 if item.raw_metadata.get("trending") else _clamp(item.likes * 2)
            community = _clamp(item.likes * 2 + (20 if item.raw_metadata.get("github_url") else 0))
            item.novelty_score = _clamp(50 + (20 if item.raw_metadata.get("github_url") else 0))
            item.heat_score = _clamp(trending * weights.get("trending", 0) + item.recency_score * weights.get("recency", 0) + _relevance(item) * weights.get("relevance", 0) + community * weights.get("community", 0) + item.novelty_score * weights.get("novelty", 0))
        else:
            weights = config.ranking_weights("social")
            item.heat_score = _clamp(item.engagement_score * weights.get("engagement", 0) + item.source_score * weights.get("author", 0) + item.recency_score * weights.get("recency", 0) + _relevance(item) * weights.get("relevance", 0))
    return sorted(items, key=lambda item: item.heat_score, reverse=True)

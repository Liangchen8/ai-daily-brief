from __future__ import annotations

from datetime import datetime, timezone

from ..models import ContentItem, ContentType


def time_filter(items: list[ContentItem], hours: int = 48, now: datetime | None = None) -> list[ContentItem]:
    now = now or datetime.now(timezone.utc)
    result = []
    for item in items:
        published = item.published_at.astimezone(timezone.utc)
        age = (now - published).total_seconds() / 3600
        if -2 <= age <= hours:
            result.append(item)
    return result


def keyword_filter(items: list[ContentItem], high_topics: list[str], medium_topics: list[str]) -> list[ContentItem]:
    result = []
    terms = [term.lower() for term in high_topics + medium_topics]
    broad_terms = ("ai", "llm", "gpt", "openai", "anthropic", "agent")
    for item in items:
        # arXiv 已通过分类查询限定主题；不能再因标题缺少新闻关键词而丢弃论文。
        if item.type == ContentType.PAPER:
            item.relevance_score = max(item.relevance_score, 75)
            result.append(item)
            continue
        text = f"{item.title} {item.content}".lower()
        if any(term in text for term in terms) or any(term in text for term in broad_terms):
            item.relevance_score = min(100, 60 + sum(15 for term in high_topics if term.lower() in text) + sum(7 for term in medium_topics if term.lower() in text))
            result.append(item)
    return result

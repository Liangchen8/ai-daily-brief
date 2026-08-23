from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ai_daily.llm.news_analyzer import NewsAnalyzer
from ai_daily.models import ContentItem, EventCluster, NewsAnalysis


def make_item():
    return ContentItem(
        id="news-1",
        type="news",
        title="真实新闻",
        content="真实内容",
        url="https://example.com/news",
        source="Test",
        source_type="rss",
        published_at=datetime.now(timezone.utc),
    )


def test_news_analysis_requires_key_points_string_array():
    with pytest.raises(ValidationError):
        NewsAnalysis(
            cluster_id="event-1",
            what_happened="发生了什么",
            why_it_matters="为什么重要",
            key_points=[{"type": "fact", "detail": "错误结构"}],
            product_implication="产品影响",
            confidence=0.8,
            source_urls=["https://example.com/news"],
        )


class FakeStructuredRouter:
    def __init__(self, result):
        self.result = result
        self.prompt = ""

    async def generate_structured(self, task, prompt, schema):
        self.prompt = prompt
        return self.result


@pytest.mark.asyncio
async def test_news_analyzer_rejects_markdown_url_and_keeps_allowlisted_url():
    item = make_item()
    allowed_url = str(item.url)
    router = FakeStructuredRouter(
        NewsAnalysis(
            cluster_id="wrong-id",
            what_happened="发生了什么",
            why_it_matters="为什么重要",
            key_points=["关键点一", "关键点二"],
            product_implication="产品影响",
            confidence=0.8,
            source_urls=[f"[{allowed_url}]({allowed_url})"],
        )
    )
    result = await NewsAnalyzer(router).analyze(EventCluster(id="event-1", title=item.title, items=[item]))
    assert result is not None
    assert result.cluster_id == "event-1"
    assert result.source_urls == [allowed_url]
    assert '"key_points":["第一条关键点","第二条关键点"]' in router.prompt
    assert "禁止 Markdown 链接" in router.prompt

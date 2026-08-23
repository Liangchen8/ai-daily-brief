from datetime import date, datetime, timezone

from ai_daily.digest.builder import DigestBuilder
from ai_daily.models import ContentItem, EventCluster, NewsAnalysis


def test_digest_contains_real_source_link():
    item = ContentItem(id="1", type="news", title="AI event", content="Facts", url="https://example.com/real", source="Test", source_type="rss", published_at=datetime.now(timezone.utc), heat_score=88)
    cluster = EventCluster(id="event-1", items=[item], title=item.title, heat_score=88)
    analysis = NewsAnalysis(cluster_id="event-1", what_happened="发生了真实事件", why_it_matters="重要", key_points=["点"], product_implication="价值", confidence=0.8, source_urls=[str(item.url)])
    report = DigestBuilder().build(report_date=date(2026, 8, 23), news_clusters=[cluster], news_analyses=[analysis], papers=[], paper_analyses=[], social=[], social_analyses=[])
    assert "https://example.com/real" in report
    assert "AI Daily Brief" in report


def test_digest_keeps_real_candidates_when_llm_skipped():
    item = ContentItem(id="1", type="news", title="真实候选", content="原始内容", url="https://example.com/raw", source="Test", source_type="rss", published_at=datetime.now(timezone.utc), heat_score=70)
    cluster = EventCluster(id="event-raw", items=[item], title=item.title, heat_score=70)
    report = DigestBuilder().build(report_date=date(2026, 8, 23), news_clusters=[cluster], news_analyses=[], papers=[], paper_analyses=[], social=[], social_analyses=[])
    assert "真实候选" in report
    assert "https://example.com/raw" in report

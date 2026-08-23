from datetime import datetime, timedelta, timezone

from ai_daily.models import ContentItem
from ai_daily.processing.cluster import cluster_items
from ai_daily.processing.deduplicate import deduplicate
from ai_daily.processing.normalize import canonicalize_url, normalize_title
from ai_daily.processing.ranking import rank_items
from ai_daily.processing.filters import keyword_filter


def item(item_id, title, url, source="Test", hours=1):
    return ContentItem(id=item_id, type="news", title=title, content="AI agents and RAG", url=url, source=source, source_type="test", published_at=datetime.now(timezone.utc) - timedelta(hours=hours), source_score=80, relevance_score=90, likes=100, comments=10)


def test_url_normalization():
    assert canonicalize_url("https://www.Example.com/a/?utm_source=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"
    assert normalize_title("OpenAI launches: XXX!") == "openai launches xxx"


def test_dedup_and_cluster():
    first = item("1", "OpenAI launches agent platform", "https://example.com/news?utm_source=x", "Official")
    duplicate = item("2", "OpenAI officially launches agent platform", "https://other.example.com/report", "Media")
    unique = item("3", "Different AI infrastructure release", "https://example.com/other", "Other")
    result = deduplicate([first, duplicate, unique], threshold=80)
    assert len(result) == 2
    clusters = cluster_items(result, title_threshold=80)
    assert len(clusters) == 2
    assert result[0].raw_metadata["duplicate_urls"] == ["https://other.example.com/report"]


def test_ranking_is_0_to_100_and_engagement_matters(app_config):
    low = item("low", "AI agents low", "https://a.test/low", hours=40)
    high = item("high", "AI agents high", "https://a.test/high", hours=1)
    high.likes = 100000
    ranked = rank_items([low, high], app_config)
    assert ranked[0].id == "high"
    for current in ranked:
        assert 0 <= current.heat_score <= 100


def test_cross_source_score_increases_with_multiple_sources(app_config):
    one = item("one", "AI agents", "https://a.test/one")
    many = item("many", "AI agents", "https://a.test/many")
    many.raw_metadata["cluster_size"] = 3
    ranked = rank_items([one, many], app_config)
    assert one.cross_source_score == 0
    assert many.cross_source_score > one.cross_source_score


def test_paper_dedup_merges_huggingface_and_arxiv_signals():
    now = datetime.now(timezone.utc)
    hf = ContentItem(id="hf", type="paper", title="A Shared Paper", content="short", url="https://huggingface.co/papers/2608.00001", source="Hugging Face Papers", source_type="huggingface", published_at=now, likes=12, source_score=92, raw_metadata={"arxiv_id": "2608.00001", "trending": True, "hf_upvotes": 12, "github_url": "https://github.com/example/repo"})
    arxiv = ContentItem(id="arxiv", type="paper", title="A Shared Paper", content="longer abstract", url="https://arxiv.org/abs/2608.00001", source="arXiv", source_type="arxiv", published_at=now, source_score=90, raw_metadata={"arxiv_id": "2608.00001", "categories": ["cs.AI"]})
    merged = deduplicate([hf, arxiv])
    assert len(merged) == 1
    assert set(merged[0].raw_metadata["paper_sources"]) == {"huggingface", "arxiv"}
    assert merged[0].raw_metadata["hf_upvotes"] == 12
    assert merged[0].raw_metadata["categories"] == ["cs.AI"]


def test_paper_survives_keyword_filter_after_category_collection():
    paper = ContentItem(id="paper", type="paper", title="A neutral title", content="Abstract without configured terms", url="https://arxiv.org/abs/2608.00001", source="arXiv", source_type="arxiv", published_at=datetime.now(timezone.utc))
    kept = keyword_filter([paper], ["agent"], ["RAG"])
    assert kept == [paper]
    assert paper.relevance_score == 75

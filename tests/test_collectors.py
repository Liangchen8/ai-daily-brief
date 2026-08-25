from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from ai_daily.collectors.rss import RSSCollector
from ai_daily.collectors.huggingface import HuggingFacePaperCollector
from ai_daily.collectors.arxiv import ArxivCollector
from ai_daily.collectors.bluesky import BlueskyCollector
from ai_daily.collectors.hackernews import HackerNewsCollector
from ai_daily.collectors.official_blog import OfficialBlogCollector
from ai_daily.collectors.semantic_scholar import SemanticScholarCollector
from ai_daily.collectors.x import XCollector
from ai_daily.collectors.base import BaseCollector

FIXED_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fixed_now(monkeypatch):
    """所有 Collector 窗口判断以同一个 UTC 基准执行，独立于机器时区与日期。"""
    monkeypatch.setattr(BaseCollector, "now", lambda _self: FIXED_NOW)
    return FIXED_NOW


def _rss_xml(published_at: datetime) -> bytes:
    pub_date = format_datetime(published_at.astimezone(timezone.utc), usegmt=True)
    return f"""<rss version='2.0'><channel><title>Test</title><item><title>AI agents launch</title><link>https://example.com/a</link><description>RAG and AI agents</description><pubDate>{pub_date}</pubDate></item></channel></rss>""".encode()


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, content: bytes):
        self.content = content

    async def get(self, url, timeout=None, **kwargs):
        assert timeout is not None
        return FakeResponse(self.content)


@pytest.mark.asyncio
async def test_rss_collector_uses_timeout_and_unified_model(app_config, fixed_now):
    source = SimpleNamespace(name="Test", url="https://example.com/feed", type="rss", authority_weight=80, enabled=True)
    app_config.sources = [source]
    items = await RSSCollector(app_config)._one(FakeClient(_rss_xml(fixed_now - timedelta(hours=1))), source)
    assert len(items) == 1
    assert items[0].source_type == "rss"
    assert items[0].title == "AI agents launch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("age_hours", "expected_count"),
    [(1, 1), (35, 1), (36, 1), (37, 0)],
)
async def test_rss_recency_window_is_deterministic(app_config, fixed_now, age_hours, expected_count):
    source = SimpleNamespace(name="Test", url="https://example.com/feed", type="rss", authority_weight=80, enabled=True)
    items = await RSSCollector(app_config)._one(FakeClient(_rss_xml(fixed_now - timedelta(hours=age_hours))), source)
    assert len(items) == expected_count


@pytest.mark.asyncio
async def test_huggingface_falls_back_to_public_search(monkeypatch, app_config, fixed_now):
    now = fixed_now.isoformat().replace("+00:00", "Z")
    row = {"paper": {"id": "1234.5678", "title": "Agent Memory", "summary": "A paper", "publishedAt": now, "authors": [{"name": "Author"}], "upvotes": 12}}

    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self.payload = payload
            self.request = __import__("httpx").Request("GET", "https://example.com")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise __import__("httpx").HTTPStatusError("error", request=self.request, response=__import__("httpx").Response(self.status_code, request=self.request))

        def json(self):
            return self.payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, timeout=None, params=None, **kwargs):
            assert timeout is not None
            if "daily-papers" in url:
                return Response(401, {"error": "token required"})
            return Response(200, [row])

    async def primary_failure(_self):
        raise RuntimeError("mocked_primary_failure")

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", primary_failure)
    monkeypatch.setattr("ai_daily.collectors.huggingface.httpx.AsyncClient", lambda **kwargs: Client())
    items = await HuggingFacePaperCollector(app_config).collect()
    assert len(items) == 1
    assert items[0].raw_metadata["search_fallback"] is True


@pytest.mark.asyncio
async def test_huggingface_sdk_daily_papers_keeps_trending_metadata(monkeypatch, app_config, fixed_now):
    now = fixed_now.isoformat().replace("+00:00", "Z")

    async def daily(_self):
        return [{"paper": {"id": "2608.12345", "title": "Fresh Paper", "abstract": "New method", "publishedAt": now, "authors": [{"name": "Ada"}], "githubUrl": "https://github.com/example/paper"}, "upvotes": 42}]

    fallback_called = False

    async def unexpected_fallback(_self):
        nonlocal fallback_called
        fallback_called = True
        raise AssertionError("主路径成功时不得调用 fallback")

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", daily)
    monkeypatch.setattr(HuggingFacePaperCollector, "_public_http_rows", unexpected_fallback)
    items = await HuggingFacePaperCollector(app_config).collect()
    assert len(items) == 1
    assert items[0].raw_metadata["trending"] is True
    assert items[0].raw_metadata["hf_upvotes"] == 42
    assert items[0].raw_metadata["arxiv_id"] == "2608.12345"
    assert fallback_called is False


@pytest.mark.asyncio
async def test_huggingface_zero_results_is_explicit(monkeypatch, app_config):
    async def daily(_self):
        return []

    async def unexpected_fallback(_self):
        raise AssertionError("正常空结果不得调用 fallback")

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", daily)
    monkeypatch.setattr(HuggingFacePaperCollector, "_public_http_rows", unexpected_fallback)
    collector = HuggingFacePaperCollector(app_config)
    assert await collector.collect() == []
    assert collector.health_records[-1]["status"] == "ok_zero_recent_items"
    assert collector.health_records[-1]["detail"] == "API returned zero results"


@pytest.mark.asyncio
async def test_huggingface_primary_failure_uses_mocked_public_fallback(monkeypatch, app_config, fixed_now):
    now = fixed_now.isoformat().replace("+00:00", "Z")
    row = {"paper": {"id": "fallback-1", "title": "Fallback Paper", "summary": "Abstract", "publishedAt": now}}
    fallback_calls = 0

    async def primary_failure(_self):
        raise RuntimeError("mocked_primary_failure")

    async def public_fallback(_self):
        nonlocal fallback_calls
        fallback_calls += 1
        return [row], False

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", primary_failure)
    monkeypatch.setattr(HuggingFacePaperCollector, "_public_http_rows", public_fallback)
    items = await HuggingFacePaperCollector(app_config).collect()
    assert fallback_calls == 1
    assert len(items) == 1
    assert items[0].raw_metadata["search_fallback"] is True


@pytest.mark.asyncio
async def test_huggingface_both_paths_failure_is_isolated(monkeypatch, app_config):
    async def primary_failure(_self):
        raise RuntimeError("mocked_primary_failure")

    async def fallback_failure(_self):
        raise RuntimeError("mocked_fallback_failure")

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", primary_failure)
    monkeypatch.setattr(HuggingFacePaperCollector, "_public_http_rows", fallback_failure)
    collector = HuggingFacePaperCollector(app_config)
    assert await collector.collect() == []
    assert collector.health_records[-1]["status"] == "parse_failed"


@pytest.mark.asyncio
async def test_huggingface_adaptive_lookback_uses_120_hours(monkeypatch, app_config, fixed_now):
    published = (fixed_now - timedelta(hours=100)).isoformat().replace("+00:00", "Z")

    async def daily(_self):
        return [
            {"paper": {"id": f"2608.00{index}", "title": f"Paper {index}", "abstract": "Abstract", "publishedAt": published}}
            for index in range(5)
        ]

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", daily)
    items = await HuggingFacePaperCollector(app_config).collect()
    assert len(items) == 5
    assert {item.raw_metadata["lookback_hours_used"] for item in items} == {120}
    assert all(99 <= item.raw_metadata["age_hours"] <= 101 for item in items)


class _TextResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.text = content.decode()
        self.status_code = status_code
        self.request = __import__("httpx").Request("GET", "https://example.com")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("httpx").HTTPStatusError("error", request=self.request, response=__import__("httpx").Response(self.status_code, request=self.request))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_rss_http_errors_are_reported(app_config, status):
    source = SimpleNamespace(name="Broken", url="https://example.com/feed", type="rss", authority_weight=80, enabled=True)

    class Client:
        async def get(self, *args, **kwargs):
            return _TextResponse(b"denied", status)

    collector = RSSCollector(app_config)
    assert await collector._one(Client(), source) == []
    assert collector.health_records[-1]["status"] == "http_failed"
    assert collector.health_records[-1]["status_code"] == status


@pytest.mark.asyncio
async def test_rss_parse_failure_and_zero_recent_items(app_config, fixed_now):
    source = SimpleNamespace(name="Test", url="https://example.com/feed", type="rss", authority_weight=80, enabled=True)

    class Client:
        async def get(self, *args, **kwargs):
            return _TextResponse(b"<rss><broken")

    collector = RSSCollector(app_config)
    assert await collector._one(Client(), source) == []
    assert collector.health_records[-1]["status"] == "parse_failed"

    old = _rss_xml(fixed_now - timedelta(hours=37))
    assert await collector._one(type("Client", (), {"get": lambda *args, **kwargs: _awaitable(_TextResponse(old))})(), source) == []
    assert collector.health_records[-1]["status"] == "ok_zero_recent_items"


async def _awaitable(value):
    return value


@pytest.mark.asyncio
async def test_arxiv_atom_date_category_and_configurable_window(monkeypatch, app_config, fixed_now):
    xml = f"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>http://arxiv.org/abs/2608.00001</id><published>{fixed_now.isoformat()}</published><title>Methods</title><summary>Not keyword constrained</summary><author><name>Ada</name></author><category term='cs.AI'/><category term='cs.LG'/></entry></feed>""".encode()

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): return _TextResponse(xml)

    monkeypatch.setattr("ai_daily.collectors.arxiv.httpx.AsyncClient", lambda **kwargs: Client())
    items = await ArxivCollector(app_config).collect()
    assert len(items) == 1
    assert items[0].raw_metadata["categories"] == ["cs.AI", "cs.LG"]
    assert items[0].published_at.tzinfo is not None


@pytest.mark.asyncio
async def test_arxiv_adaptive_lookback_expands_to_96_hours(monkeypatch, app_config, fixed_now):
    published = (fixed_now - timedelta(hours=70)).isoformat()
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/2608.00{index}</id><published>{published}</published><title>Paper {index}</title><summary>Abstract</summary><author><name>Ada</name></author><category term='cs.AI'/></entry>"
        for index in range(5)
    )
    xml = f"<feed xmlns='http://www.w3.org/2005/Atom'>{entries}</feed>".encode()

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): return _TextResponse(xml)

    monkeypatch.setattr("ai_daily.collectors.arxiv.httpx.AsyncClient", lambda **kwargs: Client())
    items = await ArxivCollector(app_config).collect()
    assert len(items) == 5
    assert {item.raw_metadata["lookback_hours_used"] for item in items} == {96}
    assert all(69 <= item.raw_metadata["age_hours"] <= 71 for item in items)


@pytest.mark.asyncio
async def test_official_blog_reads_semantic_json_without_css(app_config, fixed_now):
    now = fixed_now.isoformat()
    html = f'<script type="application/ld+json">{{"@type":"NewsArticle","headline":"Official release","url":"/news/release","datePublished":"{now}","description":"AI announcement"}}</script>'.encode()
    source = SimpleNamespace(name="Official", url="https://example.com/news", type="official_blog", authority_weight=90, enabled=True)

    class Client:
        async def get(self, *args, **kwargs): return _TextResponse(html)

    items = await OfficialBlogCollector(app_config)._one(Client(), source)
    assert len(items) == 1
    assert str(items[0].url) == "https://example.com/news/release"


@pytest.mark.asyncio
async def test_bluesky_unconfigured_and_http_failures_are_isolated(app_config):
    app_config.people = [SimpleNamespace(name="No account", enabled=True, platforms={})]
    collector = BlueskyCollector(app_config)
    assert await collector.collect() == []
    assert collector.health_records[-1]["status"] == "account_not_configured"

    class Client:
        async def get(self, *args, **kwargs): return _TextResponse(b"{}", 404)

    person = SimpleNamespace(name="Valid config", platforms={"bluesky": "real.example"})
    assert await collector._person(Client(), person) == []
    assert collector.health_records[-1]["status"] == "http_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(("age_hours", "expected_count"), [(1, 1), (49, 0)])
async def test_bluesky_recency_window_is_deterministic(app_config, fixed_now, age_hours, expected_count):
    published = (fixed_now - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "feed": [{
                    "post": {
                        "uri": "at://did:plc:test/app.bsky.feed.post/test-post",
                        "cid": "test-cid",
                        "record": {"createdAt": published, "text": "AI agent update"},
                        "likeCount": 2,
                        "replyCount": 1,
                        "repostCount": 0,
                    },
                }],
            }

    class Client:
        async def get(self, *args, **kwargs):
            return Response()

    person = SimpleNamespace(name="Fixed Time", platforms={"bluesky": "fixed.example"}, weight=80)
    items = await BlueskyCollector(app_config)._person(Client(), person)
    assert len(items) == expected_count


@pytest.mark.asyncio
@pytest.mark.parametrize(("age_hours", "expected_count"), [(1, 1), (37, 0)])
async def test_hackernews_collector_uses_only_mocked_http(monkeypatch, app_config, fixed_now, age_hours, expected_count):
    now = int((fixed_now - timedelta(hours=age_hours)).timestamp())

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

        async def get(self, url, **kwargs):
            if url.endswith(("topstories.json", "beststories.json")):
                return Response([1])
            return Response({"id": 1, "type": "story", "url": "https://example.com/ai", "title": "AI agent release", "time": now, "score": 3, "descendants": 1})

    monkeypatch.setattr("ai_daily.collectors.hackernews.httpx.AsyncClient", lambda **kwargs: Client())
    items = await HackerNewsCollector(app_config).collect()
    assert len(items) == expected_count
    if items:
        assert items[0].source_type == "hackernews"


@pytest.mark.asyncio
async def test_semantic_scholar_and_x_missing_keys_do_not_make_network_calls(app_config):
    app_config.environ["SEMANTIC_SCHOLAR_API_KEY"] = ""
    app_config.environ["X_BEARER_TOKEN"] = ""
    semantic = SemanticScholarCollector(app_config)
    assert await semantic.enrich([]) == []
    assert semantic.health_records[-1]["status"] == "disabled_missing_optional_key"
    x_collector = XCollector(app_config)
    assert await x_collector.collect() == []
    assert x_collector.health_records[-1]["status"] == "disabled"

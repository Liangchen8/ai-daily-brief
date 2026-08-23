from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ai_daily.collectors.rss import RSSCollector
from ai_daily.collectors.huggingface import HuggingFacePaperCollector
from ai_daily.collectors.arxiv import ArxivCollector
from ai_daily.collectors.bluesky import BlueskyCollector
from ai_daily.collectors.official_blog import OfficialBlogCollector


class FakeResponse:
    content = b"""<rss version='2.0'><channel><title>Test</title><item><title>AI agents launch</title><link>https://example.com/a</link><description>RAG and AI agents</description><pubDate>Sat, 23 Aug 2026 12:00:00 GMT</pubDate></item></channel></rss>"""

    def raise_for_status(self):
        return None


class FakeClient:
    async def get(self, url, timeout=None, **kwargs):
        assert timeout is not None
        return FakeResponse()


@pytest.mark.asyncio
async def test_rss_collector_uses_timeout_and_unified_model(app_config):
    source = SimpleNamespace(name="Test", url="https://example.com/feed", type="rss", authority_weight=80, enabled=True)
    app_config.sources = [source]
    items = await RSSCollector(app_config)._one(FakeClient(), source)
    assert len(items) == 1
    assert items[0].source_type == "rss"
    assert items[0].title == "AI agents launch"


@pytest.mark.asyncio
async def test_huggingface_falls_back_to_public_search(monkeypatch, app_config):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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

    monkeypatch.setattr("ai_daily.collectors.huggingface.httpx.AsyncClient", lambda **kwargs: Client())
    items = await HuggingFacePaperCollector(app_config).collect()
    assert len(items) == 1
    assert items[0].raw_metadata["search_fallback"] is True


@pytest.mark.asyncio
async def test_huggingface_sdk_daily_papers_keeps_trending_metadata(monkeypatch, app_config):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    async def daily(_self):
        return [{"paper": {"id": "2608.12345", "title": "Fresh Paper", "abstract": "New method", "publishedAt": now, "authors": [{"name": "Ada"}], "githubUrl": "https://github.com/example/paper"}, "upvotes": 42}]

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", daily)
    items = await HuggingFacePaperCollector(app_config).collect()
    assert len(items) == 1
    assert items[0].raw_metadata["trending"] is True
    assert items[0].raw_metadata["hf_upvotes"] == 42
    assert items[0].raw_metadata["arxiv_id"] == "2608.12345"


@pytest.mark.asyncio
async def test_huggingface_zero_results_is_explicit(monkeypatch, app_config):
    async def daily(_self):
        return []

    monkeypatch.setattr(HuggingFacePaperCollector, "_sdk_daily_papers", daily)
    collector = HuggingFacePaperCollector(app_config)
    assert await collector.collect() == []
    assert collector.health_records[-1]["status"] == "ok_zero_recent_items"
    assert collector.health_records[-1]["detail"] == "API returned zero results"


@pytest.mark.asyncio
async def test_huggingface_adaptive_lookback_uses_120_hours(monkeypatch, app_config):
    published = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat().replace("+00:00", "Z")

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
async def test_rss_parse_failure_and_zero_recent_items(app_config):
    source = SimpleNamespace(name="Test", url="https://example.com/feed", type="rss", authority_weight=80, enabled=True)

    class Client:
        async def get(self, *args, **kwargs):
            return _TextResponse(b"<rss><broken")

    collector = RSSCollector(app_config)
    assert await collector._one(Client(), source) == []
    assert collector.health_records[-1]["status"] == "parse_failed"

    old = b"""<rss><channel><item><title>Old</title><link>https://example.com/old</link><pubDate>Sat, 01 Aug 2026 12:00:00 GMT</pubDate></item></channel></rss>"""
    assert await collector._one(type("Client", (), {"get": lambda *args, **kwargs: _awaitable(_TextResponse(old))})(), source) == []
    assert collector.health_records[-1]["status"] == "ok_zero_recent_items"


async def _awaitable(value):
    return value


@pytest.mark.asyncio
async def test_arxiv_atom_date_category_and_configurable_window(monkeypatch, app_config):
    xml = f"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>http://arxiv.org/abs/2608.00001</id><published>{datetime.now(timezone.utc).isoformat()}</published><title>Methods</title><summary>Not keyword constrained</summary><author><name>Ada</name></author><category term='cs.AI'/><category term='cs.LG'/></entry></feed>""".encode()

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
async def test_arxiv_adaptive_lookback_expands_to_96_hours(monkeypatch, app_config):
    published = (datetime.now(timezone.utc) - timedelta(hours=70)).isoformat()
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
async def test_official_blog_reads_semantic_json_without_css(app_config):
    now = datetime.now(timezone.utc).isoformat()
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

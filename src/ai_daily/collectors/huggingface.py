from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import BaseCollector


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _value(row: Any, *names: str, default: Any = None) -> Any:
    values = _as_mapping(row)
    for name in names:
        if name in values and values[name] is not None:
            return values[name]
        if hasattr(row, name):
            candidate = getattr(row, name)
            if candidate is not None:
                return candidate
    return default


def _published(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class HuggingFacePaperCollector(BaseCollector):
    """优先使用新版 huggingface_hub 的公开 Daily Papers 能力。"""

    name = "huggingface"
    daily_url = "https://huggingface.co/api/daily-papers?limit=100&sort=trending"
    search_url = "https://huggingface.co/api/papers/search"

    async def _sdk_daily_papers(self) -> list[Any] | None:
        try:
            from huggingface_hub import HfApi
        except ImportError:
            return None
        method = getattr(HfApi(library_name="ai-daily-brief"), "list_daily_papers", None)
        if not callable(method):
            return None
        token = self.config.env("HF_TOKEN") or False
        return await asyncio.wait_for(
            asyncio.to_thread(lambda: list(method(sort="trending", limit=100, token=token))),
            timeout=self.timeout,
        )

    async def _public_http_rows(self) -> tuple[list[Any], bool]:
        headers = {"Authorization": f"Bearer {self.config.env('HF_TOKEN')}"} if self.config.env("HF_TOKEN") else {}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            try:
                response = await self.request(client, self.daily_url)
                payload = response.json()
                return (payload if isinstance(payload, list) else []), True
            except httpx.HTTPStatusError as exc:
                self.record_health("http_failed", source="Hugging Face Daily Papers", requested_url=self.daily_url, status_code=exc.response.status_code)
            rows: list[Any] = []
            for query in self.config.high_topics[:3] or ["artificial intelligence"]:
                try:
                    response = await self.request(client, self.search_url, params={"q": query})
                    payload = response.json()
                    if isinstance(payload, list):
                        rows.extend(payload)
                except httpx.HTTPStatusError as exc:
                    self.record_health("http_failed", source="Hugging Face Papers Search", requested_url=self.search_url, status_code=exc.response.status_code)
            return rows, False

    def _to_items(self, rows: list[Any], *, trending: bool, fallback: bool, max_lookback_hours: int = 168) -> list:
        result = []
        seen_ids: set[str] = set()
        for row in rows:
            paper = _value(row, "paper", default=row)
            paper_id = str(_value(paper, "id", "paper_id", "arxiv_id", default=_value(row, "id", default="")) or "")
            if not paper_id or paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)
            title = str(_value(paper, "title", default=_value(row, "title", default="")) or "").strip()
            abstract = str(_value(paper, "summary", "abstract", default=_value(row, "summary", "abstract", default="")) or "")
            published = _published(_value(paper, "publishedAt", "published_at", "createdAt", default=_value(row, "publishedAt", "published_at")))
            if not title or not published or not self.recent(published, max_lookback_hours):
                continue
            authors = _value(paper, "authors", default=[])
            author_names = [str(_value(author, "name", default=author)) for author in (authors or [])]
            github = _value(paper, "githubRepo", "githubUrl", "github_url", default=_value(row, "githubRepo", "githubUrl", "github_url"))
            url = str(_value(paper, "url", "paperUrl", default=_value(row, "url", "paperUrl", default=f"https://huggingface.co/papers/{paper_id}")))
            upvotes = int(_value(row, "upvotes", "numUpvotes", default=_value(paper, "upvotes", "numUpvotes", default=0)) or 0)
            arxiv_id = paper_id.replace("arXiv:", "").strip()
            result.append(self.item(
                item_id=f"hf-{hashlib.sha1(paper_id.encode()).hexdigest()[:16]}", type="paper", title=title,
                content=abstract, url=url, source="Hugging Face Papers", source_type="huggingface",
                published_at=published, author=", ".join(author_names), likes=upvotes, source_score=92,
                raw_metadata={"paper_id": paper_id, "arxiv_id": arxiv_id, "trending": trending or bool(_value(row, "trending", default=False)), "hf_upvotes": upvotes, "github_url": github, "search_fallback": fallback},
            ))
        return result

    async def collect(self) -> list:
        try:
            try:
                sdk_rows = await self._sdk_daily_papers()
            except Exception as exc:
                # SDK 不可用或网关临时失败时，才降级到公开搜索；空列表本身代表正常的零结果。
                self.record_health(
                    "parse_failed", source="Hugging Face Daily Papers",
                    requested_url="huggingface_hub.HfApi.list_daily_papers", error_type=type(exc).__name__,
                )
                sdk_rows = None
            if sdk_rows is not None:
                result = self._to_items(sdk_rows, trending=True, fallback=False)
                result, lookback_hours, reason = self.adaptive_paper_window(result, windows=(72, 120, 168))
                self.record_health("success" if result else "ok_zero_recent_items", source="Hugging Face Daily Papers", requested_url="huggingface_hub.HfApi.list_daily_papers", fetched_items=len(sdk_rows), recent_items=len(result), lookback_hours=lookback_hours, reason=reason, detail="API returned zero results" if not sdk_rows else "")
                self.logger.info("collector=%s hf_lookback_used=%s reason=%s", self.name, lookback_hours, reason)
                return result
            rows, trending = await self._public_http_rows()
            result = self._to_items(rows, trending=trending, fallback=not trending)
            result, lookback_hours, reason = self.adaptive_paper_window(result, windows=(72, 120, 168))
            self.record_health("success" if result else "ok_zero_recent_items", source="Hugging Face Daily Papers", requested_url=self.daily_url if trending else self.search_url, fetched_items=len(rows), recent_items=len(result), lookback_hours=lookback_hours, reason=reason, detail="API returned zero results" if not rows else "")
            self.logger.info("collector=%s hf_lookback_used=%s reason=%s", self.name, lookback_hours, reason)
            return result
        except httpx.HTTPStatusError as exc:
            self.record_health("http_failed", source="Hugging Face Papers", requested_url=self.daily_url, status_code=exc.response.status_code)
            return []
        except Exception as exc:
            self.record_health("parse_failed", source="Hugging Face Papers", requested_url=self.daily_url, error_type=type(exc).__name__)
            return []

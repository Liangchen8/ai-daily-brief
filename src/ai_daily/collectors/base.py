from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import ContentItem


class BaseCollector:
    name = "base"

    def __init__(self, config, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger("ai_daily")
        self.timeout = float(config.env("REQUEST_TIMEOUT_SECONDS", "20") or 20)
        self.health_records: list[dict[str, object]] = []

    def record_health(self, status: str, *, source: str | None = None, **details: object) -> None:
        """记录可聚合的采集健康状态；仅记录公开 URL 与非敏感计数。"""
        record = {"collector": self.name, "source": source or self.name, "status": status, **details}
        self.health_records.append(record)
        fields = " ".join(f"{key}={value}" for key, value in record.items())
        self.logger.info("%s", fields)

    async def request(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        for attempt in range(3):
            try:
                response = await client.get(url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in {429, 502, 503, 504} or attempt == 2:
                    raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt == 2:
                    raise
            await asyncio.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"请求失败: {url}")

    def now(self) -> datetime:
        """统一提供 UTC 当前时间；测试可覆写，生产默认仍使用真实时间。"""
        return datetime.now(timezone.utc)

    def recent(self, published_at: datetime, hours: int) -> bool:
        now = self.now()
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age = (now - published_at.astimezone(timezone.utc)).total_seconds() / 3600
        return -2 <= age <= hours

    def adaptive_paper_window(
        self,
        items: list[ContentItem],
        *,
        windows: tuple[int, ...],
        minimum_candidates: int = 5,
    ) -> tuple[list[ContentItem], int, str]:
        """按新鲜度逐档扩展论文窗口，旧论文仅在新论文不足时参与补位。"""
        now = self.now()
        ages = {
            item.id: max(0.0, (now - item.published_at.astimezone(timezone.utc)).total_seconds() / 3600)
            for item in items
        }
        selected: list[ContentItem] = []
        used = windows[-1]
        for window in windows:
            selected = [item for item in items if ages[item.id] <= window]
            used = window
            if len(selected) >= minimum_candidates:
                break
        reason = "sufficient_recent_candidates" if used == windows[0] else "insufficient_recent_candidates"
        for item in selected:
            item.raw_metadata["lookback_hours_used"] = used
            item.raw_metadata["age_hours"] = round(ages[item.id], 2)
        return selected, used, reason

    def item(
        self,
        *,
        item_id: str,
        type: str,
        title: str,
        content: str,
        url: str,
        source: str,
        source_type: str,
        published_at: datetime,
        author: str = "",
        likes: int = 0,
        comments: int = 0,
        reposts: int = 0,
        source_score: float = 50,
        raw_metadata: dict[str, Any] | None = None,
    ) -> ContentItem:
        return ContentItem(
            id=item_id,
            type=type,
            title=title.strip() or "无标题",
            content=content.strip(),
            summary=content.strip()[:500],
            url=url,
            source=source,
            source_type=source_type,
            published_at=published_at,
            author=author,
            likes=max(0, int(likes or 0)),
            comments=max(0, int(comments or 0)),
            reposts=max(0, int(reposts or 0)),
            source_score=max(0, min(100, float(source_score))),
            raw_metadata=raw_metadata or {},
        )

    async def collect(self) -> list[ContentItem]:
        raise NotImplementedError

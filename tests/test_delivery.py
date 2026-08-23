from datetime import datetime, timezone
import logging

import pytest

from ai_daily.main import deliver_report
from ai_daily.models import ContentItem
from ai_daily.storage.history import HistoryStore


def _item() -> ContentItem:
    return ContentItem(
        id="sent-item", type="news", title="已发送内容", content="内容", url="https://example.com/item",
        source="Test", source_type="test", published_at=datetime.now(timezone.utc),
    )


class SuccessNotifier:
    def __init__(self):
        self.calls = 0

    async def send(self, content: str) -> bool:
        self.calls += 1
        return True


class FailedNotifier:
    async def send(self, content: str) -> bool:
        raise RuntimeError("飞书不可用")


@pytest.mark.asyncio
async def test_send_success_updates_and_reloads_history(tmp_path):
    path = tmp_path / "seen_items.json"
    status, updated = await deliver_report(
        send=True, notifier=SuccessNotifier(), report="日报", history=HistoryStore(path),
        selected_items=[_item()], selected_news=[], logger=logging.getLogger("test"),
    )
    assert (status, updated) == ("sent", True)
    reloaded = HistoryStore(path)
    assert reloaded.is_new_or_updated(item_id="sent-item", canonical_url="https://example.com/item", cluster_id=None, title="已发送内容", content="内容") == (False, False)


@pytest.mark.asyncio
async def test_send_failure_does_not_update_history(tmp_path):
    path = tmp_path / "seen_items.json"
    status, updated = await deliver_report(
        send=True, notifier=FailedNotifier(), report="日报", history=HistoryStore(path),
        selected_items=[_item()], selected_news=[], logger=logging.getLogger("test"),
    )
    assert (status, updated) == ("failed", False)
    assert not path.exists()


@pytest.mark.asyncio
async def test_dry_run_does_not_send_or_update_history(tmp_path):
    path = tmp_path / "seen_items.json"
    notifier = SuccessNotifier()
    status, updated = await deliver_report(
        send=False, notifier=notifier, report="日报", history=HistoryStore(path),
        selected_items=[_item()], selected_news=[], logger=logging.getLogger("test"),
    )
    assert (status, updated) == ("dry_run", False)
    assert notifier.calls == 0
    assert not path.exists()


def test_history_update_event_is_eligible_for_resend(tmp_path):
    path = tmp_path / "seen_items.json"
    history = HistoryStore(path)
    history.mark_sent(item_id="same", canonical_url="https://example.com/a", cluster_id=None, title="旧标题", content="旧内容")
    history.save()
    reloaded = HistoryStore(path)
    assert reloaded.is_new_or_updated(item_id="same", canonical_url="https://example.com/a", cluster_id=None, title="新标题", content="新内容") == (True, True)

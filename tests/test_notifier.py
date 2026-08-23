import pytest

from ai_daily.notifiers.feishu import FeishuNotifier


def test_feishu_chunks():
    assert FeishuNotifier.chunks("abcdef", 2) == ["ab", "cd", "ef"]


@pytest.mark.asyncio
async def test_feishu_requires_webhook():
    with pytest.raises(RuntimeError, match="FEISHU_WEBHOOK_URL"):
        await FeishuNotifier("").send("hello")


from __future__ import annotations

import logging

import httpx

from .base import Notifier


class FeishuNotifier(Notifier):
    def __init__(self, webhook_url: str, logger: logging.Logger | None = None):
        self.webhook_url = webhook_url
        self.logger = logger or logging.getLogger("ai_daily")

    @staticmethod
    def chunks(content: str, max_chars: int = 3500) -> list[str]:
        return [content[index:index + max_chars] for index in range(0, len(content), max_chars)] or [""]

    async def send(self, content: str) -> bool:
        if not self.webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL 未配置")
        async with httpx.AsyncClient(timeout=20) as client:
            for index, chunk in enumerate(self.chunks(content), start=1):
                response = await client.post(self.webhook_url, json={"msg_type": "text", "content": {"text": chunk}})
                response.raise_for_status()
                body = response.json()
                if body.get("code", 0) not in (0, None):
                    raise RuntimeError(f"飞书返回错误 code={body.get('code')}")
                self.logger.info("push_status=sent channel=feishu part=%s", index)
        return True


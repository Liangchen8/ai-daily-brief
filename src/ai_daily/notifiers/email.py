from __future__ import annotations

from .base import Notifier


class EmailNotifier(Notifier):
    async def send(self, content: str) -> bool:
        raise NotImplementedError("EmailNotifier 仅保留扩展接口，第一版不作为默认渠道")


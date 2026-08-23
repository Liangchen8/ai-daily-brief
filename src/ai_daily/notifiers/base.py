from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    async def send(self, content: str) -> bool:
        raise NotImplementedError


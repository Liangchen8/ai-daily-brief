from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class LLMError(RuntimeError):
    pass


class MissingCredentialsError(LLMError):
    pass


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    retry_count: int = 0


class LLMClient(ABC):
    provider: str

    @abstractmethod
    async def generate(self, prompt: str, model: str, **kwargs: Any) -> LLMResponse:
        raise NotImplementedError


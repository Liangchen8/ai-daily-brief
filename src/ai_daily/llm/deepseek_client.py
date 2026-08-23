from __future__ import annotations

from .openai_client import OpenAIClient


class DeepSeekClient(OpenAIClient):
    provider = "deepseek"

    def __init__(self, api_key: str, base_url: str = ""):
        super().__init__(api_key=api_key, base_url=base_url or "https://api.deepseek.com")


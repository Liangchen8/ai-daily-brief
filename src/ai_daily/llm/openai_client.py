from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from openai import AsyncOpenAI

from .base import LLMClient, LLMResponse, MissingCredentialsError


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, api_key: str, base_url: str = ""):
        if not api_key:
            raise MissingCredentialsError("OPENAI_API_KEY 未配置")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)

    @staticmethod
    def _preview(response: Any, limit: int = 400) -> str:
        if isinstance(response, str):
            preview = response
        elif isinstance(response, Mapping):
            try:
                preview = json.dumps(response, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                preview = repr(response)
        else:
            preview = repr(response)
        return " ".join(preview.split())[:limit]

    def _unexpected_response(self, response: Any, reason: str) -> RuntimeError:
        return RuntimeError(
            "unexpected_response "
            f"provider={self.provider} response_type={type(response).__name__} "
            f"preview={self._preview(response)!r} reason={reason}"
        )

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    def _parse_sse_response(self, response: str) -> tuple[str, int | None, int | None, int | None]:
        """解析被 OpenAI-compatible 网关以字符串返回的 SSE data 事件。"""
        content_parts: list[str] = []
        usage: Any = None
        event_count = 0
        for line in response.splitlines():
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            payload = stripped.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise self._unexpected_response(response, "invalid_sse_json") from exc
            if not isinstance(event, Mapping):
                raise self._unexpected_response(response, "non_object_sse_event")
            event_count += 1
            if self._field(event, "usage") is not None:
                usage = self._field(event, "usage")
            choices = self._field(event, "choices", [])
            if not isinstance(choices, (list, tuple)):
                raise self._unexpected_response(response, "invalid_sse_choices")
            for choice in choices:
                delta_or_message = self._field(choice, "delta") or self._field(choice, "message")
                content = self._field(delta_or_message, "content") if delta_or_message is not None else None
                if isinstance(content, str):
                    content_parts.append(content)
                elif content is not None:
                    raise self._unexpected_response(response, "non_string_sse_content")
        if event_count == 0:
            raise self._unexpected_response(response, "missing_sse_events")
        if not content_parts:
            raise self._unexpected_response(response, "missing_sse_content")
        return (
            "".join(content_parts),
            self._field(usage, "prompt_tokens") if usage is not None else None,
            self._field(usage, "completion_tokens") if usage is not None else None,
            self._field(usage, "total_tokens") if usage is not None else None,
        )

    def _parse_response(self, response: Any) -> tuple[str, int | None, int | None, int | None]:
        """兼容 OpenAI SDK 对象、OpenAI-compatible dict 与 JSON 字符串响应。"""
        if isinstance(response, str):
            stripped = response.lstrip()
            if stripped.lower().startswith(("<!doctype html", "<html")):
                raise self._unexpected_response(response, "html_response")
            if stripped.startswith("data:"):
                return self._parse_sse_response(response)
            try:
                response = json.loads(response)
            except json.JSONDecodeError as exc:
                raise self._unexpected_response(response, "non_json_string") from exc

        if not isinstance(response, Mapping) and not hasattr(response, "choices"):
            raise self._unexpected_response(response, "unsupported_response_shape")

        choices = self._field(response, "choices")
        if not isinstance(choices, (list, tuple)) or not choices:
            raise self._unexpected_response(response, "missing_choices")

        message = self._field(choices[0], "message")
        if message is None:
            raise self._unexpected_response(response, "missing_choice_message")
        content = self._field(message, "content")
        if not isinstance(content, str):
            raise self._unexpected_response(response, "missing_or_non_string_message_content")

        usage = self._field(response, "usage")
        input_tokens = self._field(usage, "prompt_tokens") if usage is not None else None
        output_tokens = self._field(usage, "completion_tokens") if usage is not None else None
        total_tokens = self._field(usage, "total_tokens") if usage is not None else None
        return content, input_tokens, output_tokens, total_tokens

    async def generate(self, prompt: str, model: str, **kwargs: Any) -> LLMResponse:
        if not model:
            raise ValueError("OpenAI Model 未配置")
        started = time.perf_counter()
        request_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.2),
            # 部分兼容网关在省略该字段时会默认 SSE；显式关闭流式以请求单个 ChatCompletion JSON。
            "stream": False,
        }
        response_format = kwargs.get("response_format")
        if response_format is not None:
            request_kwargs["response_format"] = response_format
        response = await self.client.chat.completions.create(**request_kwargs)
        text, input_tokens, output_tokens, total_tokens = self._parse_response(response)
        return LLMResponse(
            text=text,
            provider=self.provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            retry_count=0,
        )

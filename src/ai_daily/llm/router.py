from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import AppConfig
from ..models import LLMUsage
from .base import LLMClient, LLMResponse, MissingCredentialsError
from .deepseek_client import DeepSeekClient
from .openai_client import OpenAIClient

T = TypeVar("T", bound=BaseModel)


class ModelRouter:
    def __init__(self, config: AppConfig, logger: logging.Logger | None = None, clients: dict[str, LLMClient] | None = None):
        self.config = config
        self.logger = logger or logging.getLogger("ai_daily")
        self.clients = clients or {}
        self.usage: list[LLMUsage] = []

    def _client(self, provider: str) -> LLMClient:
        if provider in self.clients:
            return self.clients[provider]
        key = self.config.api_key_for(provider)
        if provider == "openai":
            self.clients[provider] = OpenAIClient(key, self.config.env("OPENAI_BASE_URL"))
        elif provider == "deepseek":
            self.clients[provider] = DeepSeekClient(key, self.config.env("DEEPSEEK_BASE_URL"))
        else:
            raise ValueError(f"不支持的 Provider: {provider}")
        return self.clients[provider]

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
        return status in {429, 500, 502, 503, 504} or isinstance(exc, (TimeoutError, ConnectionError))

    async def generate(self, task: str, prompt: str, cli: dict[str, str] | None = None, **kwargs: Any) -> LLMResponse:
        resolved = self.config.resolve_model(task, cli)
        fallback = self.config.fallback_model(task)
        candidates = [(resolved.provider, resolved.model, False)]
        if fallback.provider and fallback.model and (fallback.provider, fallback.model) != (resolved.provider, resolved.model):
            candidates.append((fallback.provider, fallback.model, True))
        last_error: Exception | None = None
        for provider, model, fallback_used in candidates:
            if not provider or not model:
                last_error = ValueError(f"任务 {task} 的 Provider/Model 未配置")
                self.logger.warning("task_type=%s provider=%s model=%s unavailable reason=missing_model", task, provider or "", model or "")
                continue
            attempts = 0
            try:
                client = self._client(provider)
                for attempts in range(3):
                    try:
                        started = time.perf_counter()
                        response = await client.generate(prompt, model, **kwargs)
                        latency_ms = int((time.perf_counter() - started) * 1000)
                        self.usage.append(LLMUsage(task_type=task, provider=provider, model=model, latency_ms=latency_ms, retry_count=attempts, fallback_used=fallback_used, input_tokens=response.input_tokens, output_tokens=response.output_tokens, total_tokens=response.total_tokens))
                        if fallback_used:
                            self.logger.warning("task_type=%s fallback_used=true provider=%s model=%s", task, provider, model)
                        return response
                    except Exception as exc:
                        last_error = exc
                        if attempts >= 2 or not self._retryable(exc):
                            raise
                
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.exception(
                        "task_type=%s provider=%s model=%s failed error_type=%s fallback_used=%s",
                        task, provider, model, type(exc).__name__, fallback_used,
                    )
                elif message.startswith("unexpected_response"):
                    self.logger.warning(
                        "%s task_type=%s model=%s fallback_used=%s",
                        message, task, model, fallback_used,
                    )
                else:
                    self.logger.warning("task_type=%s provider=%s model=%s failed error_type=%s fallback_used=%s", task, provider, model, type(exc).__name__, fallback_used)
                continue
        raise last_error or RuntimeError(f"任务 {task} 没有可用模型")

    async def generate_structured(self, task: str, prompt: str, schema: type[T], cli: dict[str, str] | None = None, **kwargs: Any) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        structured_prompt = (
            f"{prompt}\n\n"
            "输出必须是严格合法的 JSON，且必须完全符合以下 JSON Schema。"
            "不要返回 Markdown 代码块、解释文字或 Schema 之外的结构。\n"
            f"JSON Schema:\n{schema_json}"
        )
        try:
            response = await self.generate(
                task,
                structured_prompt,
                cli=cli,
                response_format={"type": "json_object"},
                **kwargs,
            )
        except RuntimeError as exc:
            # 某些 OpenAI-compatible 网关接受 json_object 但只回传 usage SSE chunk。
            # Schema 已在 Prompt 中，故安全地降级为 Prompt-only JSON 请求。
            if not (str(exc).startswith("unexpected_response") and "sse" in str(exc)):
                raise
            self.logger.warning(
                "task_type=%s structured_response_format_fallback=true reason=compatible_gateway_sse",
                task,
            )
            response = await self.generate(task, structured_prompt, cli=cli, **kwargs)
        text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            return schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            # 只进行一次受限修复，避免把格式错误无限重试成额外成本。
            repair_prompt = f"请把下面的模型输出修复为严格 JSON，并满足这个 Pydantic Schema：{schema.model_json_schema()}。只返回 JSON，不新增事实。原输出：{text}"
            repaired = await self.generate(task, repair_prompt, cli=cli, response_format={"type": "json_object"}, **kwargs)
            repaired_text = repaired.text.strip().removeprefix("```json").removesuffix("```").strip()
            try:
                return schema.model_validate(json.loads(repaired_text))
            except (json.JSONDecodeError, ValidationError) as repair_exc:
                raise ValueError(f"LLM 结构化输出无法通过校验，Repair 也失败: {repair_exc}") from exc

    def usage_summary(self) -> dict[str, int | str]:
        return {
            "total_calls": len(self.usage),
            "filter_calls": sum(1 for item in self.usage if item.task_type == "filter"),
            "news_analysis_calls": sum(1 for item in self.usage if item.task_type == "news_analysis"),
            "paper_analysis_calls": sum(1 for item in self.usage if item.task_type == "paper_analysis"),
            "social_analysis_calls": sum(1 for item in self.usage if item.task_type == "social_analysis"),
            "digest_calls": sum(1 for item in self.usage if item.task_type == "digest"),
            "input_tokens": sum(item.input_tokens or 0 for item in self.usage),
            "output_tokens": sum(item.output_tokens or 0 for item in self.usage),
        }

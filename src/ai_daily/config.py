from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .models import ModelSpec, ResolvedModel, TaskModelConfig


class SourceConfig(BaseModel):
    name: str
    url: str
    type: str = "rss"
    authority_weight: float = 50
    enabled: bool = True


class PersonConfig(BaseModel):
    name: str
    weight: float = 50
    enabled: bool = True
    platforms: dict[str, str] = Field(default_factory=dict)


class AppConfig:
    def __init__(self, root: Path | None = None, environ: dict[str, str] | None = None):
        self.root = root or Path(__file__).resolve().parents[2]
        self.environ = dict(environ or os.environ)
        load_dotenv(self.root / ".env", override=False)
        for key, value in os.environ.items():
            self.environ.setdefault(key, value)
        self.sources = self._load_list("config/sources.yaml", SourceConfig)
        self.people = self._load_list("config/people.yaml", PersonConfig)
        self.topics = self._load_yaml("config/topics.yaml")
        self.ranking = self._load_yaml("config/ranking.yaml")
        self.models = self._load_yaml("config/models.yaml")

    def _load_yaml(self, relative: str) -> Any:
        path = self.root / relative
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _load_list(self, relative: str, model: type[BaseModel]) -> list[Any]:
        raw = self._load_yaml(relative)
        return [model.model_validate(item) for item in raw]

    @property
    def high_topics(self) -> list[str]:
        return list(self.topics.get("high_priority", []))

    @property
    def medium_topics(self) -> list[str]:
        return list(self.topics.get("medium_priority", []))

    def env(self, key: str, default: str = "") -> str:
        return self.environ.get(key, default).strip()

    def api_key_for(self, provider: str) -> str:
        return self.env({"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(provider, ""))

    def resolve_model(self, task: str, cli: dict[str, str] | None = None) -> ResolvedModel:
        cli = cli or {}
        task_key = task.lower()
        upper = task_key.upper()
        provider = cli.get("provider", "") or self.env(f"{upper}_PROVIDER") or self.env("LLM_PROVIDER")
        model = cli.get("model", "") or self.env(f"{upper}_MODEL") or self.env("LLM_MODEL")
        source = "cli" if cli.get("provider") or cli.get("model") else "environment" if (
            self.env(f"{upper}_PROVIDER") or self.env(f"{upper}_MODEL") or self.env("LLM_PROVIDER") or self.env("LLM_MODEL")
        ) else ""
        task_cfg = self.models.get(task_key, {}) or {}
        default_cfg = self.models.get("default", {}) or {}
        task_primary = task_cfg.get("primary", {})
        default_primary = default_cfg.get("primary", {})
        if not provider:
            provider = task_primary.get("provider", "") or default_primary.get("provider", "")
            source = "models.yaml" if task_primary.get("provider") else "default"
        if not model:
            model = task_primary.get("model", "") or default_primary.get("model", "")
            if not source:
                source = "models.yaml" if task_primary.get("model") else "default"
        return ResolvedModel(task=task_key, provider=provider, model=model, source=source or "default")

    def fallback_model(self, task: str) -> ModelSpec:
        task_cfg = self.models.get(task, {}) or {}
        fallback = task_cfg.get("fallback") or (self.models.get("default", {}) or {}).get("fallback", {})
        return ModelSpec.model_validate(fallback or {})

    def ranking_weights(self, kind: str) -> dict[str, float]:
        return {str(k): float(v) for k, v in (self.ranking.get(kind, {}) or {}).items() if k not in {"title_similarity_threshold", "max_hours_apart"}}

    def show_models(self, cli_overrides: dict[str, dict[str, str]] | None = None) -> list[ResolvedModel]:
        tasks = ["filter", "news_analysis", "paper_analysis", "social_analysis", "digest"]
        return [self.resolve_model(task, (cli_overrides or {}).get(task, {})) for task in tasks]


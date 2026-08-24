from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .models import ModelSpec, ResolvedModel, TaskModelConfig


REQUIRED_CONFIG_FILES = ("sources.yaml", "models.yaml", "people.yaml", "topics.yaml", "ranking.yaml")


class ConfigurationError(RuntimeError):
    """配置目录或必需配置文件不可用。"""


def _path_from_env(environ: dict[str, str], name: str) -> Path | None:
    value = environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


def resolve_config_dir(
    *,
    environ: dict[str, str] | None = None,
    cwd: Path | None = None,
    source_file: Path | None = None,
    project_root: Path | None = None,
) -> Path:
    """按固定优先级寻找配置目录，绝不依赖 Python 安装目录。"""
    env = dict(os.environ if environ is None else environ)
    configured = _path_from_env(env, "AI_DAILY_CONFIG_DIR")
    if configured:
        return configured
    if project_root is not None:
        candidate = Path(project_root).expanduser().resolve() / "config"
        if candidate.is_dir():
            return candidate
    working_dir = (cwd or Path.cwd()).expanduser().resolve()
    candidate = working_dir / "config"
    if candidate.is_dir():
        return candidate
    module_path = (source_file or Path(__file__)).expanduser().resolve()
    for parent in (module_path, *module_path.parents):
        candidate = parent / "config"
        if candidate.is_dir():
            return candidate
    raise ConfigurationError(f"Unable to locate config directory; cwd={working_dir}")


def _resolve_runtime_dir(environ: dict[str, str], name: str, default: Path) -> Path:
    return _path_from_env(environ, name) or default


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
        self.environ = dict(environ or os.environ)
        self.config_dir = resolve_config_dir(environ=self.environ, project_root=root)
        self.root = self.config_dir.parent
        self.data_dir = _resolve_runtime_dir(self.environ, "AI_DAILY_DATA_DIR", self.root / "data")
        self.output_dir = _resolve_runtime_dir(self.environ, "AI_DAILY_OUTPUT_DIR", self.root / "output")
        load_dotenv(self.root / ".env", override=False)
        for key, value in os.environ.items():
            self.environ.setdefault(key, value)
        self._validate_config_files()
        self.sources = self._load_list("sources.yaml", SourceConfig)
        self.people = self._load_list("people.yaml", PersonConfig)
        self.topics = self._load_yaml("topics.yaml")
        self.ranking = self._load_yaml("ranking.yaml")
        self.models = self._load_yaml("models.yaml")

    def _validate_config_files(self) -> None:
        for filename in REQUIRED_CONFIG_FILES:
            path = self.config_dir / filename
            if not path.is_file():
                raise ConfigurationError(f"Missing config file: {path} (config_dir={self.config_dir})")

    def _load_yaml(self, filename: str) -> Any:
        path = self.config_dir / filename
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

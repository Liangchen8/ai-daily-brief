from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ContentType(str, Enum):
    NEWS = "news"
    PAPER = "paper"
    SOCIAL = "social"


class ContentItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: ContentType
    title: str
    content: str = ""
    summary: str = ""
    url: HttpUrl | str
    source: str
    source_type: str
    author: str = ""
    published_at: datetime
    likes: int = 0
    comments: int = 0
    reposts: int = 0
    source_score: float = 0
    engagement_score: float = 0
    cross_source_score: float = 0
    recency_score: float = 0
    relevance_score: float = 0
    novelty_score: float = 0
    heat_score: float = 0
    cluster_id: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at", mode="before")
    @classmethod
    def ensure_timezone(cls, value: Any) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EventCluster(BaseModel):
    id: str
    items: list[ContentItem] = Field(default_factory=list)
    title: str
    summary: str = ""
    heat_score: float = 0
    update: bool = False

    @property
    def urls(self) -> list[str]:
        return [str(item.url) for item in self.items]


class ModelSpec(BaseModel):
    provider: str = ""
    model: str = ""


class TaskModelConfig(BaseModel):
    primary: ModelSpec = Field(default_factory=ModelSpec)
    fallback: ModelSpec = Field(default_factory=ModelSpec)


class ResolvedModel(BaseModel):
    task: str
    provider: str
    model: str
    source: str


class ClassificationResult(BaseModel):
    item_id: str
    relevant: bool
    importance: int = Field(ge=0, le=100)
    reason: str = ""
    topic: str = ""


class NewsAnalysis(BaseModel):
    cluster_id: str
    what_happened: str
    why_it_matters: str
    key_points: list[str] = Field(default_factory=list)
    product_implication: str
    confidence: float = Field(ge=0, le=1)
    source_urls: list[str] = Field(default_factory=list)


class PaperAnalysis(BaseModel):
    item_id: str
    problem: str
    previous_method: str
    core_idea: str
    innovation: str
    method: str
    experiment_result: str
    limitations: str
    product_implication: str
    recommended_to_read: bool
    source_url: str
    github_url: str | None = None


class SocialAnalysis(BaseModel):
    item_id: str
    author: str
    original_view: str
    core_argument: str
    context: str
    why_it_matters: str
    fact_or_opinion: str
    source_url: str


class DigestResult(BaseModel):
    top_news_ids: list[str] = Field(default_factory=list)
    top_paper_ids: list[str] = Field(default_factory=list)
    top_social_ids: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list, max_length=3)


class LLMUsage(BaseModel):
    task_type: str
    provider: str
    model: str
    latency_ms: int
    retry_count: int = 0
    fallback_used: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


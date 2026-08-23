from __future__ import annotations

import hashlib
import re

from rapidfuzz.fuzz import token_set_ratio

from ..models import ContentItem
from .normalize import canonicalize_url, normalize_title


def _paper_identity(item: ContentItem) -> str:
    if item.type != "paper":
        return ""
    metadata = item.raw_metadata
    for key in ("arxiv_id", "doi", "paper_id"):
        value = str(metadata.get(key, "")).strip().lower()
        if value:
            return f"{key}:{value.replace('arxiv:', '')}"
    match = re.search(r"(?:abs|pdf|papers)/([\d.]+(?:v\d+)?)", str(item.url))
    if match:
        return f"arxiv_id:{match.group(1).split('v')[0]}"
    return f"title:{normalize_title(item.title)}"


def _merge_paper(primary: ContentItem, duplicate: ContentItem) -> None:
    """保留一条论文，同时累积 HF 热度与 arXiv 原始元数据。"""
    primary.raw_metadata.setdefault("paper_sources", [primary.source_type])
    if duplicate.source_type not in primary.raw_metadata["paper_sources"]:
        primary.raw_metadata["paper_sources"].append(duplicate.source_type)
    primary.raw_metadata.setdefault("duplicate_urls", []).append(str(duplicate.url))
    primary.raw_metadata["trending"] = bool(primary.raw_metadata.get("trending") or duplicate.raw_metadata.get("trending"))
    primary.raw_metadata["hf_upvotes"] = max(int(primary.raw_metadata.get("hf_upvotes", 0) or 0), int(duplicate.raw_metadata.get("hf_upvotes", 0) or 0))
    primary.likes = max(primary.likes, duplicate.likes)
    if duplicate.raw_metadata.get("github_url") and not primary.raw_metadata.get("github_url"):
        primary.raw_metadata["github_url"] = duplicate.raw_metadata["github_url"]
    if duplicate.raw_metadata.get("categories"):
        primary.raw_metadata["categories"] = duplicate.raw_metadata["categories"]
    if duplicate.raw_metadata.get("arxiv_id") and not primary.raw_metadata.get("arxiv_id"):
        primary.raw_metadata["arxiv_id"] = duplicate.raw_metadata["arxiv_id"]
    if len(duplicate.content) > len(primary.content):
        primary.content = duplicate.content
        primary.summary = duplicate.summary
    if not primary.author and duplicate.author:
        primary.author = duplicate.author


def deduplicate(items: list[ContentItem], threshold: float = 88) -> list[ContentItem]:
    result: list[ContentItem] = []
    seen_urls: dict[str, ContentItem] = {}
    seen_papers: dict[str, ContentItem] = {}
    # 只按权威分排序，保持同分记录的输入顺序，避免毫秒级发布时间差导致代表记录不稳定。
    for item in [pair[1] for pair in sorted(enumerate(items), key=lambda pair: pair[1].source_score, reverse=True)]:
        canonical = canonicalize_url(str(item.url))
        item.raw_metadata["canonical_url"] = canonical
        paper_key = _paper_identity(item)
        if paper_key and paper_key in seen_papers:
            _merge_paper(seen_papers[paper_key], item)
            continue
        if canonical in seen_urls:
            if item.type == "paper" and seen_urls[canonical].type == "paper":
                _merge_paper(seen_urls[canonical], item)
            continue
        title = normalize_title(item.title)
        duplicate = next((candidate for candidate in result if candidate.type == item.type and token_set_ratio(title, normalize_title(candidate.title)) >= threshold), None)
        if duplicate:
            if item.type == "paper":
                _merge_paper(duplicate, item)
                seen_papers[paper_key] = duplicate
                continue
            duplicate.raw_metadata.setdefault("duplicate_urls", []).append(str(item.url))
            continue
        item.id = item.id or hashlib.sha1(canonical.encode()).hexdigest()[:20]
        seen_urls[canonical] = item
        if paper_key:
            seen_papers[paper_key] = item
        result.append(item)
    return result

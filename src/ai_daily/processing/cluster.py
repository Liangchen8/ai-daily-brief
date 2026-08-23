from __future__ import annotations

import hashlib
from datetime import timezone

from rapidfuzz.fuzz import token_set_ratio

from ..models import ContentItem, EventCluster
from .normalize import normalize_title


def _related(left: ContentItem, right: ContentItem, title_threshold: float, max_hours: int) -> bool:
    title_match = token_set_ratio(normalize_title(left.title), normalize_title(right.title)) >= title_threshold
    left_terms = set(normalize_title(left.title).split())
    right_terms = set(normalize_title(right.title).split())
    entities_match = len(left_terms & right_terms) >= 2
    hours = abs((left.published_at.astimezone(timezone.utc) - right.published_at.astimezone(timezone.utc)).total_seconds()) / 3600
    return (title_match or entities_match) and hours <= max_hours


def cluster_items(items: list[ContentItem], title_threshold: float = 84, max_hours: int = 72) -> list[EventCluster]:
    clusters: list[list[ContentItem]] = []
    for item in sorted(items, key=lambda x: x.published_at):
        matched = next((cluster for cluster in clusters if any(_related(item, existing, title_threshold, max_hours) for existing in cluster)), None)
        if matched is None:
            clusters.append([item])
        else:
            matched.append(item)
    result = []
    for index, cluster_items_list in enumerate(clusters, start=1):
        cluster_id = f"event-{hashlib.sha1('|'.join(sorted(item.id for item in cluster_items_list)).encode()).hexdigest()[:16]}"
        for item in cluster_items_list:
            item.cluster_id = cluster_id
        representative = max(cluster_items_list, key=lambda x: x.heat_score or x.source_score)
        result.append(EventCluster(id=cluster_id, items=cluster_items_list, title=representative.title, heat_score=max((x.heat_score for x in cluster_items_list), default=0)))
    return result


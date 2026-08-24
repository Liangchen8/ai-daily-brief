from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from .collectors import ArxivCollector, BlueskyCollector, HackerNewsCollector, HuggingFacePaperCollector, OfficialBlogCollector, RSSCollector, SemanticScholarCollector, XCollector
from .config import AppConfig
from .digest import DigestBuilder
from .llm.classifier import Classifier
from .llm.digest_analyzer import DigestAnalyzer
from .llm.news_analyzer import NewsAnalyzer
from .llm.paper_analyzer import PaperAnalyzer
from .llm.router import ModelRouter
from .llm.social_analyzer import SocialAnalyzer
from .models import ContentType
from .notifiers.feishu import FeishuNotifier
from .processing.cluster import cluster_items
from .processing.deduplicate import deduplicate
from .processing.filters import keyword_filter, time_filter
from .processing.ranking import rank_items
from .storage.history import HistoryStore
from .utils.logging import configure_logging


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="AI Daily Brief 中文 AI 情报日报")
    result.add_argument("--dry-run", action="store_true", help="生成本地 Markdown，不推送、不写历史")
    result.add_argument("--send", action="store_true", help="生成日报并发送飞书")
    result.add_argument("--debug", action="store_true", help="输出各阶段计数和排名细节")
    result.add_argument("--show-models", action="store_true", help="只显示当前模型配置")
    for task in ("filter", "news", "paper", "social", "digest"):
        result.add_argument(f"--{task}-provider", default="")
        result.add_argument(f"--{task}-model", default="")
    return result


def model_overrides(args) -> dict[str, dict[str, str]]:
    return {
        "filter": {"provider": args.filter_provider, "model": args.filter_model},
        "news_analysis": {"provider": args.news_provider, "model": args.news_model},
        "paper_analysis": {"provider": args.paper_provider, "model": args.paper_model},
        "social_analysis": {"provider": args.social_provider, "model": args.social_model},
        "digest": {"provider": args.digest_provider, "model": args.digest_model},
    }


def print_models(config: AppConfig, overrides: dict[str, dict[str, str]]) -> None:
    labels = {"filter": "Filter", "news_analysis": "News Analysis", "paper_analysis": "Paper Analysis", "social_analysis": "Social Analysis", "digest": "Digest"}
    for resolved in config.show_models(overrides):
        print(f"{labels[resolved.task]}:")
        print(f"Provider: {resolved.provider}")
        print(f"Model: {resolved.model}")
        print(f"Config Source: {resolved.source}")
        print()


def _log_source_health(records: list[dict[str, object]], logger: logging.Logger) -> None:
    grouped: dict[str, dict[str, int]] = {}
    for record in records:
        collector = str(record["collector"])
        status = str(record["status"])
        grouped.setdefault(collector, {})[status] = grouped.setdefault(collector, {}).get(status, 0) + 1
    summary = "; ".join(
        f"{collector}: " + ", ".join(f"{status}={count}" for status, count in sorted(statuses.items()))
        for collector, statuses in sorted(grouped.items())
    ) or "无采集记录"
    logger.info("Source Health | %s", summary)


def _source_health_counts(records: list[dict[str, object]]) -> dict[str, int]:
    statuses = [str(record.get("status", "")) for record in records]
    return {
        "healthy": sum(status == "success" for status in statuses),
        "zero_recent": sum(status == "ok_zero_recent_items" for status in statuses),
        "failed": sum(status in {"http_failed", "parse_failed"} for status in statuses),
        "disabled": sum(status.startswith("disabled") or status == "account_not_configured" for status in statuses),
    }


def daily_run_summary(
    *,
    metrics: dict[str, int | str],
    router: ModelRouter,
    health_records: list[dict[str, object]],
    output_path: Path,
    notify_status: str,
    history_updated: bool,
) -> str:
    usage = router.usage_summary()
    failures = int(metrics.get("analysis_failure_count", 0))
    health = _source_health_counts(health_records)
    fallback_calls = sum(1 for item in router.usage if item.fallback_used)
    return "\n".join([
        "Daily Run Summary",
        f"News: collected={metrics.get('news_collected', 0)} selected={metrics.get('news_selected', 0)} analyzed={metrics.get('news_analyzed', 0)}",
        f"Papers: collected={metrics.get('papers_collected', 0)} selected={metrics.get('papers_selected', 0)} analyzed={metrics.get('papers_analyzed', 0)} failed={metrics.get('papers_analysis_failed', 0)}",
        f"Social: collected={metrics.get('social_collected', 0)} selected={metrics.get('social_selected', 0)} analyzed={metrics.get('social_analyzed', 0)} failed={metrics.get('social_analysis_failed', 0)}",
        f"LLM: calls={usage['total_calls']} failed_calls={failures} fallback_calls={fallback_calls} input_tokens={usage['input_tokens']} output_tokens={usage['output_tokens']}",
        f"Sources: healthy={health['healthy']} zero_recent={health['zero_recent']} failed={health['failed']} disabled={health['disabled']}",
        f"Output: path={output_path}",
        f"Notify: {notify_status}",
        f"History: updated={str(history_updated).lower()}",
        f"analysis_failure_count={failures}",
    ])


async def deliver_report(
    *,
    send: bool,
    notifier: FeishuNotifier | None,
    report: str,
    history: HistoryStore,
    selected_items: list,
    selected_news: list,
    logger: logging.Logger,
) -> tuple[str, bool]:
    """仅在飞书完整发送成功后写入历史，失败与 dry-run 均不改动状态。"""
    if not send:
        return "dry_run", False
    try:
        assert notifier is not None
        await notifier.send(report)
    except Exception as exc:
        if logger.isEnabledFor(logging.DEBUG):
            logger.exception("push_status=failed error_type=%s", type(exc).__name__)
        else:
            logger.error("push_status=failed error_type=%s", type(exc).__name__)
        return "failed", False
    for item in selected_items:
        history.mark_sent(item_id=item.id, canonical_url=item.raw_metadata.get("canonical_url", str(item.url)), cluster_id=item.cluster_id, title=item.title, content=item.content, update=bool(item.raw_metadata.get("update")))
    for cluster in selected_news:
        history.mark_sent(item_id=cluster.id, canonical_url="", cluster_id=cluster.id, title=cluster.title, content="\n".join(item.content for item in cluster.items), update=cluster.update)
    try:
        return "sent", history.save()
    except OSError as exc:
        logger.error("history_status=failed error_type=%s", type(exc).__name__)
        return "sent_history_failed", False


async def _collect(config: AppConfig, logger: logging.Logger) -> tuple[list, list[dict[str, object]]]:
    collectors = [RSSCollector(config, logger), OfficialBlogCollector(config, logger), HackerNewsCollector(config, logger), HuggingFacePaperCollector(config, logger), ArxivCollector(config, logger), BlueskyCollector(config, logger), XCollector(config, logger)]
    batches = await asyncio.gather(*(collector.collect() for collector in collectors), return_exceptions=True)
    items = []
    for collector, batch in zip(collectors, batches):
        if isinstance(batch, Exception):
            logger.warning("collector=%s failed error_type=%s", collector.name, type(batch).__name__)
            continue
        logger.info("collector=%s raw_items_count=%s", collector.name, len(batch))
        items.extend(batch)
    health_records = [record for collector in collectors for record in collector.health_records]
    papers = [item for item in items if item.type == ContentType.PAPER]
    semantic = SemanticScholarCollector(config, logger)
    await semantic.enrich(papers)
    health_records.extend(semantic.health_records)
    _log_source_health(health_records, logger)
    return items, health_records


def _history_candidates(items: list, clusters: list, history: HistoryStore) -> tuple[list, list]:
    new_items = []
    for item in items:
        canonical = item.raw_metadata.get("canonical_url", str(item.url))
        is_new, updated = history.is_new_or_updated(item_id=item.id, canonical_url=canonical, cluster_id=item.cluster_id, title=item.title, content=item.content)
        if is_new:
            item.raw_metadata["update"] = updated
            new_items.append(item)
    new_clusters = []
    for cluster in clusters:
        content = "\n".join(item.content for item in cluster.items)
        is_new, updated = history.is_new_or_updated(item_id=cluster.id, canonical_url="", cluster_id=cluster.id, title=cluster.title, content=content)
        if is_new:
            cluster.update = updated
            new_clusters.append(cluster)
    return new_items, new_clusters


async def run(args) -> int:
    logger = configure_logging(args.debug)
    config = AppConfig()
    root = config.root
    logger.info(
        "project_root=%s config_dir=%s data_dir=%s output_dir=%s",
        config.root, config.config_dir, config.data_dir, config.output_dir,
    )
    overrides = model_overrides(args)
    if args.show_models:
        print_models(config, overrides)
        return 0
    if not args.dry_run and not args.send:
        args.dry_run = True
    metrics: dict[str, int | str] = {}
    items, health_records = await _collect(config, logger)
    metrics["collected"] = len(items)
    metrics["papers_collected"] = sum(item.type == ContentType.PAPER for item in items)
    metrics["news_collected"] = sum(item.type == ContentType.NEWS for item in items)
    metrics["social_collected"] = sum(item.type == ContentType.SOCIAL for item in items)
    items = [item for item in items if item.type == ContentType.PAPER] + time_filter(
        [item for item in items if item.type != ContentType.PAPER], hours=72
    )
    metrics["time_filtered"] = len(items)
    items = keyword_filter(items, config.high_topics, config.medium_topics)
    metrics["rule_filtered"] = len(items)
    dedup_threshold = float((config.ranking.get("dedup") or {}).get("title_similarity_threshold", 88))
    items = deduplicate(items, dedup_threshold)
    metrics["deduplicated"] = len(items)
    metrics["papers_ranked"] = sum(item.type == ContentType.PAPER for item in items)
    cluster_cfg = config.ranking.get("cluster") or {}
    clusters = cluster_items(items, float(cluster_cfg.get("title_similarity_threshold", 84)), int(cluster_cfg.get("max_hours_apart", 72)))
    for cluster in clusters:
        for item in cluster.items:
            item.raw_metadata["cluster_size"] = len(cluster.items) + len(item.raw_metadata.get("duplicate_urls", []))
    items = rank_items(items, config)
    for cluster in clusters:
        cluster.heat_score = max((item.heat_score for item in cluster.items), default=0)
    clusters.sort(key=lambda cluster: cluster.heat_score, reverse=True)
    metrics["clusters"] = len(clusters)
    history = HistoryStore(config.data_dir / "seen_items.json", logger)
    new_items, new_clusters = _history_candidates(items, clusters, history)
    candidates = new_items[: int(config.env("DRY_RUN_MAX_ITEMS", "60") or 60)]
    metrics["history_new_items"] = len(new_items)
    metrics["ranking_candidates"] = len(candidates)
    router = ModelRouter(config, logger)
    classifications = await Classifier(router, logger).classify(candidates)
    selected_ids = {result.item_id for result in classifications if result.relevant and result.importance >= 50}
    metrics["llm_filter_selected"] = len(selected_ids)
    if classifications:
        selected_items = [item for item in candidates if item.id in selected_ids]
    else:
        selected_items = []
    selected_clusters = [cluster for cluster in new_clusters if any(item.id in selected_ids for item in cluster.items)]
    selected_papers = [item for item in selected_items if item.type == ContentType.PAPER][:5]
    selected_social = [item for item in selected_items if item.type == ContentType.SOCIAL][:5]
    # 人物帖已通过来源与关键词规则；若批量初筛未选中，仍保留真实候选，避免社交栏目被静默清空。
    if not selected_social:
        selected_social = [item for item in candidates if item.type == ContentType.SOCIAL][:5]
    selected_news = selected_clusters[:5]
    # LLM 未配置时仍展示真实采集候选，但不把这些候选误当作已完成深度分析的内容。
    display_news = selected_news if classifications else new_clusters[:5]
    display_papers = selected_papers if classifications else [item for item in candidates if item.type == ContentType.PAPER][:5]
    display_social = selected_social if classifications else [item for item in candidates if item.type == ContentType.SOCIAL][:5]
    news_results = await asyncio.gather(*(NewsAnalyzer(router, logger).analyze(cluster) for cluster in selected_news))
    paper_results = await asyncio.gather(*(PaperAnalyzer(router, logger).analyze(item) for item in selected_papers))
    social_results = await asyncio.gather(*(SocialAnalyzer(router, logger).analyze(item) for item in selected_social))
    news_results = [result for result in news_results if result]
    paper_results = [result for result in paper_results if result]
    social_results = [result for result in social_results if result]
    metrics["news_analyzed"] = len(news_results)
    metrics["news_selected"] = len(selected_news)
    metrics["papers_selected"] = len(selected_papers)
    metrics["papers_analyzed"] = len(paper_results)
    metrics["social_analyzed"] = len(social_results)
    metrics["social_selected"] = len(selected_social)
    metrics["news_analysis_failed"] = max(0, len(selected_news) - len(news_results))
    metrics["papers_analysis_failed"] = max(0, len(selected_papers) - len(paper_results))
    metrics["social_analysis_failed"] = max(0, len(selected_social) - len(social_results))
    metrics["analysis_failure_count"] = sum(int(metrics[key]) for key in ("news_analysis_failed", "papers_analysis_failed", "social_analysis_failed"))
    digest_result = await DigestAnalyzer(router, logger).analyze(selected_news, selected_papers, selected_social) if selected_news or selected_papers or selected_social else None
    valid_cluster_ids = {cluster.id for cluster in selected_news}
    conflicts = digest_result.conflicts if digest_result else []
    conflicts = conflicts if len(social_results) >= 2 else []
    watchlist = digest_result.watchlist if digest_result else [cluster.title for cluster in display_news[:3]]
    report_date = datetime.now().astimezone().date()
    report = DigestBuilder().build(report_date=report_date, news_clusters=display_news, news_analyses=news_results, papers=display_papers, paper_analyses=paper_results, social=display_social, social_analyses=social_results, conflicts=conflicts, watchlist=watchlist, metrics=metrics | {"llm_usage": router.usage_summary()})
    output_path = config.output_dir / f"AI_Daily_Brief_{report_date.isoformat()}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    logger.info("output=%s", output_path)
    if args.debug:
        logger.info("ranking_top=%s", [(item.title[:80], item.source_score, item.engagement_score, item.cross_source_score, item.recency_score, item.relevance_score, item.heat_score) for item in items[:10]])
    notifier = FeishuNotifier(config.env("FEISHU_WEBHOOK_URL"), logger) if args.send else None
    notify_status, history_updated = await deliver_report(
        send=args.send, notifier=notifier, report=report, history=history,
        selected_items=selected_items, selected_news=selected_news, logger=logger,
    )
    logger.info(
        "%s",
        daily_run_summary(metrics=metrics, router=router, health_records=health_records, output_path=output_path,
                          notify_status=notify_status, history_updated=history_updated),
    )
    if notify_status in {"failed", "sent_history_failed"}:
        return 1
    if not items:
        logger.error("任务失败：所有核心 Collector 最终没有有效数据")
        return 1
    return 0


def main() -> None:
    args = parser().parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()

import logging
from pathlib import Path

from ai_daily.main import _log_source_health, daily_run_summary
from ai_daily.llm.router import ModelRouter


def test_source_health_summary(caplog):
    with caplog.at_level(logging.INFO):
        _log_source_health(
            [
                {"collector": "rss", "status": "success"},
                {"collector": "rss", "status": "ok_zero_recent_items"},
                {"collector": "x", "status": "disabled"},
            ],
            logging.getLogger("ai_daily.test"),
        )
    assert "Source Health" in caplog.text
    assert "rss: ok_zero_recent_items=1, success=1" in caplog.text


def test_daily_run_summary_contains_quality_fields(app_config, tmp_path):
    summary = daily_run_summary(
        metrics={"news_collected": 8, "news_selected": 3, "news_analyzed": 2, "papers_collected": 5, "papers_selected": 5, "papers_analyzed": 4, "papers_analysis_failed": 1, "social_collected": 2, "social_selected": 1, "social_analyzed": 1, "social_analysis_failed": 0, "analysis_failure_count": 1},
        router=ModelRouter(app_config), health_records=[{"status": "success"}, {"status": "ok_zero_recent_items"}, {"status": "http_failed"}, {"status": "disabled"}],
        output_path=Path(tmp_path / "report.md"), notify_status="dry_run", history_updated=False,
    )
    assert "Papers: collected=5 selected=5 analyzed=4 failed=1" in summary
    assert "Sources: healthy=1 zero_recent=1 failed=1 disabled=1" in summary
    assert "analysis_failure_count=1" in summary

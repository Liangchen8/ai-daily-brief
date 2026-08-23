from ai_daily.main import model_overrides, parser


def test_environment_overrides_yaml(app_config):
    config = app_config
    config.environ.update({"PAPER_ANALYSIS_PROVIDER": "deepseek", "PAPER_ANALYSIS_MODEL": "env-paper"})
    resolved = config.resolve_model("paper_analysis")
    assert resolved.provider == "deepseek"
    assert resolved.model == "env-paper"
    assert resolved.source == "environment"


def test_cli_overrides_environment(app_config):
    app_config.environ.update({"PAPER_ANALYSIS_PROVIDER": "deepseek", "PAPER_ANALYSIS_MODEL": "env-paper"})
    resolved = app_config.resolve_model("paper_analysis", {"provider": "openai", "model": "cli-paper"})
    assert (resolved.provider, resolved.model, resolved.source) == ("openai", "cli-paper", "cli")


def test_cli_parser_maps_task_overrides():
    args = parser().parse_args(["--paper-provider", "deepseek", "--paper-model", "model-x"])
    overrides = model_overrides(args)
    assert overrides["paper_analysis"] == {"provider": "deepseek", "model": "model-x"}


def test_workflow_requires_python_312_and_persists_only_history(project_root):
    workflow = (project_root / ".github/workflows/daily_digest.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.12"' in workflow
    assert "Python executable" in workflow
    assert "python -m pytest" in workflow
    assert "git add data/seen_items.json" in workflow
    assert "git add data/seen_items.json output/" not in workflow
    assert "[skip ci]" in workflow

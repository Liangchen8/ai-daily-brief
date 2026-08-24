import sys
from pathlib import Path

import pytest

from ai_daily.config import AppConfig, ConfigurationError, resolve_config_dir
from ai_daily.main import model_overrides, parser


def _write_config_dir(root: Path) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "sources.yaml").write_text("[]\n", encoding="utf-8")
    (config_dir / "people.yaml").write_text("[]\n", encoding="utf-8")
    (config_dir / "topics.yaml").write_text("high_priority: []\nmedium_priority: []\n", encoding="utf-8")
    (config_dir / "ranking.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "models.yaml").write_text("{}\n", encoding="utf-8")
    return config_dir


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
    assert "working-directory: ${{ github.workspace }}" in workflow
    assert "AI_DAILY_CONFIG_DIR: ${{ github.workspace }}/config" in workflow
    assert "AI_DAILY_DATA_DIR: ${{ github.workspace }}/data" in workflow
    assert "AI_DAILY_OUTPUT_DIR: ${{ github.workspace }}/output" in workflow


def test_config_dir_uses_current_working_directory(tmp_path, monkeypatch):
    config_dir = _write_config_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert resolve_config_dir(environ={}, cwd=tmp_path) == config_dir


def test_environment_config_dir_has_priority(tmp_path, monkeypatch):
    cwd_config = _write_config_dir(tmp_path / "cwd")
    env_config = _write_config_dir(tmp_path / "environment")
    monkeypatch.chdir(tmp_path / "cwd")
    assert resolve_config_dir(environ={"AI_DAILY_CONFIG_DIR": str(env_config)}, cwd=tmp_path / "cwd") == env_config
    assert cwd_config != env_config


def test_config_dir_never_uses_sys_prefix_when_cwd_has_config(tmp_path):
    config_dir = _write_config_dir(tmp_path)
    resolved = resolve_config_dir(
        environ={}, cwd=tmp_path, source_file=Path(sys.prefix) / "lib/python3.12/site-packages/ai_daily/config.py",
    )
    assert resolved == config_dir
    assert not str(resolved).startswith(sys.prefix)


def test_github_workspace_config_and_runtime_dirs(tmp_path):
    workspace = tmp_path / "github-workspace"
    config_dir = _write_config_dir(workspace)
    app = AppConfig(environ={
        "AI_DAILY_CONFIG_DIR": str(config_dir),
        "AI_DAILY_DATA_DIR": str(workspace / "data"),
        "AI_DAILY_OUTPUT_DIR": str(workspace / "output"),
    })
    assert app.root == workspace
    assert app.config_dir == config_dir
    assert app.data_dir == workspace / "data"
    assert app.output_dir == workspace / "output"


def test_missing_config_file_raises_clear_configuration_error(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    with pytest.raises(ConfigurationError, match=r"Missing config file: .*sources.yaml.*config_dir="):
        AppConfig(environ={"AI_DAILY_CONFIG_DIR": str(config_dir)})


def test_local_project_root_configuration_remains_available(project_root, app_config):
    assert app_config.root == project_root
    assert app_config.config_dir == project_root / "config"

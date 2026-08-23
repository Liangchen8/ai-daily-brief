from pathlib import Path

import pytest

from ai_daily.config import AppConfig


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def app_config(project_root):
    return AppConfig(project_root, environ={})


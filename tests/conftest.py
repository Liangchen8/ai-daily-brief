from pathlib import Path
import socket

import pytest

from ai_daily.config import AppConfig


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def app_config(project_root):
    return AppConfig(project_root, environ={})


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    """单元测试只能使用显式 Mock；手动 dry-run 才允许联网。"""
    def denied(*args, **kwargs):
        raise AssertionError("pytest 禁止访问真实外部网络，请为 Collector 提供 Mock")

    monkeypatch.setattr(socket.socket, "connect", denied)

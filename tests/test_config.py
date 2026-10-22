"""Tests for app.config defaults and environment overrides."""

from __future__ import annotations

import os

import pytest

from app.config import Settings, get_settings

ENV_KEYS = (
    "SAMPLE_MODE",
    "METERLESS_BASE_URL",
    "METERLESS_API_KEY",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "MODEL_NAME",
    "ZETARIS_URL",
    "ZETARIS_API_KEY",
    "MAX_QUERY_ROWS",
    "QUERY_TIMEOUT_SECONDS",
    "MODEL_TIMEOUT_SECONDS",
    "LOG_DIR",
)


@pytest.fixture
def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_config_defaults_with_empty_environment(clear_settings_env: None) -> None:
    settings = Settings()
    assert settings.sample_mode is True
    assert settings.meterless_base_url == "http://127.0.0.1:8088/v1"
    assert settings.meterless_api_key == ""
    assert settings.nvidia_api_key == ""
    assert settings.nvidia_base_url == ""
    assert settings.model_name == ""
    assert settings.zetaris_url == ""
    assert settings.zetaris_api_key == ""
    assert settings.max_query_rows == 5000
    assert settings.query_timeout_seconds == 30
    assert settings.model_timeout_seconds == 60
    assert settings.log_dir == "logs"


def test_config_picks_up_overridden_variable(
    clear_settings_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_QUERY_ROWS", "123")
    monkeypatch.setenv("SAMPLE_MODE", "false")
    settings = get_settings()
    assert settings.max_query_rows == 123
    assert settings.sample_mode is False


def test_import_does_not_require_env_keys(clear_settings_env: None) -> None:
    for key in ENV_KEYS:
        assert key not in os.environ
    settings = get_settings()
    assert settings is not None

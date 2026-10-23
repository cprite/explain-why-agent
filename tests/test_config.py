"""Tests for app.config defaults and environment overrides."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.config as config_module
from app.config import Settings, get_settings

ROOT = Path(__file__).resolve().parents[1]

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


def test_empty_env_values_fall_back_to_defaults(
    clear_settings_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAMPLE_MODE", "")
    monkeypatch.setenv("MAX_QUERY_ROWS", "")
    settings = get_settings()
    assert settings.sample_mode is True
    assert settings.max_query_rows == 5000

    env = {**os.environ, "SAMPLE_MODE": "", "MAX_QUERY_ROWS": ""}
    result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "test"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    # No recorded model replies for "test": a structured error, still in sample mode by default.
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sample_mode"] is True


def test_import_does_not_require_env_keys(
    clear_settings_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ENV_KEYS:
        assert key not in os.environ
        monkeypatch.delenv(key, raising=False)
    reloaded = importlib.reload(config_module)
    settings = reloaded.get_settings()
    assert settings.sample_mode is True
    assert settings.max_query_rows == 5000

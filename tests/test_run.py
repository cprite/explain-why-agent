"""Tests for run.py with the settings variables cleared (defaults: sample mode)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SETTINGS_ENV_KEYS = (
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


def test_run_py_defaults_to_sample_mode_with_settings_cleared() -> None:
    env = {key: value for key, value in os.environ.items() if key not in SETTINGS_ENV_KEYS}
    result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "test"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    # "test" has no recorded model replies, so sample mode answers with a structured cache-miss error.
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["question"] == "test"
    assert payload["sample_mode"] is True
    assert payload["error"]["code"] == "cache_miss"

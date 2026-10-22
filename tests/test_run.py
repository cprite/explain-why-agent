"""Tests for the placeholder run.py CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_py_prints_placeholder_json() -> None:
    env = {**os.environ, "SAMPLE_MODE": "true"}
    result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "test"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "not_implemented"
    assert payload["question"] == "test"
    assert "sample_mode" in payload
    assert payload["sample_mode"] is True

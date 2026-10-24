"""run.py picks the investigation loop: the Markovian orchestrator by default, the simple loop with
`--loop simple` or `LOOP=simple`. Sample mode, no network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_py(*args: str, loop_env: str | None = None) -> tuple[int, dict]:
    env = {key: value for key, value in os.environ.items() if key not in ("LOOP", "SAMPLE_MODE")}
    if loop_env is not None:
        env["LOOP"] = loop_env
    done = subprocess.run([sys.executable, str(ROOT / "run.py"), *args], check=False, capture_output=True,
                          text=True, cwd=ROOT, env=env, timeout=300)
    return done.returncode, json.loads(done.stdout)


def test_default_is_the_markovian_orchestrator() -> None:
    code, payload = run_py("test", "--sample", "--run-id", "t-loop-default")
    assert code == 1
    assert payload["stop_reason"] == "error"  # only the orchestrator sets stop_reason
    assert payload["error"]["code"] == "cache_miss"


@pytest.mark.parametrize(("args", "loop_env"), [(("--loop", "simple"), None), ((), "simple"),
                                                (("--loop", "simple"), "markovian")])
def test_simple_loop_by_flag_or_environment(args: tuple[str, ...], loop_env: str | None) -> None:
    code, payload = run_py("test", "--sample", "--run-id", "t-loop-simple", *args, loop_env=loop_env)
    assert code == 1
    assert "stop_reason" not in payload  # the simple loop's result keeps its Sprint 2 shape
    assert payload["error"]["code"] == "cache_miss"


def test_flag_wins_over_the_environment() -> None:
    _, payload = run_py("test", "--sample", "--run-id", "t-loop-flag", "--loop", "markovian", loop_env="simple")
    assert payload["stop_reason"] == "error"


def test_bad_loop_variable_is_reported() -> None:
    code, payload = run_py("test", "--sample", "--run-id", "t-loop-bad", loop_env="chunky")
    assert code == 2
    assert payload["error"]["code"] == "bad_loop" and "chunky" in payload["error"]["message"]

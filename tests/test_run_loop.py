"""run.py picks the investigation loop: the Markovian orchestrator by default, the simple loop with
`--loop simple` or `LOOP=simple`. Sample mode, no network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.schemas import Result

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


@pytest.mark.parametrize("timeout_s", ["0.005", "0.02", "0.05", "0.1"])
def test_tiny_run_timeout_at_the_cli_returns_the_timeout_result(timeout_s: str) -> None:
    """A deadline that lands during a query or schema read still gives the timeout result and a clean exit.

    The sample run takes about 0.1-0.2 s, so on a fast machine the larger limits may let it finish;
    that is the only other outcome allowed. 0.005 s always lands inside the run.
    """
    env = {key: value for key, value in os.environ.items() if key not in ("LOOP", "SAMPLE_MODE")}
    env["MARKOVIAN_RUN_TIMEOUT_S"] = timeout_s
    question = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"
    done = subprocess.run([sys.executable, str(ROOT / "run.py"), question, "--sample", "--run-id",
                           f"t-tiny-timeout-{timeout_s}"], check=False, capture_output=True, text=True, cwd=ROOT,
                          env=env, timeout=120)
    assert "Traceback" not in done.stderr and "terminate called" not in done.stderr, done.stderr[-2000:]
    payload = json.loads(done.stdout)  # the exit used to be 134 (DuckDB abort) with an `internal` error
    Result.model_validate(payload)
    if timeout_s == "0.005" or done.returncode != 0:
        assert done.returncode == 1, (done.returncode, done.stderr[-2000:])
        assert payload["stop_reason"] == "timeout"
        assert payload["error"]["code"] == "timeout"
    else:
        assert payload["stop_reason"] == "completed"


# --- The shared run helper (app/runner.py) and the HTTP API use the same loop selection ----------

PLAN_CHECK_QUESTION = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"


@pytest.fixture
def api_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.config import Settings

    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    return tmp_path / "logs"


def test_select_loop_flag_wins_and_bad_names_raise() -> None:
    from app.config import Settings
    from app.runner import select_loop

    assert select_loop(Settings(loop="markovian")) == "markovian"
    assert select_loop(Settings(loop=" Simple ")) == "simple"
    assert select_loop(Settings(loop="simple"), "markovian") == "markovian"
    with pytest.raises(ValueError, match="chunky"):
        select_loop(Settings(loop="chunky"))


def test_post_run_uses_the_orchestrator_by_default_and_stores_its_result(api_logs: Path) -> None:
    from fastapi.testclient import TestClient

    import app.api.main as api

    body = {"run_id": "api-markovian", "input": {"query": PLAN_CHECK_QUESTION}, "options": {"sample_mode": True}}
    response = TestClient(api.app).post("/run", json=body)
    assert response.status_code == 200, response.text
    served = response.json()
    assert served["status"] == "success" and served["stop_reason"] == "completed"
    assert (api_logs / "result-api-markovian.json").is_file()
    stored = TestClient(api.app).get("/runs/api-markovian")
    assert stored.status_code == 200 and stored.json() == served
    trace = [json.loads(line) for line in (api_logs / "trace-api-markovian.jsonl").read_text().splitlines()]
    assert any(line.get("agent") == "Orchestrator" and line.get("action") == "chunk" for line in trace)


def test_post_run_follows_loop_simple(api_logs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import app.api.main as api

    monkeypatch.setenv("LOOP", "simple")
    body = {"input": {"query": "Why did order volume spike on 24 November 2017?"}, "options": {"sample_mode": True}}
    response = TestClient(api.app).post("/run", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"
    assert "stop_reason" not in response.json()  # the simple loop's Sprint 2 shape, also over HTTP


def test_result_without_stop_reason_keeps_the_sprint2_shape() -> None:
    base = {"run_id": "r", "status": "success", "question": "q", "determinable": False, "trace_id": "r",
            "log_file": "logs/trace-r.jsonl", "execution_time_seconds": 0.0}
    assert "stop_reason" not in Result(**base).model_dump(mode="json")
    assert "stop_reason" not in json.loads(Result(**base).model_dump_json())
    assert Result(**base, stop_reason="completed").model_dump(mode="json")["stop_reason"] == "completed"
    assert "stop_reason" in Result.model_json_schema()["properties"]

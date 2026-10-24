"""Tests for eval/run_eval.py: the runner (timeouts, crashes, run cap), the report and the CLI in
sample mode. No network: sample mode serves model replies from the committed cache."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.schemas import Result

ROOT = Path(__file__).resolve().parents[1]
# eval/ is not a package: its directory goes on the path before importing from it.
sys.path.insert(0, str(ROOT / "eval"))

import run_eval

DAY1 = "Why did order volume spike on 24 November 2017?"
RUN_SPECIFIC = {"run_id", "trace_id", "log_file", "query_log", "execution_time_seconds"}


def sample_env(tmp_path: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key not in {"SAMPLE_MODE", "RECORD_CACHE", "LLM_CACHE_DIR", "EVAL_QUESTION_TIMEOUT_SECONDS",
                          "EVAL_TOTAL_TIMEOUT_SECONDS"}}
    env["LOG_DIR"] = str(tmp_path / "logs")
    return env


def test_load_incidents_merges_wrong_explanation_types() -> None:
    incidents = run_eval.load_incidents()
    assert len(incidents) == 10
    by_id = {item["id"]: item for item in incidents}
    assert by_id["incident-01"]["wrong_explanation_type"] == "data_artefact"
    assert by_id["incident-09"]["wrong_explanation_type"] is None


def test_timeouts_come_from_the_environment_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_QUESTION_TIMEOUT_SECONDS", raising=False)
    assert run_eval.env_seconds("EVAL_QUESTION_TIMEOUT_SECONDS", 600) == 600
    monkeypatch.setenv("EVAL_QUESTION_TIMEOUT_SECONDS", "45")
    assert run_eval.env_seconds("EVAL_QUESTION_TIMEOUT_SECONDS", 600) == 45
    monkeypatch.setenv("EVAL_QUESTION_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError):
        run_eval.env_seconds("EVAL_QUESTION_TIMEOUT_SECONDS", 600)
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "EVAL_QUESTION_TIMEOUT_SECONDS=600" in example
    assert "EVAL_TOTAL_TIMEOUT_SECONDS=3600" in example


def test_crash_and_timeout_are_errors_and_the_run_continues() -> None:
    incidents = run_eval.load_incidents()[:3]
    calls = []

    def runner(question: str, run_id: str, sample: bool, timeout: float):
        calls.append((run_id, timeout))
        if run_id.endswith("incident-01"):
            raise RuntimeError("boom")
        if run_id.endswith("incident-02"):
            return None, {"code": "timeout", "message": "no result within 5 s"}
        return None, {"code": "crashed", "message": "exit code 1: Traceback"}

    rows = run_eval.evaluate(incidents, sample=True, question_timeout=5, total_timeout=100,
                             run_prefix="eval-t", runner=runner)
    assert [row["status"] for row in rows] == ["error", "error", "error"]
    assert [row["error"]["code"] for row in rows] == ["crashed", "timeout", "crashed"]
    assert "RuntimeError: boom" in rows[0]["error"]["message"]
    assert [run_id for run_id, _ in calls] == ["eval-t-incident-01", "eval-t-incident-02", "eval-t-incident-03"]
    assert all(timeout <= 5 for _, timeout in calls)
    assert run_eval.score_line(run_eval.summarise(rows)) == "Score: 0/3 (answered 0, no_cache 0, errors 3)"


def test_total_cap_stops_starting_questions() -> None:
    incidents = run_eval.load_incidents()[:3]

    def slow(question: str, run_id: str, sample: bool, timeout: float):
        time.sleep(0.3)
        return None, {"code": "timeout", "message": "slow"}

    rows = run_eval.evaluate(incidents, sample=True, question_timeout=5, total_timeout=0.2,
                             run_prefix="eval-t", runner=slow)
    assert rows[0]["error"]["code"] == "timeout"
    assert [row["error"]["code"] for row in rows[1:]] == ["run_cap_reached", "run_cap_reached"]


def test_run_question_kills_a_question_at_its_timeout() -> None:
    started = time.monotonic()
    result, error = run_eval.run_question(DAY1, "eval-timeout-test", True, 0.05)
    assert result is None
    assert error["code"] == "timeout"
    assert time.monotonic() - started < 10


def test_incident_01_through_the_eval_matches_the_recorded_day1_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The eval wiring gives the same incident-01 answer as run.py on main (committed result.json)."""
    for key, value in sample_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    result, error = run_eval.run_question(DAY1, "eval-day1-test", True, 120)
    assert error is None, error
    recorded = Result.model_validate_json((ROOT / "result.json").read_text(encoding="utf-8"))
    assert result.model_dump(exclude=RUN_SPECIFIC) == recorded.model_dump(exclude=RUN_SPECIFIC)
    assert (tmp_path / "logs" / "trace-eval-day1-test.jsonl").is_file()
    assert run_eval.trace_tokens(result.log_file) > 0


def test_cli_sample_run_prints_table_score_and_writes_json(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run_eval.py"), "--sample", "--only", "incident-01", "incident-04",
         "incident-09", "--timeout", "120"],
        capture_output=True, text=True, cwd=ROOT, env=sample_env(tmp_path), check=False, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[-1] == "Score: 0/3 (answered 1, no_cache 2, errors 0)"
    assert any(line.startswith("incident-01  not_found") for line in lines)
    assert "cause_type_not_in_vocabulary: freight_cost (incident-04)" in proc.stdout
    assert "rank-1 cause mix_shift not in ['volume']" in proc.stdout

    reports = list((tmp_path / "logs").glob("eval-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["sample_mode"] is True
    assert report["score_line"] == lines[-1]
    assert report["cause_type_not_in_vocabulary"] == {"incident-04": ["freight_cost"]}
    rows = {row["id"]: row for row in report["incidents"]}
    assert [rows[i]["status"] for i in ("incident-01", "incident-04", "incident-09")] == [
        "not_found", "no_cache", "no_cache"]
    assert rows["incident-04"]["cause_type_not_in_vocabulary"] == ["freight_cost"]
    for row in rows.values():
        assert row["run_id"].startswith("eval-") and row["run_id"].endswith(row["id"])
        assert Path(row["trace_file"]).name == f"trace-{row['run_id']}.jsonl"
        assert Path(row["trace_file"]).is_file()
    assert rows["incident-01"]["tokens"] > 0
    assert rows["incident-01"]["checks"]["segment"]["pass"] is True


def test_cli_rejects_unknown_incident_id(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run_eval.py"), "--sample", "--only", "incident-99"],
        capture_output=True, text=True, cwd=ROOT, env=sample_env(tmp_path), check=False, timeout=60,
    )
    assert proc.returncode == 2
    assert "incident-99" in proc.stderr

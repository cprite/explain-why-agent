"""Tests for the thin end-to-end slice: Planner, Investigator, Reporter, the loop and run.py.

Every model reply comes from the scripted stub (app/llm/stub.py) or the committed sample-mode
cache; the agents, the DuckDB queries and the loop run for real.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.data.local import LocalDataLayer
from app.llm.generator import GenerationResult, Generator
from app.llm.stub import ScriptedModel
from app.loop import run_investigation
from app.schemas import Result
from app.trace import TraceWriter

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Why did order volume spike on 24 November 2017?"
ANSWER_KEY = ROOT / "eval" / "answer_key.json"


def settings_for(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "sample_mode": False,
        "log_dir": str(tmp_path / "logs"),
        "llm_cache_dir": str(tmp_path / "cache"),
        "max_agent_rounds": 8,
        "max_tool_calls": 20,
        "meterless_runtime_token": "",
        "nvidia_api_key": "",
    }
    values.update(overrides)
    return Settings(**values)


def run(tmp_path: Path, generate: Any, run_id: str = "t", **overrides: Any) -> tuple[Result, LocalDataLayer]:
    settings = settings_for(tmp_path, **overrides)
    data = LocalDataLayer(run_id=run_id, log_dir=tmp_path / "logs", sources=("orders",), settings=settings)
    try:
        result = run_investigation(QUESTION, run_id=run_id, generate=generate, data=data, settings=settings)
    finally:
        data.close()
    return result, data


def test_stub_run_every_cause_has_evidence_in_query_log(tmp_path: Path) -> None:
    result, data = run(tmp_path, ScriptedModel())
    assert result.status == "success", result.error
    Result.model_validate(result.model_dump())
    assert result.causes, "expected at least one cause"
    logged = {line["query_id"]: line for line in data.log.read()}
    for cause in result.causes:
        assert cause.evidence
        for item in cause.evidence:
            assert item.query_id in logged
            assert logged[item.query_id]["status"] == "ok"
        for statement in cause.statements:
            assert set(statement.query_ids) <= set(logged)
    assert {s.kind for s in result.causes[0].statements} == {"measured", "inferred"}
    trace_path = tmp_path / "logs" / "trace-t.jsonl"
    assert trace_path.is_file()
    assert result.log_file.endswith("trace-t.jsonl")
    assert result.trace_id == "t"
    actions = [(line["agent"], line["action"]) for line in TraceWriter(tmp_path / "logs", "t").read()]
    assert actions[0] == ("Loop", "start") and actions[-1] == ("Loop", "finish")
    assert ("Planner", "delegate") in actions and ("Reporter", "report") in actions
    for line in TraceWriter(tmp_path / "logs", "t").read():
        for key in ("timestamp", "agent", "action", "target_agent", "input_summary", "output_summary",
                    "status", "retry_count"):
            assert key in line


class BadSqlFirst(ScriptedModel):
    """Writes a broken statement for the first hypothesis' first SQL proposal (or every time)."""

    def __init__(self, always: bool = False) -> None:
        super().__init__()
        self.always = always
        self.broken = 0

    def _reply_SqlProposal(self, data: dict[str, Any]) -> dict[str, Any] | None:
        if data["task"].get("id") == "H1" and (self.always or self.broken == 0):
            self.broken += 1
            return {"sql": "SELECT no_such_column FROM orders.orders", "sources": ["orders"], "rationale": "x"}
        return super()._reply_SqlProposal(data)


def test_failed_sql_is_repaired_once_and_traced(tmp_path: Path) -> None:
    model = BadSqlFirst()
    result, data = run(tmp_path, model)
    assert result.status == "success"
    trace = TraceWriter(tmp_path / "logs", "t").read()
    repairs = [line for line in trace if line["action"] == "repair_sql"]
    assert len(repairs) == 1
    assert repairs[0]["retry_count"] == 1
    assert "no_such_column" in repairs[0]["previous_error"]
    reruns = [line for line in trace if line["action"] == "run_query" and line["retry_count"] == 1]
    assert len(reruns) == 1 and reruns[0]["status"] == "ok"
    statuses = [line["status"] for line in data.log.read()]
    assert statuses.count("failed") == 1
    repair_input = [c for c in model.calls if c["schema"] == "SqlProposal" and "previous_error" in c["messages"][-1]["content"]]
    assert len(repair_input) == 1


def test_sql_failing_twice_is_reported_not_retried_again(tmp_path: Path) -> None:
    result, data = run(tmp_path, BadSqlFirst(always=True))
    assert result.status == "success"
    assert sum(line["status"] == "failed" for line in data.log.read()) == 2
    assert any("query failed after repair" in item for item in result.limitations)
    assert all(cause.type != "volume" for cause in result.causes)


class NeverFinishes(ScriptedModel):
    """A Reporter that always wants one more hypothesis tested."""

    def _reply_ReportDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "complete": False,
            "determinable": False,
            "follow_up": [
                {"id": "X", "family": "volume", "priority": 1, "statement": "Test once more.",
                 "test": {"description": "Orders per day again.", "sources": ["orders"]}}
            ],
        }


def test_loop_stops_at_max_agent_rounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_AGENT_ROUNDS", "9")
    assert Settings().max_agent_rounds == 9
    model = NeverFinishes()
    settings = Settings(sample_mode=False, log_dir=str(tmp_path / "logs"))
    with LocalDataLayer(run_id="cap", log_dir=tmp_path / "logs", sources=("orders",), settings=settings) as data:
        result = run_investigation(QUESTION, run_id="cap", generate=model, data=data, settings=settings)
    assert result.status == "error"
    assert result.error is not None and result.error.code == "max_agent_rounds"
    assert result.causes == [] and result.determinable is False
    trace = TraceWriter(tmp_path / "logs", "cap").read()
    finish = trace[-1]
    assert finish["action"] == "finish" and finish["rounds_used"] <= 9
    rounds = sum(line["action"] in ("plan", "report") for line in trace) + sum(
        line["action"] == "delegate" and line["input_summary"] != "change_check" for line in trace
    )
    assert rounds <= 9
    assert sum(call["schema"] == "ReportDraft" for call in model.calls) >= 2


def test_tool_call_cap_stops_queries(tmp_path: Path) -> None:
    result, data = run(tmp_path, ScriptedModel(), max_tool_calls=2)
    assert len(data.log.read()) == 2
    assert any("Tool-call cap reached" in item for item in result.limitations)


def test_generator_error_becomes_structured_error_result(tmp_path: Path) -> None:
    def broken(messages: Any, **kwargs: Any) -> GenerationResult:
        return GenerationResult(ok=False, error={"code": "offline", "message": "runtime unreachable"})

    result, _ = run(tmp_path, broken)
    assert result.status == "error"
    assert result.error.code == "offline"
    assert (tmp_path / "logs" / "trace-t.jsonl").is_file()


def test_sample_mode_uses_committed_cache(tmp_path: Path) -> None:
    settings = Settings(sample_mode=True, log_dir=str(tmp_path / "logs"))
    generator = Generator(settings)
    with LocalDataLayer(run_id="sample", log_dir=tmp_path / "logs", settings=settings) as data:
        result = run_investigation(QUESTION, run_id="sample", generate=generator, data=data, settings=settings)
        logged = {line["query_id"] for line in data.log.read()}
    assert result.status == "success", result.error
    assert result.sample_mode is True
    assert result.causes and result.causes[0].evidence
    assert all(e.query_id in logged for c in result.causes for e in c.evidence)
    trace = TraceWriter(tmp_path / "logs", "sample").read()
    model_calls = [line for line in trace if line["action"] == "model_call"]
    assert model_calls and all(line["provider"] == "cache" and line["status"] == "ok" for line in model_calls)
    assert all(line["recorded_with"] == "meterless" for line in model_calls)


def test_committed_cache_entries_are_real_meterless_recordings() -> None:
    """The committed sample cache is a live run through Meterless (Nightshift) on Nemotron.

    Since Sprint 8 the cache also holds entries recorded with the scripted stub for the Markovian plan
    check (`recorded_with: stub`, provider `stub`), until they are re-recorded through Nightshift. Those
    are checked to be marked as such; every other entry, including all of the Day 1 question's, must
    be a live Meterless recording.
    """
    entries = list((ROOT / "data" / "sample" / "llm_cache").glob("*.json"))
    assert entries
    live = 0
    for path in entries:
        entry = json.loads(path.read_text())
        if entry.get("recorded_with") == "stub":
            assert entry["provider"] == "stub" and entry["model_routed"] == "scripted-stub", path.name
            assert QUESTION not in json.dumps(entry["messages"]), path.name  # Day 1 stays a live recording
            continue
        live += 1
        assert entry["provider"] == "meterless", path.name
        assert "nemotron" in (entry["model_routed"] or ""), path.name
        assert entry["receipt_id"], path.name
    assert live >= 15  # the 23 Oct Day 1 recording


# --- no incident-specific wording ---------------------------------------------------------------


def _answer_key_needles() -> list[tuple[str, re.Pattern[str]]]:
    needles: list[tuple[str, re.Pattern[str]]] = []
    for incident in json.loads(ANSWER_KEY.read_text()):
        for key in ("window_start", "window_end"):
            day = date.fromisoformat(incident[key])
            for text in (day.isoformat(), f"{day.day} {day:%B %Y}", f"{day:%B} {day.day}", f"{day:%B %Y}",
                         f"{day:%Y-%m}"):
                needles.append((text, re.compile(re.escape(text), re.IGNORECASE)))
        value = str(incident["segment"]["value"])
        if len(value) <= 3:  # state codes: whole word, case-sensitive
            needles.append((value, re.compile(rf"\b{re.escape(value)}\b")))
        else:
            needles.append((value, re.compile(re.escape(value), re.IGNORECASE)))
    return needles


AGENT_FILES = sorted(
    [*(ROOT / "app" / "agents").rglob("*.py"), *(ROOT / "app" / "agents" / "prompts").glob("*.md"),
     ROOT / "app" / "loop.py", ROOT / "app" / "llm" / "stub.py", ROOT / "run.py"]
)


def test_prompts_and_agent_code_contain_no_incident_specifics() -> None:
    prompts = list((ROOT / "app" / "agents" / "prompts").glob("*.md"))
    assert len(prompts) >= 4
    hits = []
    for path in AGENT_FILES:
        text = path.read_text()
        for label, pattern in _answer_key_needles():
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {label}")
    assert hits == []


def test_agents_never_reference_the_answer_key() -> None:
    for path in [*(ROOT / "app").rglob("*.py"), *(ROOT / "app").rglob("*.md"), ROOT / "run.py"]:
        assert "answer_key" not in path.read_text(), path


# --- run.py -----------------------------------------------------------------------------------


def _run_cli(*args: str, sample: bool = True) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("METERLESS_", "NVIDIA_", "MAX_"))}
    env["SAMPLE_MODE"] = "true" if sample else "false"
    return subprocess.run(
        [sys.executable, "run.py", *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        timeout=300,
    )


def test_run_py_success_exit_zero() -> None:
    out = _run_cli(QUESTION, "--run-id", "pytest-cli-ok")
    assert out.returncode == 0, out.stdout + out.stderr
    payload = json.loads(out.stdout)
    assert payload["status"] == "success"
    assert payload["causes"][0]["evidence"]
    assert (ROOT / payload["log_file"]).is_file()
    assert not (ROOT / "output_examples" / "pytest-cli-ok.json").exists()


def test_run_py_error_exit_nonzero_with_structured_error() -> None:
    out = _run_cli("Why did something nobody recorded happen?", "--run-id", "pytest-cli-miss")
    assert out.returncode == 1
    payload = json.loads(out.stdout)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "cache_miss"
    assert "needs a model key" in payload["error"]["message"]


def test_run_py_bad_run_id_exit_two() -> None:
    out = _run_cli(QUESTION, "--run-id", "../escape")
    assert out.returncode == 2
    assert json.loads(out.stdout)["error"]["code"] == "bad_run_id"


def test_run_py_save_writes_output_example_only_when_asked() -> None:
    target = ROOT / "output_examples" / "pytest-cli-save.json"
    try:
        out = _run_cli(QUESTION, "--run-id", "pytest-cli-save", "--save")
        assert out.returncode == 0, out.stderr
        assert Result.model_validate_json(target.read_text()).status == "success"
    finally:
        target.unlink(missing_ok=True)

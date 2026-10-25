"""Tests for the Markovian orchestrator (app/engines/markovian/orchestrator.py, build-plan task 12).

Model replies come from the scripted stub (app/llm/stub.py), wrappers around it that fail or stall on
purpose, or the committed sample-mode cache; the agents, the DuckDB queries, the World Model and the
chunk manager run for real. No network.

These are the Sprint 8 mechanics: `run()` pins the no-op critic (`critic=critic_hook`) unless a test
passes its own. The real Critic and the branches are tested in tests/test_critic.py.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.data.local import LocalDataLayer
from app.engines.markovian.config import MarkovianConfig
from app.engines.markovian.orchestrator import CriticRequest, critic_hook, run_markovian
from app.engines.world_model.context import Intent
from app.llm.generator import GenerationResult, Generator
from app.llm.stub import ScriptedModel
from app.schemas import Result, Verdict
from app.trace import TraceWriter

DAY1 = "Why did order volume spike on 24 November 2017?"
PLAN_CHECK = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"
CHUNK_FIELDS = ("chunk", "hypothesis_id", "queries", "carryover_step", "projected_chars", "actual_chars",
                "chunk_budget_chars")


def settings_for(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "sample_mode": False,
        "log_dir": str(tmp_path / "logs"),
        "llm_cache_dir": str(tmp_path / "cache"),
        "max_tool_calls": 20,
        "meterless_runtime_token": "",
        "nvidia_api_key": "",
    }
    values.update(overrides)
    return Settings(**values)


def config(**overrides: Any) -> MarkovianConfig:
    values: dict[str, Any] = {"max_chunks": 8, "chunk_budget_chars": 12000, "carryover_budget_chars": 1200,
                              "chunk_timeout_seconds": 60.0, "compression_timeout_seconds": 5.0,
                              "run_timeout_s": 120.0}
    values.update(overrides)
    return MarkovianConfig(**values)


def run(
    tmp_path: Path,
    generate: Any,
    *,
    question: str = DAY1,
    run_id: str = "m",
    cfg: MarkovianConfig | None = None,
    settings: Settings | None = None,
    sources: tuple[str, ...] | None = ("orders",),
    **kwargs: Any,
) -> Result:
    settings = settings or settings_for(tmp_path)
    kwargs.setdefault("critic", critic_hook)
    layer_kwargs = {"sources": sources} if sources else {}
    with LocalDataLayer(run_id=run_id, log_dir=tmp_path / "logs", settings=settings, **layer_kwargs) as data:
        result = run_markovian(question, run_id=run_id, generate=generate, data=data, settings=settings,
                               config=cfg or config(), log_dir=tmp_path / "logs", **kwargs)
    Result.model_validate(result.model_dump())  # every stop path is schema-valid
    return result


def trace(tmp_path: Path, run_id: str = "m") -> list[dict[str, Any]]:
    return TraceWriter(tmp_path / "logs", run_id).read()


def chunk_lines(tmp_path: Path, run_id: str = "m") -> list[dict[str, Any]]:
    return [line for line in trace(tmp_path, run_id) if line["agent"] == "Orchestrator" and line["action"] == "chunk"]


def finish_line(tmp_path: Path, run_id: str = "m") -> dict[str, Any]:
    return [line for line in trace(tmp_path, run_id) if line["agent"] == "Orchestrator" and line["action"] == "finish"][-1]


class Scripted(ScriptedModel):
    """The scripted stub with optional overrides per schema name: a function of the parsed reply."""

    def __init__(self, **overrides: Any) -> None:
        super().__init__()
        self.overrides = overrides

    def __call__(self, messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> Any:
        name = schema.__name__ if schema else None
        override = self.overrides.get(name)
        if callable(override) and getattr(override, "replaces_call", False):
            return override(messages)
        result = super().__call__(messages, schema=schema, role=role, run_id=run_id)
        if callable(override) and result.ok:
            reply = override(json.loads(result.content), messages)
            return GenerationResult(ok=True, content=json.dumps(reply), parsed=schema.model_validate(reply).model_dump(
                mode="json"), provider="stub")
        return result


def failing(code: str = "offline") -> Any:
    def call(messages: Any) -> GenerationResult:
        return GenerationResult(ok=False, provider="stub", error={"code": code, "message": f"stub {code}"})

    call.replaces_call = True  # type: ignore[attr-defined]
    return call


# --- completed --------------------------------------------------------------------------------------


def test_completed_run_tests_every_hypothesis_in_priority_order(tmp_path: Path) -> None:
    result = run(tmp_path, ScriptedModel())
    assert result.status == "success", result.error
    assert result.stop_reason == "completed"
    assert result.causes and result.causes[0].evidence
    chunks = chunk_lines(tmp_path)
    assert [c["hypothesis_id"] for c in chunks] == [None, "H1", "H2", "H3", "H4"]
    assert [c["kind"] for c in chunks] == ["plan", "round", "round", "round", "round"]
    assert result.token_report.standard_estimate > result.token_report.markovian_actual > 0
    actions = [(line["agent"], line["action"]) for line in trace(tmp_path)]
    assert actions[0] == ("Orchestrator", "start") and actions[-1] == ("Orchestrator", "finish")
    assert ("WorldModel", "ingest") in actions and ("Reporter", "report") in actions


def test_plan_check_question_with_the_stub_ranks_carrier_transit_first(tmp_path: Path) -> None:
    result = run(tmp_path, ScriptedModel(), question=PLAN_CHECK)
    assert result.stop_reason == "completed"
    assert result.change is not None and result.change.significant is True
    assert result.causes[0].type == "logistics_delay"
    assert {r.type for r in result.ruled_out} == {"volume", "single_seller", "data_artefact"}


def test_sample_mode_plan_check_question_replays_the_recorded_cache(tmp_path: Path) -> None:
    """The committed stub-recorded cache answers every call of the plan-check question (no network)."""
    settings = settings_for(tmp_path, sample_mode=True, llm_cache_dir="data/sample/llm_cache")
    for run_id in ("s1", "another-run-id"):  # prompts do not depend on the run id
        generator = Generator(settings)
        result = run(tmp_path, generator, question=PLAN_CHECK, run_id=run_id, settings=settings, sources=None,
                     critic=None)  # the real Critic: the cache is recorded with it (Sprint 9)
        assert result.status == "success", result.error
        assert result.stop_reason == "completed"
        assert result.causes[0].type == "logistics_delay"
        calls = [line for line in trace(tmp_path, run_id) if line["action"] == "model_call"]
        assert calls and all(line["status"] == "ok" and line["recorded_with"] == "stub" for line in calls)


# --- stop paths -------------------------------------------------------------------------------------


@pytest.mark.parametrize("max_chunks", [1, 2, 3, 4])
def test_max_chunks_stops_with_a_valid_result_and_never_exceeds_the_cap(tmp_path: Path, max_chunks: int) -> None:
    result = run(tmp_path, ScriptedModel(), cfg=config(max_chunks=max_chunks))
    assert result.stop_reason == "max_chunks"
    chunks = chunk_lines(tmp_path)
    assert len(chunks) == max_chunks
    assert finish_line(tmp_path)["chunks_used"] == max_chunks
    assert any("MARKOVIAN_MAX_CHUNKS" in note for note in result.limitations)
    if max_chunks > 1:  # at least one hypothesis tested: the Reporter still writes an answer
        assert result.status == "success"


def test_cap_never_exceeded_with_follow_ups_requested_every_time(tmp_path: Path) -> None:
    """A Reporter that always asks for more stops at the chunk cap, never above it."""

    def always_more(reply: dict[str, Any], messages: Any) -> dict[str, Any]:
        follow = {"id": "H9", "family": "mix_shift", "priority": 9, "statement": "A category mix shift.",
                  "test": {"description": "Category shares.", "sources": ["orders"]}}
        return {**reply, "complete": False, "follow_up": [follow]}

    result = run(tmp_path, Scripted(ReportDraft=always_more), cfg=config(max_chunks=6))
    assert result.stop_reason == "max_chunks"
    assert len(chunk_lines(tmp_path)) <= 6


def test_run_timeout_with_a_slow_stub_returns_promptly(tmp_path: Path) -> None:
    release = threading.Event()
    stub = ScriptedModel()

    def slow(messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> GenerationResult:
        if schema is not None and schema.__name__ == "SqlProposal":
            release.wait(10)
        return stub(messages, schema=schema, role=role, run_id=run_id)

    started = time.monotonic()
    try:
        result = run(tmp_path, slow, cfg=config(run_timeout_s=1.0, chunk_timeout_seconds=30.0))
    finally:
        release.set()
    elapsed = time.monotonic() - started
    assert result.stop_reason == "timeout"
    assert result.status == "error" and result.error is not None and result.error.code == "timeout"
    assert "MARKOVIAN_RUN_TIMEOUT_S=1" in result.error.message
    assert elapsed < 6, elapsed  # the 1 s limit plus data loading, not the 10 s stall
    assert finish_line(tmp_path)["stop_reason"] == "timeout"


def test_chunk_timeout_stops_the_run(tmp_path: Path) -> None:
    release = threading.Event()
    stub = ScriptedModel()

    def slow(messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> GenerationResult:
        if schema is not None and schema.__name__ == "ObservationDraft":
            release.wait(10)
        return stub(messages, schema=schema, role=role, run_id=run_id)

    try:
        result = run(tmp_path, slow, cfg=config(run_timeout_s=60.0, chunk_timeout_seconds=0.5,
                                                compression_timeout_seconds=0.5))
    finally:
        release.set()
    assert result.stop_reason == "timeout"
    assert result.error is not None and "MARKOVIAN_CHUNK_TIMEOUT_SECONDS=0.5" in result.error.message


class _StallingSchemaRead(LocalDataLayer):
    """A local layer whose schema read stalls until it is interrupted (a slow describe on a busy database)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.interrupted = threading.Event()
        self.inside = 0

    def interrupt(self) -> None:
        self.interrupted.set()
        super().interrupt()

    def describe(self, source: str) -> Any:
        self.inside += 1
        try:
            self.interrupted.wait(10)
            return super().describe(source)
        finally:
            self.inside -= 1


def test_timeout_during_a_schema_read_leaves_the_data_layer_before_returning(tmp_path: Path) -> None:
    """On a timeout the worker is out of the data layer when the run returns, so the caller can close it."""
    settings = settings_for(tmp_path)
    data = _StallingSchemaRead(run_id="m", log_dir=tmp_path / "logs", settings=settings, sources=("orders",))
    started = time.monotonic()
    try:
        result = run_markovian(DAY1, run_id="m", generate=ScriptedModel(), data=data, settings=settings,
                               config=config(run_timeout_s=0.5), log_dir=tmp_path / "logs")
        assert data.interrupted.is_set()
        assert data.inside == 0
    finally:
        data.close()  # raised "connection is busy with another call" when the worker was still inside
    assert time.monotonic() - started < 6
    Result.model_validate(result.model_dump())
    assert result.stop_reason == "timeout"
    assert result.error is not None and result.error.code == "timeout"


def test_no_significant_change_means_no_hypotheses(tmp_path: Path) -> None:
    def not_real(reply: dict[str, Any], messages: Any) -> dict[str, Any]:
        if '"kind":"change_check"' in messages[-1]["content"]:
            return {**reply, "supports": False}
        return reply

    def no_spread(reply: dict[str, Any], messages: Any) -> dict[str, Any]:
        if '"kind":"change_check"' in messages[-1]["content"]:
            return {**reply, "sql": re.sub(r", round\(stddev_samp\(m\).*? AS n_baseline FROM d", " FROM d",
                                           reply["sql"])}
        return reply

    # 111 orders against 106.9 a day: within the relative rule (Sprint 11c), so with no spread the
    # Investigator's "not real" still ends the run.
    result = run(tmp_path, Scripted(ObservationDraft=not_real, SqlProposal=no_spread),
                 question="Why did order volume rise on 21 September 2017?")
    assert result.stop_reason == "no_hypotheses"
    # Since Sprint 9 this is the no-significant-change branch: a determinable answer with no causes.
    # The stub's change check has a spread; the run ends here when the change is within it (or, as here
    # with the spread removed, when the Investigator reads the change as not real).
    assert result.status == "success" and result.determinable is True and result.causes == []
    assert result.change is not None and result.change.significant is False and result.change.spread is None
    assert result.summary and result.summary.startswith("No significant change")
    assert len(chunk_lines(tmp_path)) == 1

    # Day 1 (1176 orders against 136.6 a day) with the same "not real" reading and no spread: the change
    # is far beyond the relative rule, so the hypotheses are tested (Sprint 11c, incident-10's cause).
    day1 = run(tmp_path, Scripted(ObservationDraft=not_real, SqlProposal=no_spread), run_id="m2")
    assert day1.stop_reason != "no_hypotheses" and day1.change is not None and day1.change.significant is None


@pytest.mark.parametrize("schema", ["Plan", "ReportDraft"])
def test_generator_error_on_plan_or_report_stops_with_error(tmp_path: Path, schema: str) -> None:
    result = run(tmp_path, Scripted(**{schema: failing("retries_exhausted")}))
    assert result.stop_reason == "error"
    assert result.status == "error" and result.error is not None and result.error.code == "retries_exhausted"
    assert finish_line(tmp_path)["stop_reason"] == "error"


def test_generator_error_on_an_investigation_is_noted_and_the_run_goes_on(tmp_path: Path) -> None:
    result = run(tmp_path, Scripted(SqlProposal=failing()))
    assert result.stop_reason == "completed"
    assert any(note.startswith("Not tested: H1") for note in result.limitations)


def test_generator_that_raises_ends_in_an_error_result(tmp_path: Path) -> None:
    def broken(*args: Any, **kwargs: Any) -> GenerationResult:
        raise RuntimeError("provider exploded")

    result = run(tmp_path, broken)
    assert result.stop_reason == "error"
    assert result.error is not None and result.error.code == "internal"
    assert "provider exploded" in result.error.message


def test_invalid_markovian_environment_is_an_error_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKOVIAN_MAX_CHUNKS", "0")
    settings = settings_for(tmp_path)
    with LocalDataLayer(run_id="m", log_dir=tmp_path / "logs", sources=("orders",), settings=settings) as data:
        result = run_markovian(DAY1, run_id="m", generate=ScriptedModel(), data=data, settings=settings,
                               log_dir=tmp_path / "logs")
    assert result.stop_reason == "error" and result.error is not None
    assert result.error.code == "invalid_config" and "MARKOVIAN_MAX_CHUNKS" in result.error.message


# --- budgets, trace and logs ------------------------------------------------------------------------


@pytest.mark.parametrize(("chunk_budget", "carryover_budget"), [(1000, 300), (2500, 600), (12000, 1200)])
def test_every_chunk_input_stays_within_the_chunk_budget(tmp_path: Path, chunk_budget: int,
                                                         carryover_budget: int) -> None:
    run(tmp_path, ScriptedModel(), question=PLAN_CHECK,
        cfg=config(chunk_budget_chars=chunk_budget, carryover_budget_chars=carryover_budget))
    chunks = chunk_lines(tmp_path)
    assert len(chunks) == 5
    for chunk in chunks:
        assert chunk["chunk_budget_chars"] == chunk_budget
        assert 0 < chunk["projected_chars"] <= chunk_budget, chunk
    delegate = [line for line in trace(tmp_path) if line["action"] == "delegate" and line["target_agent"] == "Reporter"]
    assert delegate and delegate[0]["projected_chars"] <= chunk_budget


def test_trace_has_one_entry_per_chunk_with_the_required_fields(tmp_path: Path) -> None:
    run(tmp_path, ScriptedModel())
    chunks = chunk_lines(tmp_path)
    assert [c["chunk"] for c in chunks] == list(range(1, len(chunks) + 1))
    assert finish_line(tmp_path)["chunks_used"] == len(chunks)
    for chunk in chunks:
        for name in CHUNK_FIELDS:
            assert name in chunk, name
        assert chunk["actual_chars"] > chunk["projected_chars"]  # agent prompts and schemas come on top
        assert chunk["queries"] and all(q.startswith("q") for q in chunk["queries"])
    assert chunks[0]["carryover_step"] is None
    assert all(c["carryover_step"] == "explicit_state" for c in chunks[1:])
    markovian = (tmp_path / "logs" / "markovian-m.jsonl").read_text().splitlines()
    assert len(markovian) == len(chunks)
    world = (tmp_path / "logs" / "world-m.jsonl").read_text().splitlines()
    assert world and all(json.loads(line)["run_id"] == "m" for line in world)


def test_rounds_left_in_the_carryover_comes_from_the_chunk_manager(tmp_path: Path) -> None:
    run(tmp_path, ScriptedModel(), cfg=config(max_chunks=7))
    for line in (tmp_path / "logs" / "markovian-m.jsonl").read_text().splitlines():
        record = json.loads(line)
        assert record["carryover_out"]["rounds_left"] == 7 - record["index"]


def test_chunk_inputs_carry_the_world_model_evidence_and_the_state(tmp_path: Path) -> None:
    stub = ScriptedModel()
    run(tmp_path, stub)
    sql_calls = [c for c in stub.calls if c["schema"] == "SqlProposal"]
    first, last = (json.loads(c["messages"][1]["content"][len("INPUT:"):])["chunk"] for c in (sql_calls[0], sql_calls[-1]))
    assert first.startswith("Goal: Answer: " + DAY1) and "(hypothesis)" in first and "State so far" not in first
    assert "State so far:\nRounds left: 4" in last and "(observation)" in last
    report = next(c for c in stub.calls if c["schema"] == "ReportDraft")
    assert "chunk" in json.loads(report["messages"][1]["content"][len("INPUT:"):])


# --- the Critic seam --------------------------------------------------------------------------------


def test_default_critic_hook_gives_no_verdict() -> None:
    assert critic_hook.__name__ == "critic_hook"
    assert critic_hook(None) is None  # type: ignore[arg-type]


def test_a_critic_verdict_changes_the_ranking(tmp_path: Path) -> None:
    seen: list[CriticRequest] = []

    def critic(request: CriticRequest) -> Verdict | None:
        seen.append(request)
        if request.hypothesis.id == "H1":
            return Verdict(hypothesis_id="H1", verdict="refuted", reason="concentrated in one region")
        return None

    run(tmp_path, ScriptedModel(), critic=critic)
    assert [r.hypothesis.id for r in seen] == ["H1", "H2", "H3", "H4"]
    assert all(r.chunk_text.startswith("Goal:") for r in seen)
    last = json.loads((tmp_path / "logs" / "markovian-m.jsonl").read_text().splitlines()[-1])
    assert "H1" in {item["id"] for item in last["carryover_out"]["ruled_out"]}
    verdicts = [line for line in trace(tmp_path) if line["agent"] == "Critic"]
    assert len(verdicts) == 1 and verdicts[0]["verdict"] == "refuted"


def test_selection_reasons_do_not_name_the_run_id(tmp_path: Path) -> None:
    """The critique payload a Critic builds names the run; the orchestrator's evidence never does."""
    reasons: list[str] = []

    def critic(request: CriticRequest) -> Verdict | None:
        payload = request.context_builder.build(Intent("critique", hypothesis_id=request.hypothesis_entity_id), 4000)
        reasons.extend(item["selection_reason"] for item in payload["items"])
        return None

    stub = ScriptedModel()
    run(tmp_path, stub, run_id="run-id-xyz", critic=critic)
    assert any("run run-id-xyz" in reason for reason in reasons)  # the builder itself names the run
    assert all("run-id-xyz" not in json.dumps(call["messages"]) for call in stub.calls)

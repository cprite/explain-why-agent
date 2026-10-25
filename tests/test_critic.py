"""Tests for the Critic (app/agents/critic.py) and the three branches in the Markovian orchestrator
(build-plan tasks 13+14), plus the two Sprint 8 review fixes carried into Sprint 9.

The model is the scripted stub (app/llm/stub.py), with its Critic reply overridden per test where a
specific verdict is needed; the agents, DuckDB queries, World Model and chunk manager run for real.
Sample-mode tests replay the committed cache. No network: the deadline test uses an httpx
MockTransport.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agents.critic import Critic, critic_input
from app.agents.prompts import PROMPT_DIR, load_prompt
from app.config import REPO_ROOT, Settings
from app.data.local import LocalDataLayer
from app.engines.markovian.config import MarkovianConfig
from app.engines.markovian.orchestrator import CriticRequest, critic_hook, run_markovian
from app.engines.world_model.context import ContextBuilder
from app.engines.world_model.ingest import IngestPipeline
from app.engines.world_model.store import WorldStore
from app.llm.generator import CALL_THREAD_NAME, GenerationResult, Generator
from app.llm.stub import ScriptedModel
from app.schemas import (
    CHECK_NAMES,
    HYPOTHESIS_FAMILIES,
    CritiqueDraft,
    Hypothesis,
    Observation,
    Plan,
    Result,
)
from app.trace import TraceWriter

LATENESS = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"
NO_CHANGE = "Why did order volume rise on 21 September 2017?"
ANSWER_KEY = {item["id"]: item["question"] for item in json.loads((REPO_ROOT / "eval" / "answer_key.json").read_text())}


def settings_for(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {"sample_mode": False, "log_dir": str(tmp_path / "logs"),
                              "llm_cache_dir": str(tmp_path / "cache"), "max_tool_calls": 20,
                              "meterless_runtime_token": "", "nvidia_api_key": ""}
    values.update(overrides)
    return Settings(**values)


def config(**overrides: Any) -> MarkovianConfig:
    values: dict[str, Any] = {"max_chunks": 8, "chunk_budget_chars": 12000, "carryover_budget_chars": 1200,
                              "chunk_timeout_seconds": 60.0, "compression_timeout_seconds": 5.0,
                              "run_timeout_s": 120.0}
    values.update(overrides)
    return MarkovianConfig(**values)


def run(tmp_path: Path, generate: Any, *, question: str = LATENESS, run_id: str = "c", cfg: MarkovianConfig | None = None,
        settings: Settings | None = None, **kwargs: Any) -> Result:
    """One orchestrated run with the real Critic (unless `critic=` is given), all sources loaded."""
    settings = settings or settings_for(tmp_path)
    with LocalDataLayer(run_id=run_id, log_dir=tmp_path / "logs", settings=settings) as data:
        result = run_markovian(question, run_id=run_id, generate=generate, data=data, settings=settings,
                               config=cfg or config(), log_dir=tmp_path / "logs", **kwargs)
    Result.model_validate(result.model_dump())
    return result


def trace(tmp_path: Path, run_id: str = "c") -> list[dict[str, Any]]:
    return TraceWriter(tmp_path / "logs", run_id).read()


def critiques(tmp_path: Path, run_id: str = "c") -> list[dict[str, Any]]:
    return [line for line in trace(tmp_path, run_id) if line["agent"] == "Critic" and line["action"] == "critique"]


def branches(tmp_path: Path, run_id: str = "c") -> list[dict[str, Any]]:
    return [line for line in trace(tmp_path, run_id) if line["agent"] == "Orchestrator" and line["action"] == "branch"]


def chunks(tmp_path: Path, run_id: str = "c") -> list[dict[str, Any]]:
    return [line for line in trace(tmp_path, run_id) if line["agent"] == "Orchestrator" and line["action"] == "chunk"]


def draft(total: tuple[int, int, int] = (3, 3, 2), *, contradicted: bool = False, follow_up: list[str] | None = None,
          sample_size: int | None = None, reason: str = "scripted critique") -> dict[str, Any]:
    return {
        "checks": [{"name": name, "outcome": "passed", "detail": "scripted"} for name in CHECK_NAMES],
        "scores": dict(zip(("supported_by_data", "explains_size_and_timing", "alternatives_excluded"), total,
                           strict=True)),
        "contradicted": contradicted, "reason": reason, "follow_up_tests": follow_up or [],
        "sample_size": sample_size, "observation_ids": [],
    }


class CriticScript(ScriptedModel):
    """The scripted stub whose Critic replies come from `script(hypothesis_id, attempt)`; the other
    agents answer as the stub does. Records every Critic request body."""

    def __init__(self, script: Any) -> None:
        super().__init__()
        self.script = script
        self.critic_inputs: list[dict[str, Any]] = []

    def __call__(self, messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> Any:
        if schema is CritiqueDraft:
            body = json.loads(messages[-1]["content"][len("INPUT:"):])
            self.critic_inputs.append(body)
            self.calls.append({"role": role, "schema": "CritiqueDraft", "messages": messages})
            reply = self.script(body["hypothesis"]["id"], body["attempt"])
            if isinstance(reply, GenerationResult):
                return reply
            return GenerationResult(ok=True, content=json.dumps(reply),
                                    parsed=CritiqueDraft.model_validate(reply).model_dump(mode="json"), provider="stub")
        return super().__call__(messages, schema=schema, role=role, run_id=run_id)


# --- the Critic on its own ------------------------------------------------------------------------


def critic_request(tmp_path: Path, generate: Any, *, observation: Observation | None = None,
                   change_row: dict[str, Any] | None = None, run_id: str = "unit-run") -> CriticRequest:
    store = WorldStore(":memory:")
    hypothesis = Hypothesis(id="H1", family="logistics_delay", statement="Transit took longer.", priority=1,
                            test={"description": "transit days", "sources": ["orders"]})
    entity_id = IngestPipeline(store, settings=settings_for(tmp_path)).put_hypothesis(hypothesis, run_id=run_id)
    plan = Plan(question="Why?", metric="late share", segment="all", window={"start": "2018-05-28", "end": "2018-06-04"},
                baseline_window={"start": "2018-04-30", "end": "2018-05-28"}, change_check={"description": "late share"},
                hypotheses=[hypothesis, hypothesis.model_copy(update={"id": "H2", "priority": 2})])
    obs = observation or Observation(id="obs-1", hypothesis_id="H1", query_id="q002", source="orders", sql="SELECT 1",
                                     finding="Transit 10.2 days against 6.7.", value=10.2, baseline=6.7, effect=0.52,
                                     supports=True)
    change = Observation(id="obs-0", query_id="q001", source="orders", sql="SELECT 1", finding="Late share up.",
                         value=0.1, baseline=0.015, effect=5.7, supports=True)
    return CriticRequest(run_id=run_id, plan=plan, hypothesis=hypothesis, hypothesis_entity_id=entity_id,
                         observation=obs, chunk_text="Goal: explain.", context_builder=ContextBuilder(store),
                         budget_chars=4000, generate=generate, change=change, change_row=change_row)


def fixed(*replies: Any) -> Any:
    """A generator that returns the given replies in turn (dicts become valid results)."""
    calls: list[dict[str, Any]] = []

    def generate(messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> GenerationResult:
        calls.append({"messages": messages, "schema": schema, "role": role})
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, GenerationResult):
            return reply
        return GenerationResult(ok=True, content=json.dumps(reply), parsed=reply, provider="stub")

    generate.calls = calls  # type: ignore[attr-defined]
    return generate


def test_critic_is_its_own_prompt_and_call_on_the_critic_lane(tmp_path: Path) -> None:
    generate = fixed(draft((3, 3, 2)))
    verdict = Critic(min_sample_size=30)(critic_request(tmp_path, generate))
    assert verdict.verdict == "supported" and verdict.total_score == 8
    call = generate.calls[0]  # type: ignore[attr-defined]
    assert call["role"] == "critic" and call["schema"] is CritiqueDraft
    assert call["messages"][0]["content"] == load_prompt("critic")
    body = json.loads(call["messages"][1]["content"][len("INPUT:"):])
    assert body["checks"] == list(CHECK_NAMES) and body["min_sample_size"] == 30 and body["attempt"] == 1
    assert [item["type"] for item in body["evidence"]["items"]] == ["hypothesis"]  # the critique payload
    assert "unit-run" not in call["messages"][1]["content"]  # the run id never reaches the prompt
    assert [c.name for c in verdict.checks] == list(CHECK_NAMES)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (draft((3, 2, 2)), "supported"),  # 7 of 9
        (draft((2, 2, 2), follow_up=["split by state"]), "insufficient"),  # 6 of 9
        (draft((3, 3, 3), contradicted=True, reason="transit fell"), "refuted"),  # contradiction wins
    ],
)
def test_verdict_follows_the_seven_of_nine_rule(tmp_path: Path, reply: dict[str, Any], expected: str) -> None:
    verdict = Critic(min_sample_size=30)(critic_request(tmp_path, fixed(reply)))
    assert verdict.verdict == expected
    if expected == "insufficient":
        assert verdict.follow_up_tests == ["split by state"]
    if expected == "refuted":
        assert verdict.reason == "transit fell" and verdict.query_ids == ["q002"]


def test_small_sample_is_flagged_and_insufficient(tmp_path: Path) -> None:
    verdict = Critic(min_sample_size=30)(critic_request(tmp_path, fixed(draft((3, 3, 3), sample_size=3))))
    assert verdict.verdict == "insufficient" and verdict.sample_too_small and verdict.sample_size == 3
    assert "Sample too small: 3 records" in verdict.reason


def test_invalid_reply_is_retried_once_then_insufficient(tmp_path: Path) -> None:
    bad = GenerationResult(ok=False, error={"code": "invalid_json", "message": "not JSON"})
    missing_check = {**draft(), "checks": draft()["checks"][:4]}  # parsed but fails CritiqueDraft validation
    generate = fixed(bad, missing_check, draft())
    verdict = Critic()(critic_request(tmp_path, generate))
    assert len(generate.calls) == 2  # type: ignore[attr-defined]  # one retry, no third call
    assert verdict.verdict == "insufficient" and verdict.retry_count == 1
    assert "invalid twice" in verdict.reason

    generate = fixed(bad, draft((3, 3, 2)))
    verdict = Critic()(critic_request(tmp_path, generate))
    assert verdict.verdict == "supported" and verdict.retry_count == 1
    assert len(generate.calls) == 2  # type: ignore[attr-defined]


def test_critique_draft_names_every_check_once() -> None:
    with pytest.raises(ValueError, match="exactly once"):
        CritiqueDraft.model_validate({**draft(), "checks": draft()["checks"] * 2})
    with pytest.raises(ValueError):
        CritiqueDraft.model_validate({**draft(), "scores": {"supported_by_data": 4, "explains_size_and_timing": 0,
                                                            "alternatives_excluded": 0}})


def test_critic_input_carries_the_follow_up_on_the_second_critique(tmp_path: Path) -> None:
    request = critic_request(tmp_path, fixed(draft()))
    follow = Observation(id="obs-5", hypothesis_id="H1", query_id="q007", source="orders", sql="SELECT 1",
                         finding="Second half: 11 days.", value=11.0, baseline=6.7, effect=0.64, supports=True)
    second = CriticRequest(**{**request.__dict__, "attempt": 2, "follow_up_tests": ("timing check",),
                              "follow_up": (follow,)})
    body = critic_input(second, 30)
    assert body["follow_up"] == {"requested": ["timing check"], "results": [
        {"id": "obs-5", "query_id": "q007", "source": "orders", "finding": "Second half: 11 days.", "value": 11.0,
         "baseline": 6.7, "effect": 0.64, "supports": True}]}
    verdict = Critic()(second)
    assert set(verdict.query_ids) == {"q002", "q007"} and set(verdict.observation_ids) == {"obs-1", "obs-5"}


# --- the Critic in the orchestrator (acceptance criterion 2) --------------------------------------------


def test_supported(tmp_path: Path) -> None:
    result = run(tmp_path, ScriptedModel())  # the stub's Critic: transit +52 % supports H1
    assert result.status == "success" and result.determinable and result.stop_reason == "completed"
    assert [c.type for c in result.causes] == ["logistics_delay"]
    lines = critiques(tmp_path)
    assert [(line["hypothesis_id"], line["verdict"]) for line in lines] == [
        ("H1", "supported"), ("H2", "refuted"), ("H3", "refuted"), ("H4", "refuted")]
    assert result.summary and result.summary.startswith("Most likely cause (logistics_delay)")
    refuted = {r.type: r for r in result.ruled_out}
    assert set(refuted) == {"volume", "single_seller", "data_artefact"}
    assert all(r.evidence and r.why.startswith(("H2:", "H3:", "H4:")) for r in refuted.values())


def test_insufficient_then_follow_up_then_supported(tmp_path: Path) -> None:
    def script(hid: str, attempt: int) -> dict[str, Any]:
        if hid == "H1":
            return draft((2, 1, 2), follow_up=["transit days on the second half of the week"]) if attempt == 1 \
                else draft((3, 3, 2), reason="the follow-up confirms it")
        return draft((0, 1, 1), contradicted=True)

    model = CriticScript(script)
    result = run(tmp_path, model)
    assert [c.type for c in result.causes] == ["logistics_delay"] and result.determinable
    lines = critiques(tmp_path)
    h1 = [line for line in lines if line["hypothesis_id"] == "H1"]
    assert [(line["attempt"], line["verdict"]) for line in h1] == [(1, "insufficient"), (2, "supported")]
    assert h1[0]["follow_up_tests"] == ["transit days on the second half of the week"]
    answered = h1[1]["follow_up_results"]
    assert len(answered) == 1 and answered[0]["query_ids"] and answered[0]["observation_id"]
    # The revision is its own chunk; the Investigator got the Critic's test as its task.
    kinds = [(c["kind"], c["hypothesis_id"]) for c in chunks(tmp_path)]
    assert kinds[:3] == [("plan", None), ("round", "H1"), ("revision", "H1")]
    sql_requests = [c for c in model.calls if c["schema"] == "SqlProposal"]
    assert any("Follow-up requested by the Critic: transit days on the second half" in c["messages"][-1]["content"]
               for c in sql_requests)
    # The second critique saw the follow-up result.
    second = next(b for b in model.critic_inputs if b["hypothesis"]["id"] == "H1" and b["attempt"] == 2)
    assert second["follow_up"]["results"] and second["follow_up"]["results"][0]["query_id"] in answered[0]["query_ids"]
    # The follow-up query's rows are in the World Model, tied to H1.
    world = [json.loads(line) for line in (tmp_path / "logs" / "world-c.jsonl").read_text().splitlines()]
    assert any(row["target_type"] == "observation" and not row["noop"] for row in world)


def test_insufficient_twice_then_demoted(tmp_path: Path) -> None:
    def script(hid: str, attempt: int) -> dict[str, Any]:
        if hid == "H1":
            return draft((2, 1, 1), follow_up=["split transit by state"])
        if hid == "H2":
            return draft((3, 3, 2))
        return draft((0, 1, 1), contradicted=True)

    model = CriticScript(script)
    result = run(tmp_path, model)
    h1 = [line for line in critiques(tmp_path) if line["hypothesis_id"] == "H1"]
    assert [(line["attempt"], line["verdict"]) for line in h1] == [(1, "insufficient"), (2, "insufficient")]
    promotion = next(b for b in branches(tmp_path) if b["branch"] == "promotion")
    assert promotion["numbers"]["from"] == "H1" and promotion["numbers"]["to"] == "H2"
    assert "demoted" in promotion["why"]
    assert any(item.startswith("Unconfirmed: H1 (logistics_delay)") and "split transit by state" in item
               for item in result.limitations)
    # Only H2 was supported: H1's demotion keeps its cause out of the answer.
    assert all(c.type != "logistics_delay" for c in result.causes)


def test_refuted_then_next_promoted(tmp_path: Path) -> None:
    def script(hid: str, attempt: int) -> dict[str, Any]:
        if hid == "H1":
            return draft((0, 1, 1), contradicted=True, reason="transit was flat in the window")
        return draft((3, 3, 2)) if hid == "H2" else draft((0, 1, 1), contradicted=True)

    result = run(tmp_path, CriticScript(script))
    promotion = [b for b in branches(tmp_path) if b["branch"] == "promotion"]
    assert promotion[0]["numbers"]["from"] == "H1" and promotion[0]["numbers"]["to"] == "H2"
    assert promotion[0]["numbers"]["reason"] == "transit was flat in the window"
    ruled = {r.type: r for r in result.ruled_out}
    assert "transit was flat" in ruled["logistics_delay"].why and ruled["logistics_delay"].evidence == ["q002"]
    assert "logistics_delay" not in {c.type for c in result.causes}


def test_all_refuted_then_no_cause(tmp_path: Path) -> None:
    result = run(tmp_path, CriticScript(lambda hid, attempt: draft((0, 1, 1), contradicted=True)))
    assert result.status == "success" and result.determinable is False and result.causes == []
    assert {r.type for r in result.ruled_out} == {"logistics_delay", "volume", "single_seller", "data_artefact"}
    assert all(r.evidence for r in result.ruled_out)
    # Acceptance criterion 5: the summary names no ruled-out type as the cause.
    assert result.summary and result.summary.startswith("Cannot be determined")
    assert not any(r.type in result.summary for r in result.ruled_out)
    final = branches(tmp_path)[-1]
    assert final["branch"] == "cannot_be_determined" and final["numbers"]["refuted"] == ["H1", "H2", "H3", "H4"]


# --- caps (acceptance criterion 3) --------------------------------------------------------------------


@pytest.mark.parametrize("max_chunks", [2, 3, 4, 6, 8])
def test_revisions_and_critic_calls_are_capped(tmp_path: Path, max_chunks: int) -> None:
    always_insufficient = CriticScript(lambda hid, attempt: draft((1, 1, 1), follow_up=["one more test"]))
    result = run(tmp_path, always_insufficient, cfg=config(max_chunks=max_chunks))
    lines = critiques(tmp_path)
    assert len(lines) <= max_chunks and len(always_insufficient.critic_inputs) <= max_chunks
    per_hypothesis: dict[str, int] = {}
    for line in lines:
        per_hypothesis[line["hypothesis_id"]] = per_hypothesis.get(line["hypothesis_id"], 0) + 1
    assert all(count <= 2 for count in per_hypothesis.values())  # one critique plus at most one revision
    revisions = [c for c in chunks(tmp_path) if c["kind"] == "revision"]
    assert len(revisions) == len({c["hypothesis_id"] for c in revisions})
    assert len(chunks(tmp_path)) <= max_chunks
    assert result.determinable is False and result.causes == []  # nothing was ever supported


def test_critic_calls_never_exceed_max_chunks_even_with_report_follow_ups(tmp_path: Path) -> None:
    class AlwaysMore(CriticScript):
        def __call__(self, messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> Any:
            result = super().__call__(messages, schema=schema, role=role, run_id=run_id)
            if schema is not None and schema.__name__ == "ReportDraft" and result.ok:
                reply = {**json.loads(result.content), "complete": False,
                         "follow_up": [{"id": "H9", "family": "volume", "priority": 9, "statement": "More deliveries.",
                                        "test": {"description": "deliveries per day", "sources": ["orders"]}}]}
                return GenerationResult(ok=True, content=json.dumps(reply), parsed=reply, provider="stub")
            return result

    model = AlwaysMore(lambda hid, attempt: draft((2, 1, 1), follow_up=["again"]))
    run(tmp_path, model, cfg=config(max_chunks=5))
    assert 0 < len(critiques(tmp_path)) <= 5


# --- Sprint 10b: the Critic's failure path, the reported branch, the cap's unit ----------------------------

HYPOTHESES = ["H1", "H2", "H3", "H4"]
"""The stub Planner's hypotheses for the lateness question, in priority order."""


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (GenerationResult(ok=False, error={"code": "provider_error", "message": "HTTP 503"}), "provider_error"),
        # parsed, but fails CritiqueDraft validation (a check is missing)
        (GenerationResult(ok=True, content="{}", parsed={**draft(), "checks": draft()["checks"][:4]}, provider="stub"),
         "invalid_reply"),
    ],
)
def test_critic_failure_demotes_without_a_revision_and_names_the_critic(
        tmp_path: Path, reply: GenerationResult, code: str) -> None:
    """Acceptance criterion 1: a Critic whose model call always fails costs no revision chunk."""
    model = CriticScript(lambda hid, attempt: reply)
    result = run(tmp_path, model)
    # No revision chunk: the plan chunk and one round per hypothesis.
    assert [(c["kind"], c["hypothesis_id"]) for c in chunks(tmp_path)] == [
        ("plan", None), *(("round", hid) for hid in HYPOTHESES)]
    assert not any(line["action"] == "request_revision" for line in trace(tmp_path))
    # One critique per hypothesis, each the first call plus its one retry: 8 Critic model calls
    # (on main the empty revision chunk asked for a second critique: 16).
    lines = critiques(tmp_path)
    assert [(line["hypothesis_id"], line["attempt"], line["critic_error"], line["model_calls"]) for line in lines] == [
        (hid, 1, code, 2) for hid in HYPOTHESES]
    assert len(model.critic_inputs) == 8
    critic_calls = [c for c in model.calls if c["schema"] == "CritiqueDraft"]
    assert len(critic_calls) == 8
    # Every other model call is the same as in a run whose Critic answers once per hypothesis.
    once = CriticScript(lambda hid, attempt: draft((0, 1, 1), contradicted=True))
    run(tmp_path / "once", once)
    assert len(model.calls) - len(critic_calls) == len(once.calls) - len(once.critic_inputs)
    # Every hypothesis demoted; cannot be determined, and the answer blames the Critic, not the data.
    final = branches(tmp_path)[-1]
    assert final["branch"] == "cannot_be_determined"
    assert final["numbers"]["demoted"] == HYPOTHESES and final["numbers"]["unconfirmed"] == []
    assert result.status == "success" and result.determinable is False and result.causes == []
    assert result.stop_reason == "completed"
    failures = [item for item in result.limitations if item.startswith("Critic failure:")]
    assert len(failures) == 4
    assert failures[0].startswith(f"Critic failure: the Critic could not judge H1 (logistics_delay) ({code})")
    assert not any(item.startswith("Unconfirmed:") or "Data that would decide it" in item
                   for item in result.limitations)
    expected_why = "the Critic could not judge " + ", ".join(f"{hid} ({code})" for hid in HYPOTHESES)
    assert final["why"] == expected_why
    # (the Reporter's own ruled-out entries, from the Investigator's readings, are still counted)
    assert result.summary is not None
    assert result.summary.startswith(f"Cannot be determined from the data: {expected_why} (4 tested, ")


def test_one_critic_failure_among_refutations_is_named(tmp_path: Path) -> None:
    down = GenerationResult(ok=False, error={"code": "timeout", "message": "no reply"})
    model = CriticScript(lambda hid, attempt: down if hid == "H1" else draft((0, 1, 1), contradicted=True))
    result = run(tmp_path, model)
    assert [c["kind"] for c in chunks(tmp_path)] == ["plan", "round", "round", "round", "round"]
    promotion = next(b for b in branches(tmp_path) if b["branch"] == "promotion")
    assert promotion["numbers"]["from"] == "H1" and promotion["numbers"]["to"] == "H2"
    assert result.determinable is False
    assert result.summary == ("Cannot be determined from the data: the Critic could not judge H1 (timeout); the other "
                              "tested explanations were refuted or left unconfirmed (4 tested, 3 ruled out).")


def test_insufficient_with_follow_up_still_gets_its_revision(tmp_path: Path) -> None:
    """The success path is unchanged: a Critic that asks for a test still gets the revision chunk."""
    model = CriticScript(lambda hid, attempt: draft((2, 1, 1), follow_up=["split by state"]) if hid == "H1"
                         else draft((0, 1, 1), contradicted=True))
    run(tmp_path, model)
    assert [(c["kind"], c["hypothesis_id"]) for c in chunks(tmp_path)][:3] == [
        ("plan", None), ("round", "H1"), ("revision", "H1")]
    assert all(line["critic_error"] is None and line["model_calls"] == 1 for line in critiques(tmp_path))


class ReportsOnly(ScriptedModel):
    """The stub, with every Reporter cause moved to hypothesis `to` (or no cause, determinable false)."""

    def __init__(self, to: str | None) -> None:
        super().__init__()
        self.to = to

    def __call__(self, messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> Any:
        result = super().__call__(messages, schema=schema, role=role, run_id=run_id)
        if schema is not None and schema.__name__ == "ReportDraft" and result.ok:
            reply = json.loads(result.content)
            if self.to is None:
                reply = {**reply, "determinable": False, "causes": []}
            else:
                reply = {**reply, "causes": [{**c, "hypothesis_id": self.to} for c in reply["causes"]]}
            return GenerationResult(ok=True, content=json.dumps(reply), parsed=reply, provider="stub")
        return result


@pytest.mark.parametrize("to", [None, "H2"], ids=["reporter-undeterminable", "reporter-cause-for-another"])
def test_supported_but_not_reported_trace_and_summary_agree(tmp_path: Path, to: str | None) -> None:
    """Acceptance criterion 2: the Critic supports H1 (the stub's rule), the Reporter does not report it."""
    result = run(tmp_path, ReportsOnly(to))
    assert next((line["hypothesis_id"], line["verdict"]) for line in critiques(tmp_path)) == ("H1", "supported")
    final = branches(tmp_path)[-1]
    why = "the Reporter did not report the supported explanation (H1)"
    assert final["branch"] == "cannot_be_determined" and final["why"] == why
    assert final["numbers"]["supported"] == ["H1"]
    assert result.determinable is False and result.causes == []
    assert result.summary is not None and result.summary.startswith(f"Cannot be determined from the data: {why} (")


def test_reporter_undeterminable_with_a_supported_cause_is_explained(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """The case behind the PR #28 note: the Reporter keeps the supported cause but calls the answer not
    determinable. The branch line used to say "the Critic supported the leading explanation" while the
    summary said nothing was supported."""
    from app.engines.markovian import orchestrator

    real = orchestrator.report

    def undeterminable(*args: Any, **kwargs: Any) -> Any:
        outcome = real(*args, **kwargs)
        assert outcome.causes and outcome.cause_hypotheses == ["H1"]
        outcome.determinable = False
        return outcome

    monkeypatch.setattr(orchestrator, "report", undeterminable)
    result = run(tmp_path, ScriptedModel())
    final = branches(tmp_path)[-1]
    why = "the Reporter did not report the supported explanation (H1)"
    assert final["branch"] == "cannot_be_determined" and final["why"] == why
    assert result.determinable is False and result.causes == []
    assert result.summary is not None and why in result.summary


def test_critic_cap_counts_critiques_each_up_to_two_model_calls(tmp_path: Path) -> None:
    """Acceptance criterion 3: `max_chunks` caps Critic calls (critiques); one critique is up to
    MAX_REPLY_ATTEMPTS = 2 model calls (an invalid first reply and its retry)."""
    from app.agents.critic import MAX_REPLY_ATTEMPTS
    from app.engines.markovian.orchestrator import _Run

    assert MAX_REPLY_ATTEMPTS == 2
    seen: dict[tuple[str, int], int] = {}
    bad = GenerationResult(ok=False, error={"code": "invalid_json", "message": "not JSON"})

    def first_invalid(hid: str, attempt: int) -> Any:
        seen[(hid, attempt)] = seen.get((hid, attempt), 0) + 1
        return bad if seen[(hid, attempt)] == 1 else draft((0, 1, 1), contradicted=True)

    model = CriticScript(first_invalid)
    run(tmp_path, model, cfg=config(max_chunks=4))  # plan + 3 rounds
    lines = critiques(tmp_path)
    assert [line["critic_call"] for line in lines] == [1, 2, 3]  # counted per critique ...
    assert all(line["model_calls"] == 2 and line["max_critic_calls"] == 4 for line in lines)
    assert len(model.critic_inputs) == 6  # ... while the model saw two calls for each

    # At the cap the hook is not called at all, and the note names the unit.
    settings = settings_for(tmp_path / "cap")
    called: list[CriticRequest] = []
    with LocalDataLayer(run_id="cap", log_dir=tmp_path / "cap", settings=settings) as data:
        the_run = _Run("Why?", run_id="cap", generate=ScriptedModel(), data=data, settings=settings,
                       config=config(max_chunks=3), log_dir=tmp_path / "cap", sample_mode=False,
                       critic=lambda request: called.append(request), world_db_path=":memory:")
        request = critic_request(tmp_path, ScriptedModel())
        the_run.critic_calls = 3
        verdict = the_run._critique(WorldStore(":memory:"), request.context_builder, request.plan,
                                    request.hypothesis, request.hypothesis_entity_id, request.observation, "chunk")
    assert verdict is None and called == [] and the_run.critic_calls == 3
    assert the_run.notes == [("H1 was not critiqued: 3 Critic calls (MARKOVIAN_MAX_CHUNKS; each up to 2 model calls) "
                             "were made.")]


# --- branches (acceptance criteria 4-6) ---------------------------------------------------------------


def test_change_within_normal_variation_ends_early(tmp_path: Path) -> None:
    model = ScriptedModel()
    result = run(tmp_path, model, question=NO_CHANGE)
    assert result.status == "success" and result.stop_reason == "no_hypotheses"
    assert result.change is not None and result.change.significant is False
    assert result.determinable is True and result.causes == [] and result.ruled_out == []
    assert [c["kind"] for c in chunks(tmp_path)] == ["plan"]  # no hypothesis rounds
    assert critiques(tmp_path) == [] and not any(c["schema"] == "ReportDraft" for c in model.calls)
    branch = branches(tmp_path)
    assert len(branch) == 1 and branch[0]["branch"] == "no_significant_change"
    numbers = branch[0]["numbers"]
    assert numbers["observed"] == 111 and numbers["baseline"] == pytest.approx(106.857, abs=1e-3)
    assert numbers["spread"] == pytest.approx(17.677, abs=1e-3) and numbers["threshold"] == 2.0
    assert numbers["decided_by"] == "spread" and numbers["spreads"] < 2.0
    assert result.summary is not None and "\n" not in result.summary
    for number in ("111", "106.9", "17.68"):
        assert number in result.summary


def test_variation_threshold_comes_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANGE_VARIATION_THRESHOLD", "0.1")  # 4.1 orders above baseline is 0.23 spreads
    settings = Settings(sample_mode=False, log_dir=str(tmp_path / "logs"), llm_cache_dir=str(tmp_path / "cache"),
                        meterless_runtime_token="", nvidia_api_key="")
    assert settings.change_variation_threshold == 0.1
    result = run(tmp_path, ScriptedModel(), question=NO_CHANGE, settings=settings)
    assert result.change is not None and result.change.significant is True
    assert len(chunks(tmp_path)) > 1 and branches(tmp_path)[0]["branch"] == "significant_change"


def test_defaults_are_documented_in_env_example() -> None:
    assert Settings().change_variation_threshold == 2.0 and Settings().critic_min_sample_size == 30
    example = (REPO_ROOT / ".env.example").read_text()
    assert "\nCHANGE_VARIATION_THRESHOLD=2.0\n" in example and "\nCRITIC_MIN_SAMPLE_SIZE=30\n" in example


def test_small_sample_flagged_gives_determinable_false(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, critic_min_sample_size=1000)  # the week has 606 deliveries
    result = run(tmp_path, ScriptedModel(), settings=settings)
    assert result.status == "success" and result.determinable is False and result.causes == []
    first = critiques(tmp_path)[0]
    assert first["sample_too_small"] is True and first["sample_size"] == 606
    assert len(critiques(tmp_path)) == 1  # escalation: no further rounds
    final = branches(tmp_path)[-1]
    assert final["branch"] == "cannot_be_determined" and final["numbers"]["sample_size"] == 606
    assert final["numbers"]["min_sample_size"] == 1000
    assert any("CRITIC_MIN_SAMPLE_SIZE=1000" in item for item in result.limitations)
    assert any(item.startswith("Not tested after the Critic flagged the sample") for item in result.limitations)
    assert not any(family in (result.summary or "") for family in HYPOTHESIS_FAMILIES)


def test_max_chunks_without_a_supported_leader_gives_determinable_false(tmp_path: Path) -> None:
    model = CriticScript(lambda hid, attempt: draft((2, 1, 1), follow_up=["split by state"]))
    result = run(tmp_path, model, cfg=config(max_chunks=2))
    assert result.stop_reason == "max_chunks" and result.status == "success"
    assert result.determinable is False and result.causes == []
    final = branches(tmp_path)[-1]
    assert final["branch"] == "cannot_be_determined" and "max_chunks" in final["why"]
    assert final["numbers"]["unconfirmed"] == ["H1"] and final["numbers"]["untested"] == ["H2", "H3", "H4"]
    assert any(item.startswith("Unconfirmed: H1") for item in result.limitations)


def test_trace_has_one_entry_per_critic_call_and_per_branch(tmp_path: Path) -> None:
    def script(hid: str, attempt: int) -> dict[str, Any]:
        if hid == "H1":
            return draft((2, 1, 2), follow_up=["timing"]) if attempt == 1 else draft((3, 3, 2))
        return draft((0, 1, 1), contradicted=True)

    model = CriticScript(script)
    run(tmp_path, model)
    lines = critiques(tmp_path)
    assert len(lines) == len(model.critic_inputs) == 5  # H1 twice, H2-H4 once
    for line in lines:
        for key in ("hypothesis_id", "checks", "scores", "total_score", "verdict", "follow_up_tests",
                    "follow_up_results", "query_ids", "attempt"):
            assert key in line, key
        assert [c["name"] for c in line["checks"]] == list(CHECK_NAMES)
    assert lines[1]["follow_up_results"][0]["query_ids"]  # the queries that answered the follow-up
    kinds = [b["branch"] for b in branches(tmp_path)]
    assert kinds == ["significant_change", "determined"]  # H1 led throughout: no promotion
    for line in branches(tmp_path):
        assert line["why"] and isinstance(line["numbers"], dict)
    assert branches(tmp_path)[0]["numbers"]["spread"] is not None


def test_verdicts_are_stored_in_the_world_model_with_provenance(tmp_path: Path) -> None:
    run(tmp_path, ScriptedModel())
    world = [json.loads(line) for line in (tmp_path / "logs" / "world-c.jsonl").read_text().splitlines()]
    verdicts = [row for row in world if row["target_type"] == "verdict"]
    judges = [row for row in world if row["target_type"] == "judges"]
    relies = [row for row in world if row["target_type"] == "relies_on"]
    assert len(verdicts) == 4 and len(judges) == 4
    assert relies and all(row["detail"]["dst"].startswith("obs_") for row in relies)
    assert {row["agent"] for row in verdicts + judges + relies} == {"Critic"}


def test_no_op_critic_keeps_the_sprint_8_behaviour(tmp_path: Path) -> None:
    result = run(tmp_path, ScriptedModel(), critic=critic_hook)
    assert critiques(tmp_path) == [] and [c.type for c in result.causes] == ["logistics_delay"]
    assert [c["kind"] for c in chunks(tmp_path)] == ["plan", "round", "round", "round", "round"]
    start = next(line for line in trace(tmp_path) if line["action"] == "start")
    assert start["critic"] == "off"


# --- sample mode: the plan check N questions replay the committed cache ----------------------------------


def replay(tmp_path: Path, question: str, run_id: str) -> Result:
    settings = settings_for(tmp_path, sample_mode=True, llm_cache_dir="data/sample/llm_cache")
    result = run(tmp_path, Generator(settings), question=question, run_id=run_id, settings=settings)
    calls = [line for line in trace(tmp_path, run_id) if line["action"] == "model_call"]
    assert calls and all(line["status"] == "ok" and line["recorded_with"] == "stub" for line in calls)
    return result


def test_sample_incident_06_refutes_delivery_delay_and_promotes_the_next(tmp_path: Path) -> None:
    result = replay(tmp_path, ANSWER_KEY["incident-06"], "l06")
    lines = critiques(tmp_path, "l06")
    delay = [line for line in lines if line["family"] == "logistics_delay"]
    assert delay and delay[0]["verdict"] == "refuted"
    promotion = [b for b in branches(tmp_path, "l06") if b["branch"] == "promotion"]
    assert promotion and promotion[0]["numbers"]["from"] == delay[0]["hypothesis_id"]
    assert "logistics_delay" in {r.type for r in result.ruled_out}


@pytest.mark.parametrize("incident", ["incident-09", "incident-10"])
def test_sample_undeterminable_incidents_assert_no_cause(tmp_path: Path, incident: str) -> None:
    result = replay(tmp_path, ANSWER_KEY[incident], incident)
    assert result.status == "success" and result.determinable is False and result.causes == []
    assert result.limitations
    assert not any(family in (result.summary or "") for family in HYPOTHESIS_FAMILIES)


def test_sample_no_change_question(tmp_path: Path) -> None:
    result = replay(tmp_path, NO_CHANGE, "nochange")
    assert result.change is not None and result.change.significant is False and result.causes == []


# --- Sprint 8 review fixes (acceptance criterion 7) ------------------------------------------------------


def test_tool_call_cap_reports_max_tool_calls(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, max_tool_calls=3)  # change check, H1, H2; H3 and H4 left
    result = run(tmp_path, ScriptedModel(), settings=settings, critic=critic_hook)
    assert result.stop_reason == "max_tool_calls" and result.status == "success"
    assert any(item.startswith("Tool-call cap reached: MAX_TOOL_CALLS=3") and "H3, H4" in item
               for item in result.limitations)
    finish = [line for line in trace(tmp_path) if line["action"] == "finish"][-1]
    assert finish["stop_reason"] == "max_tool_calls" and finish["tool_calls_used"] == 3


def test_tool_call_cap_inside_a_round_reports_max_tool_calls(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, max_tool_calls=1)  # only the change check runs; H1's query is refused
    result = run(tmp_path, ScriptedModel(), settings=settings, critic=critic_hook)
    assert result.stop_reason == "max_tool_calls"


class Trickle(httpx.SyncByteStream):
    """A reply body sent one byte every `gap` seconds: each read is quick, the whole body is slow."""

    def __init__(self, body: bytes, gap: float) -> None:
        self.body, self.gap = body, gap

    def __iter__(self) -> Any:
        for i in range(len(self.body)):
            time.sleep(self.gap)
            yield self.body[i:i + 1]


def test_overall_deadline_bounds_a_slow_trickling_reply() -> None:
    reply = json.dumps({"choices": [{"message": {"content": "{}"}}], "model": "m"}).encode()
    seen: list[float] = []

    def server(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, stream=Trickle(b" " * 40 + reply, 0.05))  # about 3.5 s in all

    settings = Settings(sample_mode=False, meterless_runtime_token="token-x", nvidia_api_key="", max_retries=3,
                        log_dir="/tmp/unused-logs")
    generator = Generator(settings, transport=httpx.MockTransport(server), sleep=lambda _s: None)
    bounded = generator.with_limits(deadline_seconds=0.5)
    started = time.monotonic()
    result = bounded([{"role": "user", "content": "hi"}], role="compressor")
    elapsed = time.monotonic() - started
    assert not result.ok and result.error is not None and result.error["code"] == "timeout"
    assert elapsed < 0.9, elapsed  # the per-read timeout (0.5 s) alone would have let it run ~3.5 s
    assert len(seen) == 1 and seen[0] <= 0.5 + 1e-6
    deadline = time.monotonic() + 1.0  # the worker stops at its next chunk
    while any(t.name == CALL_THREAD_NAME and t.is_alive() for t in threading.enumerate()):
        assert time.monotonic() < deadline, "the request thread kept reading after the deadline"
        time.sleep(0.01)


def test_bounded_call_still_returns_a_fast_reply() -> None:
    def server(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}], "model": "m"},
                              headers={"content-encoding": "identity"})

    settings = Settings(sample_mode=False, meterless_runtime_token="token-x", nvidia_api_key="", log_dir="/tmp/unused")
    generator = Generator(settings, transport=httpx.MockTransport(server), sleep=lambda _s: None)
    result = generator.with_limits(deadline_seconds=2.0)([{"role": "user", "content": "hi"}], role="compressor")
    assert result.ok and result.content == "hello" and result.model_routed == "m"


# --- no incident-specific wording (acceptance criterion 8) -----------------------------------------------


FORBIDDEN = ("relogios", "watches", "strike", "1430239a", "average order value")


def test_prompts_and_orchestrator_have_no_incident_wording() -> None:
    files = [*sorted(PROMPT_DIR.glob("*")), REPO_ROOT / "app" / "engines" / "markovian" / "orchestrator.py"]
    files = [path for path in files if path.is_file() and path.suffix in (".md", ".py")]
    assert any(path.name == "critic.md" for path in files)
    found = [(path.name, word) for path in files for word in FORBIDDEN
             if re.search(re.escape(word), path.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert found == []


def test_simple_loop_output_keeps_its_shape() -> None:
    """`summary` and `change.spread` are left out when unset, so the simple loop's JSON is unchanged."""
    result = Result(run_id="r", status="success", question="q", determinable=False, trace_id="r", log_file="l",
                    execution_time_seconds=0.0, change={"metric": "m", "segment": "s", "window": "w"})
    dumped = result.model_dump(mode="json")
    assert "summary" not in dumped and "stop_reason" not in dumped and "spread" not in dumped["change"]

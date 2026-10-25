"""Sprint 11c: the four general causes behind wrong answers in the real Nightshift runs of 25 Oct
(main 0ae9313), each reproduced with a scripted generator and the numbers the real run reported.

1. incident-02: a share's change check came back with the per-record spread (0.1699 for a baseline of
   0.0301 against 0.132), so a 4x rise read as "within 2 x the spread".
2. incident-01: the Planner never proposed a broad, marketplace-wide volume rise.
3. incident-03: the Critic's sample-size check fired on a drop to zero (13 records in the window).
4. incident-10: with no spread, "no significant change" for 142.7 against 109.7.

The agents, DuckDB queries, World Model and chunk manager run for real; only the model replies are
scripted (app/llm/stub.py, overridden per test). No network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.agents.base import AgentContext, Budget
from app.agents.critic import Critic
from app.agents.planner import HYPOTHESIS_CHECKLIST, make_plan
from app.agents.prompts import load_prompt
from app.config import Settings
from app.data.local import LocalDataLayer
from app.engines.markovian.config import MarkovianConfig
from app.engines.markovian.orchestrator import CriticRequest, run_markovian
from app.engines.world_model.context import ContextBuilder
from app.engines.world_model.ingest import IngestPipeline
from app.engines.world_model.store import WorldStore
from app.llm.generator import GenerationResult
from app.llm.stub import ScriptedModel
from app.schemas import (
    CHECK_NAMES,
    CritiqueDraft,
    Hypothesis,
    Observation,
    Plan,
    Result,
)
from app.trace import TraceWriter

LATENESS = "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?"
ORDER_VALUE = "Why has average order value been declining since August 2017?"


def settings_for(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {"sample_mode": False, "log_dir": str(tmp_path / "logs"),
                              "llm_cache_dir": str(tmp_path / "cache"), "max_tool_calls": 20,
                              "meterless_runtime_token": "", "nvidia_api_key": ""}
    values.update(overrides)
    return Settings(**values)


def config() -> MarkovianConfig:
    return MarkovianConfig(max_chunks=8, chunk_budget_chars=12000, carryover_budget_chars=1200,
                           chunk_timeout_seconds=60.0, compression_timeout_seconds=5.0, run_timeout_s=120.0)


def run(tmp_path: Path, generate: Any, question: str, settings: Settings | None = None) -> Result:
    settings = settings or settings_for(tmp_path)
    with LocalDataLayer(run_id="n", log_dir=tmp_path / "logs", settings=settings) as data:
        result = run_markovian(question, run_id="n", generate=generate, data=data, settings=settings,
                               config=config(), log_dir=tmp_path / "logs")
    Result.model_validate(result.model_dump())
    return result


def trace(tmp_path: Path) -> list[dict[str, Any]]:
    return TraceWriter(tmp_path / "logs", "n").read()


def branches(tmp_path: Path) -> list[dict[str, Any]]:
    return [line for line in trace(tmp_path) if line["agent"] == "Orchestrator" and line["action"] == "branch"]


def critiques(tmp_path: Path) -> list[dict[str, Any]]:
    return [line for line in trace(tmp_path) if line["agent"] == "Critic" and line["action"] == "critique"]


def draft(total: tuple[int, int, int] = (3, 3, 2), *, sample_size: int | None = None) -> dict[str, Any]:
    return {
        "checks": [{"name": name, "outcome": "passed", "detail": "scripted"} for name in CHECK_NAMES],
        "scores": dict(zip(("supported_by_data", "explains_size_and_timing", "alternatives_excluded"), total,
                           strict=True)),
        "contradicted": False, "reason": "scripted critique", "follow_up_tests": [], "sample_size": sample_size,
        "observation_ids": [],
    }


class ChangeCheckScript(ScriptedModel):
    """The stub, with the change check's row and the Investigator's reading of it fixed."""

    def __init__(self, row: dict[str, Any], supports: bool | None) -> None:
        super().__init__()
        self.row = row
        self.supports = supports

    def _reply_SqlProposal(self, data: dict[str, Any]) -> dict[str, Any] | None:
        if data.get("task", {}).get("kind") != "change_check":
            return super()._reply_SqlProposal(data)
        columns = ", ".join(f"{'NULL' if v is None else v} AS {k}" for k, v in self.row.items())
        return {"sql": f"SELECT {columns} FROM orders.orders LIMIT 1", "sources": ["orders"],
                "rationale": "The change check as the real run measured it."}

    def _reply_ObservationDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        reply = super()._reply_ObservationDraft(data)
        if reply is not None and data.get("task", {}).get("kind") == "change_check":
            reply["supports"] = self.supports
        return reply


# --- 1. incident-02: the per-record spread of a share -------------------------------------------------


INCIDENT_02 = {"value": 0.132, "baseline": 0.0301, "spread": 0.1699}


def test_incident_02_numbers_were_within_two_spreads_before_the_fix() -> None:
    """The old rule: |0.132 - 0.0301| = 0.1019 is within 2 x 0.1699, so the run stopped as no change."""
    assert abs(INCIDENT_02["value"] - INCIDENT_02["baseline"]) <= 2.0 * INCIDENT_02["spread"]


def test_incident_02_share_spread_is_replaced_by_the_standard_error(tmp_path: Path) -> None:
    model = ChangeCheckScript({**INCIDENT_02, "n": 606, "n_baseline": 5963}, supports=False)
    result = run(tmp_path, model, LATENESS)
    first = branches(tmp_path)[0]
    assert first["branch"] == "significant_change"
    numbers = first["numbers"]
    assert numbers["spread_rejected"] == 0.1699 and numbers["spread_basis"] == "standard_error"
    assert numbers["spread"] == pytest.approx((0.0301 * 0.9699 / 606) ** 0.5, abs=1e-6)
    assert numbers["decided_by"] == "spread" and numbers["spreads"] > 10
    assert result.stop_reason != "no_hypotheses" and result.change is not None and result.change.significant is True
    assert result.change.spread == pytest.approx(0.006941, abs=1e-6)  # the spread actually used, not 0.1699
    assert len(critiques(tmp_path)) >= 1  # the hypotheses were tested


def test_incident_02_share_spread_without_a_count_falls_back_to_the_relative_rule(tmp_path: Path) -> None:
    model = ChangeCheckScript(INCIDENT_02, supports=False)
    result = run(tmp_path, model, LATENESS)
    first = branches(tmp_path)[0]
    assert first["branch"] == "change_not_decided"
    numbers = first["numbers"]
    assert numbers["spread"] is None and numbers["spread_rejected"] == 0.1699
    assert numbers["spread_basis"] == "not_measured" and numbers["decided_by"] == "relative_change"
    assert numbers["relative_change"] == pytest.approx(3.3854, abs=1e-4) and numbers["relative_floor"] == 0.2
    assert result.stop_reason != "no_hypotheses" and result.change.significant is None
    assert critiques(tmp_path)


def test_change_check_note_asks_for_period_level_spread_and_baseline_count() -> None:
    note = load_prompt("change_check_note")
    assert "per period first" in note and "per-record" in note and "`n_baseline`" in note


# --- 2. incident-01: the broad-volume hypothesis ----------------------------------------------------------


def test_planner_gets_the_checklist_with_a_breadth_test_for_count_and_revenue(tmp_path: Path) -> None:
    model = ScriptedModel()
    settings = settings_for(tmp_path)
    with LocalDataLayer(run_id="p", log_dir=tmp_path / "logs", settings=settings) as data:
        ctx = AgentContext(generate=model, data=data, trace=TraceWriter(tmp_path / "logs", "p"), run_id="p",
                           budget=Budget(max_rounds=6, max_tool_calls=20))
        make_plan(ctx, "Why did order volume spike on 24 November 2017?")
    body = json.loads(model.calls[0]["messages"][-1]["content"][len("INPUT:"):])
    checklist = body["hypothesis_checklist"]
    assert checklist == [dict(item) for item in HYPOTHESIS_CHECKLIST]
    count = next(item for item in checklist if item["metric_kind"].startswith("count or revenue"))
    assert count["standard_families"].startswith("volume")
    assert "distinct sellers" in count["volume_test"] and "categories" in count["volume_test"]
    families = set(body["hypothesis_families"])
    for item in checklist:  # every family the checklist names is in the vocabulary
        named = {word.strip(" ,()") for word in item["standard_families"].replace(" or ", ", ").split(",")}
        assert {word.split(" (")[0] for word in named} <= families, item


def test_planner_prompt_requires_volume_for_count_and_revenue_and_the_whole_period() -> None:
    prompt = load_prompt("planner")
    assert "`hypothesis_checklist`" in prompt
    assert "For a count or revenue metric, always include `volume`" in prompt
    assert "the window spans all of it" in prompt


def test_incident_01_with_a_breadth_hypothesis_finds_a_supported_cause(tmp_path: Path) -> None:
    """The real run tested data_artefact, price_discount, mix_shift and single_seller, each judged
    insufficient, and ended at max_chunks with no cause. A plan that follows the checklist adds the breadth
    test (distinct sellers per day), which the stub measures on the sample data and the Critic supports."""
    model = ScriptedModel()
    result = run(tmp_path, model, "Why did order volume spike on 24 November 2017?")
    plan = next(line for line in trace(tmp_path) if line["agent"] == "Planner" and line["action"] == "plan")
    assert re.search(r"H\d volume: ", json.dumps(plan["output_summary"]))
    assert result.determinable is True and result.causes[0].type == "volume"
    volume = next(line for line in critiques(tmp_path) if line["family"] == "volume")
    assert volume["verdict"] == "supported"


# --- 3. incident-03: the sample-size check on a drop to zero ------------------------------------------------


def critic_request(change_row: dict[str, Any], observed: float, baseline: float, *,
                   window: tuple[str, str] = ("2018-01-08", "2018-01-22"),
                   baseline_window: tuple[str, str] = ("2017-12-11", "2018-01-08")) -> CriticRequest:
    store = WorldStore(":memory:")
    hypothesis = Hypothesis(id="H1", family="single_seller", statement="The seller's orders were cancelled.",
                            priority=1, test={"description": "order status for the seller", "sources": ["orders"]})
    entity_id = IngestPipeline(store, settings=Settings(meterless_runtime_token="", nvidia_api_key="")).put_hypothesis(
        hypothesis, run_id="u")
    plan = Plan(question="Why?", metric="seller revenue", segment="seller",
                window={"start": window[0], "end": window[1]},
                baseline_window={"start": baseline_window[0], "end": baseline_window[1]},
                change_check={"description": "revenue"},
                hypotheses=[hypothesis, hypothesis.model_copy(update={"id": "H2", "priority": 2})])
    obs = Observation(id="obs-1", hypothesis_id="H1", query_id="q002", source="orders", sql="SELECT 1",
                      finding="Cancelled share 0.9 against 0.02.", value=0.9, baseline=0.02, effect=44.0, supports=True)
    change = Observation(id="obs-0", query_id="q001", source="orders", sql="SELECT 1", finding="Revenue fell.",
                         value=observed, baseline=baseline, effect=None, supports=True)

    def generate(messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> GenerationResult:
        reply = draft((3, 3, 2), sample_size=change_row.get("n"))
        return GenerationResult(ok=True, content=json.dumps(reply), parsed=CritiqueDraft.model_validate(reply)
                                .model_dump(mode="json"), provider="stub")

    return CriticRequest(run_id="u", plan=plan, hypothesis=hypothesis, hypothesis_entity_id=entity_id,
                         observation=obs, chunk_text="Goal.", context_builder=ContextBuilder(store), budget_chars=4000,
                         generate=generate, change=change, change_row=change_row)


def test_incident_03_drop_to_zero_counts_window_and_baseline() -> None:
    verdict = Critic(min_sample_size=30)(critic_request({"n": 13, "n_baseline": 96}, 0.0, 1520.5))
    assert verdict.verdict == "supported" and not verdict.sample_too_small
    assert verdict.sample_size == 13 and verdict.sample_basis == "window_and_baseline" and verdict.sample_counted == 109


def test_incident_03_drop_to_zero_without_a_baseline_count_skips_the_rule() -> None:
    """The real run's row had no baseline count: 13 records in the window, minimum 30."""
    verdict = Critic(min_sample_size=30)(critic_request({"n": 13}, 0.0, 1520.5))
    assert verdict.verdict == "supported" and not verdict.sample_too_small
    assert verdict.sample_basis == "not_applied" and verdict.sample_counted is None


def test_incident_03_few_records_on_both_sides_are_still_too_few() -> None:
    verdict = Critic(min_sample_size=30)(critic_request({"n": 2, "n_baseline": 9}, 0.0, 300.0))
    assert verdict.verdict == "insufficient" and verdict.sample_too_small
    assert verdict.sample_counted == 11
    assert "11 records in the window and the baseline together (minimum 30)" in verdict.reason


def test_incident_09_style_three_records_without_a_fall_are_flagged() -> None:
    """Review scores fell with 3 reviews in 15 days against 5 in 30: no fall in records, still too few."""
    request = critic_request({"n": 3, "n_baseline": 5}, 1.67, 3.0, window=("2017-12-01", "2017-12-16"),
                             baseline_window=("2017-11-01", "2017-12-01"))
    verdict = Critic(min_sample_size=30)(request)
    assert verdict.verdict == "insufficient" and verdict.sample_too_small
    assert verdict.sample_basis == "window" and verdict.sample_counted == 3
    assert "Sample too small: 3 records in the window (minimum 30)" in verdict.reason


def test_critic_prompt_says_a_fall_in_records_is_the_finding() -> None:
    assert "few records in the window are the finding" in load_prompt("critic")


# --- 4. incident-10: no spread and a large change -----------------------------------------------------------


def test_incident_10_no_spread_large_change_is_investigated(tmp_path: Path) -> None:
    model = ChangeCheckScript({"value": 142.7, "baseline": 109.7, "spread": None, "n": 3123, "n_baseline": 6005},
                              supports=False)
    result = run(tmp_path, model, ORDER_VALUE)
    first = branches(tmp_path)[0]
    assert first["branch"] == "change_not_decided" and first["numbers"]["decided_by"] == "relative_change"
    assert first["numbers"]["relative_change"] == pytest.approx(0.3008, abs=1e-4)
    assert "30% of the baseline" in first["why"] and "20%" in first["why"]
    assert result.stop_reason != "no_hypotheses" and not (result.summary or "").startswith("No significant change")
    assert critiques(tmp_path)


def test_no_spread_small_change_still_ends_as_no_change(tmp_path: Path) -> None:
    """Within the relative rule (3.9 % < 20 %) the Investigator's "not real" still ends the run."""
    model = ChangeCheckScript({"value": 111, "baseline": 106.857, "spread": None, "n": 111, "n_baseline": 748},
                              supports=False)
    result = run(tmp_path, model, "Why did order volume rise on 21 September 2017?")
    first = branches(tmp_path)[0]
    assert first["branch"] == "no_significant_change" and first["numbers"]["decided_by"] == "investigator_reading"
    assert result.stop_reason == "no_hypotheses" and "spread not measured" in (result.summary or "")


def test_relative_rule_follows_the_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANGE_VARIATION_THRESHOLD", "4.0")  # 40 %: a 30 % change is now within it
    settings = Settings(sample_mode=False, log_dir=str(tmp_path / "logs"), llm_cache_dir=str(tmp_path / "cache"),
                        meterless_runtime_token="", nvidia_api_key="")
    model = ChangeCheckScript({"value": 142.7, "baseline": 109.7, "spread": None, "n": 3123}, supports=False)
    result = run(tmp_path, model, ORDER_VALUE, settings=settings)
    assert branches(tmp_path)[0]["branch"] == "no_significant_change"
    assert result.stop_reason == "no_hypotheses"

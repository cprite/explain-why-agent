"""Tests and plan check for the Markovian carryover cascade (app/engines/markovian/carryover.py).

Plan check (build-plan task 11): carryover stays within `carryover_budget_chars` for every step,
and each fallback step works when the one before it fails. Every case prints the step used and
`used_chars/budget_chars`; CI runs this file with `-s` so the lines appear in the log. No network.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.config import REPO_ROOT, Settings
from app.engines.markovian.carryover import (
    STEPS,
    Carryover,
    CarryoverDraft,
    RoundOutput,
    SampleStubGenerator,
    build_carryover,
    compression_messages,
    heuristic_items,
    main,
    recorded_report,
    round_from_report,
)
from app.engines.markovian.config import MarkovianConfig
from app.llm.generator import GenerationResult, Generator, ResponseCache

ROUND_TEXT = """Investigation round 3 on H3.
1. H3 leading: top-3 category share 28.7% vs 25.1% baseline (+14%).
2. H4: one seller went from 0.14 to 10 orders a day.
- H1 ruled out: 0 duplicate order ids in window and baseline.
- H2 refuted: discount share 1.0 in both periods.
Which categories drove the shift?
Next check: seller share of the total increase.
"""

STATE = {
    "ranking": [{"id": "H3", "note": "top-3 category share 28.7% vs 25.1%"}, {"id": "H4", "note": "seller 10/day"}],
    "ruled_out": [{"id": "H1", "reason": "0 duplicate order ids"}, {"id": "H2", "reason": "discount share unchanged"}],
    "open_questions": ["Which categories drove the shift?"],
}
COMPRESSED = {"ranking": [{"id": "H3", "note": "mix shift"}], "ruled_out": [{"id": "H1", "reason": "no duplicates"}]}
NO_ITEMS_TEXT = "Order count was 1176 on the day against 136.6 a day in the baseline window, about 8.6 times."


def cfg(budget: int = 600, timeout: float = 1.0) -> MarkovianConfig:
    return MarkovianConfig(
        max_chunks=8,
        chunk_budget_chars=max(1000, budget * 2),
        carryover_budget_chars=budget,
        chunk_timeout_seconds=10.0,
        compression_timeout_seconds=timeout,
    )


def report_case(case: str, carryover: Carryover) -> None:
    tried = ", ".join(f"{a.step}:{a.status}" for a in carryover.attempts)
    print(
        f"\nPLAN-CHECK {case}: step={carryover.carryover_step} "
        f"used_chars/budget_chars={carryover.used_chars}/{carryover.budget_chars} tried=[{tried}]"
    )


def check(case: str, carryover: Carryover, expected_step: str, config: MarkovianConfig) -> None:
    report_case(case, carryover)
    assert carryover.carryover_step == expected_step
    assert carryover.used_chars <= config.carryover_budget_chars
    assert carryover.used_chars == len(carryover.render())
    assert carryover.attempts[-1].step == expected_step
    assert carryover.attempts[-1].status == "ok"
    # Every earlier step was tried, in order, and did not succeed.
    assert [a.step for a in carryover.attempts if a.status == "ok"] == [expected_step]
    assert [a.step for a in carryover.attempts][-1] == expected_step
    tried = [a.step for a in carryover.attempts]
    assert tried == sorted(tried, key=STEPS.index)
    assert set(STEPS[: STEPS.index(expected_step)]) <= set(tried)


class SlowGenerator:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __call__(self, messages: list[dict[str, Any]], **_: Any) -> GenerationResult:
        time.sleep(self.seconds)
        return GenerationResult(ok=True, content=json.dumps(COMPRESSED))


# --- Plan check: each step, and each fallback when the step before fails ------------------------------


def test_step1_explicit_state_is_used_when_valid() -> None:
    config = cfg()
    stub = SampleStubGenerator("reply", COMPRESSED)
    result = build_carryover(RoundOutput(ROUND_TEXT, STATE), config=config, rounds_left=5, generate=stub)
    check("step1 valid explicit state", result, "explicit_state", config)
    assert stub.calls == 0
    assert [r.id for r in result.ranking] == ["H3", "H4"]
    assert result.rounds_left == 5
    assert result.render().startswith("Rounds left: 5\nRanking: 1) H3: top-3 category share")


@pytest.mark.parametrize(
    ("case", "state"),
    [
        ("missing", None),
        ("wrong type", {"ranking": "H3 then H4"}),
        ("missing reason", {"ruled_out": [{"id": "H1"}]}),
        ("unknown field", {**STATE, "verdict": "done"}),
        ("empty", {"ranking": [], "ruled_out": [], "open_questions": ["  "]}),
        ("not an object", ["H3"]),
    ],
)
def test_step1_invalid_state_falls_back_to_step2_model_compression(case: str, state: Any) -> None:
    config = cfg()
    stub = SampleStubGenerator("reply", COMPRESSED)
    result = build_carryover(RoundOutput(ROUND_TEXT, state), config=config, rounds_left=4, generate=stub)
    check(f"step1 fails ({case}) -> step2", result, "model_compression", config)
    assert stub.calls == 1
    assert result.attempts[0].status == "failed"
    assert [r.id for r in result.ranking] == ["H3"]


def test_step1_over_budget_falls_back_to_step2() -> None:
    config = cfg(budget=200)
    big = {"ranking": [{"id": f"H{i}", "note": "n" * 300} for i in range(1, 4)]}
    result = build_carryover(
        RoundOutput(ROUND_TEXT, big), config=config, rounds_left=2, generate=SampleStubGenerator("reply", COMPRESSED)
    )
    check("step1 over budget -> step2", result, "model_compression", config)
    assert result.attempts[0].status == "over_budget"
    assert result.attempts[0].used_chars is not None and result.attempts[0].used_chars > 200


@pytest.mark.parametrize(
    ("case", "generate"),
    [
        ("generator raises", SampleStubGenerator("raise")),
        ("invalid JSON", SampleStubGenerator("invalid_json")),
        ("generator error result", SampleStubGenerator("error")),
        ("schema mismatch", SampleStubGenerator("reply", {"ranking": [{"rank": 1}]})),
        ("empty reply", SampleStubGenerator("reply", {})),
        ("times out", SlowGenerator(1.5)),
        ("no generator", None),
    ],
)
def test_step2_failure_falls_back_to_step3_heuristic(case: str, generate: Any) -> None:
    config = cfg(timeout=0.2)
    started = time.perf_counter()
    result = build_carryover(RoundOutput(ROUND_TEXT, None), config=config, rounds_left=3, generate=generate)
    elapsed = time.perf_counter() - started
    check(f"step2 fails ({case}) -> step3", result, "heuristic_extraction", config)
    assert result.attempts[1].step == "model_compression"
    assert result.attempts[1].status == "failed"
    if case == "times out":
        assert "did not answer within 0.2 s" in result.attempts[1].detail
        assert elapsed < 1.0  # the cascade did not wait for the slow generator
    assert [r.id for r in result.ranking] == ["H3", "H4"]
    assert [r.id for r in result.ruled_out] == ["H1", "H2"]
    assert result.open_questions[0] == "Which categories drove the shift?"


def test_step2_over_budget_falls_back_to_step3() -> None:
    config = cfg(budget=300)
    long_reply = {"ranking": [{"id": "H3", "note": "m" * 390}]}
    result = build_carryover(
        RoundOutput(ROUND_TEXT, None), config=config, rounds_left=3, generate=SampleStubGenerator("reply", long_reply)
    )
    check("step2 over budget -> step3", result, "heuristic_extraction", config)
    assert result.attempts[1].status == "over_budget"


def test_step2_real_generator_in_sample_mode_cache_miss_falls_back_to_step3(tmp_path: Path) -> None:
    """The injected generator is the real one (sample mode, empty cache): a miss, no network."""
    settings = Settings(sample_mode=True, llm_cache_dir=str(tmp_path), log_dir=str(tmp_path))
    generator = Generator(settings, cache=ResponseCache(tmp_path))
    config = cfg()
    result = build_carryover(RoundOutput(ROUND_TEXT, None), config=config, rounds_left=3, generate=generator)
    check("step2 real generator cache miss -> step3", result, "heuristic_extraction", config)
    assert "cache_miss" in result.attempts[1].detail


@pytest.mark.parametrize(
    ("case", "text"),
    [("numbers only", NO_ITEMS_TEXT), ("empty text", ""), ("short lines", "ok\nfine\n")],
)
def test_step3_no_extractable_items_falls_back_to_step4_truncation(case: str, text: str) -> None:
    config = cfg()
    result = build_carryover(
        RoundOutput(text, {"bad": 1}), config=config, rounds_left=1, generate=SampleStubGenerator("invalid_json")
    )
    check(f"step3 fails ({case}) -> step4", result, "truncation", config)
    assert result.attempts[2].step == "heuristic_extraction"
    assert result.attempts[2].status == "failed"
    assert result.ranking == [] and result.ruled_out == []


def test_step3_drops_trailing_items_to_fit_then_step4_when_nothing_fits() -> None:
    lines = [f"{i}. H{i} leading candidate " + "d" * 150 for i in range(1, 7)]
    lines += [f"- H{i} ruled out because " + "r" * 150 for i in range(7, 13)]
    text = "\n".join(lines)
    config = cfg(budget=500)
    fitted = build_carryover(RoundOutput(text, None), config=config, rounds_left=2)
    check("step3 drops items to fit", fitted, "heuristic_extraction", config)
    assert "dropped" in fitted.attempts[-1].detail
    assert fitted.ranking[0].id == "H1"  # the head of the ranking is kept

    config_tiny = cfg(budget=200)
    huge = "1. H1 leading candidate " + "w" * 400
    # One item clipped to 200 chars plus the header does not fit in 200: step 4 takes over.
    cut = build_carryover(RoundOutput(huge, None), config=config_tiny, rounds_left=2)
    check("step3 nothing fits -> step4", cut, "truncation", config_tiny)


@pytest.mark.parametrize("budget", [200, 333, 1200, 5000])
def test_step4_truncation_always_within_budget(budget: int) -> None:
    config = cfg(budget=budget)
    text = " ".join(f"number{i}=4{i}.5" for i in range(4000))  # ~50,000 chars, nothing extractable
    result = build_carryover(RoundOutput(text, None), config=config, rounds_left=7)
    check(f"step4 truncation of 50k chars at budget {budget}", result, "truncation", config)
    assert result.notes.endswith("…")
    assert result.used_chars > budget - 40  # it uses the budget rather than giving up early


def test_truncation_falls_back_to_previous_state_when_round_text_is_empty() -> None:
    config = cfg()
    previous = build_carryover(RoundOutput(ROUND_TEXT, STATE), config=config, rounds_left=3)
    result = build_carryover(RoundOutput("", None), config=config, rounds_left=2, previous=previous)
    check("step4 empty round keeps previous state text", result, "truncation", config)
    assert "H3" in result.notes


@pytest.mark.parametrize("budget", [200, 400, 1200, 4000])
@pytest.mark.parametrize("state", [STATE, None, {"x": 1}])
@pytest.mark.parametrize("mode", ["reply", "raise", "invalid_json"])
def test_every_combination_stays_within_budget(budget: int, state: Any, mode: Any) -> None:
    config = cfg(budget=budget)
    for text in (ROUND_TEXT, NO_ITEMS_TEXT * 50, ""):
        result = build_carryover(
            RoundOutput(text, state), config=config, rounds_left=6, generate=SampleStubGenerator(mode, COMPRESSED)
        )
        assert result.used_chars <= budget
        assert result.carryover_step in STEPS


# --- Unit behaviour ---------------------------------------------------------------------------------


def test_compression_messages_carry_goal_previous_state_and_a_bounded_preview() -> None:
    config = cfg()
    previous = build_carryover(RoundOutput(ROUND_TEXT, STATE), config=config, rounds_left=3)
    messages = compression_messages(
        RoundOutput("t " * 5000, None), goal="Why?", previous=previous, budget=600, preview_chars=1000
    )
    assert messages[0]["role"] == "system" and "600 characters" in messages[0]["content"]
    user = messages[1]["content"]
    assert user.startswith("Goal: Why?\n\nPrevious state:\nRounds left: 3")
    assert user.endswith("[...]")
    assert len(user) < 1000 + len(previous.render()) + 100


def test_generator_is_called_once_with_the_schema_and_compressor_role() -> None:
    seen: list[dict[str, Any]] = []

    def generate(messages: list[dict[str, Any]], **kwargs: Any) -> GenerationResult:
        seen.append(kwargs)
        return GenerationResult(ok=True, content="", parsed=COMPRESSED)

    result = build_carryover(RoundOutput(ROUND_TEXT, None), config=cfg(), rounds_left=1, generate=generate, run_id="r9")
    assert result.carryover_step == "model_compression"
    assert seen == [{"schema": CarryoverDraft, "role": "compressor", "run_id": "r9"}]


def test_heuristic_extraction_is_deterministic_and_does_not_rank_ruled_out_ids() -> None:
    text = "1. H1 leading: volume up\n- H1 not supported after all\n2) H2 supported: seller\nIs H5 open?"
    first, second = heuristic_items(text), heuristic_items(text)
    assert first == second
    assert [r.id for r in first.ranking] == ["H2"]  # H1 was ranked, then ruled out
    assert [r.id for r in first.ruled_out] == ["H1"]
    assert first.open_questions == ["Is H5 open?"]


def test_rounds_left_is_never_negative_and_to_dict_is_json() -> None:
    result = build_carryover(RoundOutput(ROUND_TEXT, STATE), config=cfg(), rounds_left=-2)
    assert result.rounds_left == 0
    data = json.loads(json.dumps(result.to_dict()))
    assert data["carryover_step"] == "explicit_state"
    assert data["used_chars"] == len(data["text"])
    assert data["attempts"][0]["status"] == "ok"


# --- Sample mode ------------------------------------------------------------------------------------


def test_recorded_round_comes_from_the_sample_cache() -> None:
    key, report = recorded_report(REPO_ROOT / "data" / "sample" / "llm_cache")
    assert report["complete"] is False
    round_output = round_from_report(report)
    assert round_output.state is not None
    assert CarryoverDraft.model_validate(round_output.state).ranking
    assert "Ruled out:" in round_output.text
    assert len(key) == 64


def test_sample_mode_runs_every_step_without_network(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--sample"]) == 0
    out = capsys.readouterr().out
    for number, step in enumerate(STEPS, 1):
        assert f"step {number} {step}: ok" in out
    assert "Sample cascade: OK" in out


def test_cli_without_sample_flag_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "--sample" in capsys.readouterr().out

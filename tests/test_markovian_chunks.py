"""Tests for the Markovian chunk manager (app/engines/markovian/chunks.py), against a stub payload."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.engines.markovian.carryover import Carryover, RankedItem, RuledOutItem
from app.engines.markovian.chunks import (
    GOAL_CONTINUATION_CHARS,
    ChunkCapError,
    ChunkManager,
    ContextPayload,
    estimate_tokens,
    render_item,
)
from app.engines.markovian.config import MarkovianConfig

GOAL = "Why did order volume spike on 24 November 2017?"


@dataclass
class StubItem:
    id: str
    type: str
    summary: str
    selection_reason: str


@dataclass
class StubPayload:
    """Stands in for the World Model ContextBuilder payload until the orchestrator sprint wires it."""

    items: list[StubItem] = field(default_factory=list)
    budget_chars: int = 0
    used_chars: int = 0


def payload(n: int, summary_chars: int = 200) -> StubPayload:
    items = [
        StubItem(f"obs-{i}", "observation", f"Finding {i}: " + "x" * summary_chars, f"supports H{i % 3 + 1}")
        for i in range(1, n + 1)
    ]
    return StubPayload(items=items, budget_chars=10**6, used_chars=sum(len(i.summary) for i in items))


def carryover(budget: int = 1000) -> Carryover:
    return Carryover(
        ranking=[RankedItem(id="H3", note="mix shift, top-3 share 28.7% vs 25.1%")],
        ruled_out=[RuledOutItem(id="H1", reason="0 duplicate order ids")],
        open_questions=["Which categories drove the shift?"],
        rounds_left=5,
        budget_chars=budget,
        carryover_step="explicit_state",
    )


def config(**overrides: float) -> MarkovianConfig:
    values: dict[str, float] = {"max_chunks": 3, "chunk_budget_chars": 2000, "carryover_budget_chars": 1000}
    values.update(overrides)
    return MarkovianConfig(**values)  # type: ignore[arg-type]


def test_stub_payload_satisfies_the_protocol() -> None:
    p: ContextPayload = payload(1)
    assert p.items[0].selection_reason == "supports H2"


def test_first_chunk_has_goal_and_evidence_in_ranked_order() -> None:
    manager = ChunkManager(config())
    chunk = manager.start_chunk(GOAL, context=payload(3, 20), label="plan")
    assert chunk.index == 1
    assert chunk.text.startswith(f"Goal: {GOAL}\n\nEvidence:\n- [obs-1]")
    assert chunk.items_included == ["obs-1", "obs-2", "obs-3"]
    assert chunk.items_dropped == []
    assert "selected because: supports H2" in chunk.text
    assert chunk.text.index("[obs-1]") < chunk.text.index("[obs-2]") < chunk.text.index("[obs-3]")


def test_payload_larger_than_budget_is_cut_to_budget_and_drops_are_recorded() -> None:
    cfg = config()
    big = payload(40, 300)  # about 13,000 chars of evidence against a 2,000-char chunk budget
    assert big.used_chars > cfg.chunk_budget_chars
    manager = ChunkManager(cfg)
    chunk = manager.start_chunk(GOAL, carryover=carryover(), context=big)
    assert chunk.chars <= cfg.chunk_budget_chars
    assert chunk.items_included
    assert chunk.items_dropped
    assert len(chunk.items_included) + len(chunk.items_dropped) == 40
    assert chunk.items_included == [f"obs-{i}" for i in range(1, len(chunk.items_included) + 1)]
    record = manager.records[0]
    assert record.projected_chars == chunk.chars
    assert record.standard_chars > cfg.chunk_budget_chars
    assert record.items_dropped == chunk.items_dropped


def test_a_large_item_is_skipped_and_smaller_ones_after_it_still_fit() -> None:
    items = payload(3, 20)
    items.items.insert(1, StubItem("huge", "observation", "y" * 5000, "too big"))
    chunk = ChunkManager(config()).start_chunk(GOAL, context=items)
    assert chunk.items_dropped == ["huge"]
    assert chunk.items_included == ["obs-1", "obs-2", "obs-3"]


@pytest.mark.parametrize("budget", [1000, 1500, 4000, 12000])
def test_chunk_never_exceeds_budget_with_long_goal_full_carryover_and_huge_payload(budget: int) -> None:
    cfg = config(chunk_budget_chars=budget, carryover_budget_chars=budget // 2, max_chunks=4)
    manager = ChunkManager(cfg)
    long_goal = "Why " + "really " * 2000 + "?"
    full = Carryover([], [], [], 3, cfg.carryover_budget_chars, "truncation", notes="z" * (budget // 2 - 30))
    assert full.used_chars <= cfg.carryover_budget_chars
    for _ in range(cfg.max_chunks):
        chunk = manager.start_chunk(long_goal, carryover=full, context=payload(100, 500))
        assert chunk.chars <= budget


def test_goal_is_clipped_harder_on_continuation_chunks() -> None:
    manager = ChunkManager(config(chunk_budget_chars=8000, carryover_budget_chars=1000))
    long_goal = "word " * 1000
    first = manager.start_chunk(long_goal)
    second = manager.start_chunk(long_goal, carryover=carryover())
    assert first.goal_chars == 8000 // 4
    assert second.goal_chars == GOAL_CONTINUATION_CHARS
    assert "State so far:\nRounds left: 5\nRanking: 1) H3" in second.text


def test_empty_or_missing_payload_says_none_selected() -> None:
    chunk = ChunkManager(config()).start_chunk(GOAL, context=StubPayload())
    assert chunk.text.endswith("Evidence: none selected")
    assert ChunkManager(config()).start_chunk(GOAL).text.endswith("Evidence: none selected")


def test_starting_chunk_max_plus_one_raises_a_defined_error() -> None:
    manager = ChunkManager(config(max_chunks=3))
    for expected_left in (2, 1, 0):
        manager.start_chunk(GOAL)
        assert manager.rounds_left == expected_left
    assert not manager.can_start()
    with pytest.raises(ChunkCapError) as info:
        manager.start_chunk(GOAL)
    assert info.value.index == 4
    assert info.value.max_chunks == 3
    assert "MARKOVIAN_MAX_CHUNKS=3" in str(info.value)
    assert manager.chunks_started == 3  # the refused chunk is not recorded


def test_finish_chunk_records_actual_sizes_and_report_estimates_tokens() -> None:
    manager = ChunkManager(config())
    first = manager.start_chunk(GOAL, context=payload(2, 20), label="plan")
    manager.finish_chunk(first.index, sent_chars=first.chars + 900, output_chars=1201)
    second = manager.start_chunk(GOAL, carryover=carryover(), context=payload(2, 20), label="H3")
    report = manager.report()
    assert [r["label"] for r in report] == ["plan", "H3"]
    assert report[0]["actual_sent_chars"] == first.chars + 900
    assert report[0]["output_tokens"] == estimate_tokens(1201) == 301
    assert report[0]["projected_tokens"] == estimate_tokens(first.chars)
    assert report[1]["actual_sent_chars"] is None
    assert report[1]["carryover_step"] == "explicit_state"
    assert report[1]["carryover_chars"] == len(carryover().render())
    # The growing-conversation size includes the earlier chunk's output; the built input does not.
    assert report[1]["standard_chars"] == len(GOAL) + len("\n".join(render_item(i) for i in payload(2, 20).items)) + 1201
    assert report[1]["projected_chars"] == second.chars


def test_finish_chunk_rejects_unknown_or_repeated_chunks() -> None:
    manager = ChunkManager(config())
    with pytest.raises(ValueError, match="not started"):
        manager.finish_chunk(1, sent_chars=1, output_chars=1)
    manager.start_chunk(GOAL)
    manager.finish_chunk(1, sent_chars=1, output_chars=1)
    with pytest.raises(ValueError, match="already finished"):
        manager.finish_chunk(1, sent_chars=1, output_chars=1)

"""Tests for the World Model context builder (app/engines/world_model/context.py), build-plan task 9."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.data.layer import QueryResult
from app.engines.world_model import context as context_module
from app.engines.world_model.context import ContextBuilder, Intent, serialise
from app.engines.world_model.ingest import IngestPipeline
from app.engines.world_model.store import WorldStore

ROOT = Path(__file__).resolve().parents[1]


def _result(values: list[float], *, sql: str, query_id: str, source: str = "orders") -> QueryResult:
    rows = [{"day": f"2018-06-{i + 1:02d}", "orders": v} for i, v in enumerate(values)]
    return QueryResult(query_id=query_id, source=source, sql=sql, adapter="local", columns=["day", "orders"],
                       rows=rows, row_count=len(rows), truncated=False, duration_ms=1.0)


def _rose(observation: dict) -> str | None:
    rel = observation["rel_change"]
    return None if not rel else ("supports" if rel > 0 else "refutes")


def seed(store: WorldStore, *, reverse: bool = False) -> dict[str, str]:
    """H1 "orders rose": five supporting rises (+80 % … +40 %), two weaker refuting falls (−5 %, −10 %),
    one undirected observation from a second query that tests H1. H2 has its own evidence."""
    pipeline = IngestPipeline(store, agent="investigator")
    question = store.put_entity("question", {"text": "Why did orders change in June?"}, agent="planner", run_id="r1")
    h1 = store.put_entity("hypothesis", {"statement": "Orders rose broadly", "family": "volume",
                                         "question_id": question, "label": "H1", "priority": 1},
                          agent="planner", run_id="r1")
    h2 = store.put_entity("hypothesis", {"statement": "One seller drove the change", "family": "single_seller",
                                         "question_id": question, "label": "H2", "priority": 2},
                          agent="planner", run_id="r1")
    baseline = [{"orders": 100}]
    calls = [
        lambda: pipeline.ingest(_result([180, 170, 160, 150, 140, 95, 90], sql="SELECT orders FROM daily",
                                        query_id="q001"),
                                run_id="r1", hypothesis=h1, window_column="day", baseline_rows=baseline,
                                direction=_rose),
        lambda: pipeline.ingest(_result([130], sql="SELECT orders FROM daily_paid", query_id="q002",
                                        source="payments"),
                                run_id="r1", hypothesis=h1, window_column="day", baseline_rows=baseline),
        lambda: pipeline.ingest(_result([300], sql="SELECT orders FROM top_seller", query_id="q003"),
                                run_id="r1", hypothesis=h2, window_column="day", baseline_rows=baseline,
                                direction="supports"),
    ]
    for call in reversed(calls) if reverse else calls:
        call()
    return {"question": question, "h1": h1, "h2": h2}


@pytest.fixture
def seeded(tmp_path: Path) -> tuple[WorldStore, dict[str, str]]:
    with WorldStore(tmp_path / "world.db") as store:
        yield store, seed(store)


def _directions(payload: dict) -> list[str | None]:
    return [item["summary"].get("direction") for item in payload["items"] if item["type"] == "observation"]


def _check_budget(payload: dict, budget: int) -> None:
    text = serialise(payload)
    assert payload["budget_chars"] == budget
    assert payload["used_chars"] == len(text) <= budget
    kept = {item["id"] for item in payload["items"]}
    assert payload["dropped"]["count"] == payload["candidates"] - len(kept)
    if payload["dropped"]["ids_complete"]:
        assert len(payload["dropped"]["ids"]) == payload["dropped"]["count"]
    assert not kept & set(payload["dropped"]["ids"])


def test_plan_check_task9_critique_has_support_and_refutation_within_budget(seeded) -> None:
    """Plan check (task 9): for a seeded store the critique payload respects the budget and includes
    both the supporting and the refuting evidence."""
    store, ids = seeded
    budget = 2500
    payload = ContextBuilder(store).build(Intent(kind="critique", hypothesis_id=ids["h1"]), budget)
    print("plan check task 9 — critique payload:")
    print(json.dumps(payload, indent=1, sort_keys=True))
    print(f"used_chars={payload['used_chars']} budget_chars={payload['budget_chars']} "
          f"dropped={payload['dropped']['count']}")
    _check_budget(payload, budget)
    directions = _directions(payload)
    assert "supports" in directions and "refutes" in directions
    assert payload["items"][0] == {**payload["items"][0], "id": ids["h1"], "type": "hypothesis"}
    assert payload["items"][0]["summary"]["supports"] == 5 and payload["items"][0]["summary"]["refutes"] == 2


def test_critique_selects_all_evidence_strongest_first(seeded) -> None:
    store, ids = seeded
    payload = ContextBuilder(store).build(Intent(kind="critique", hypothesis_id=ids["h1"]), 100_000)
    observations = [item for item in payload["items"] if item["type"] == "observation"]
    # 7 directed observations from q001 plus the undirected one from q002, nothing from H2.
    assert len(observations) == 8 and payload["dropped"]["count"] == 0
    rels = [abs(item["summary"]["rel_change"]) for item in observations]
    assert rels == sorted(rels, reverse=True)
    assert [o["summary"]["value"] for o in observations][:2] == [180, 170]
    undirected = [o for o in observations if "direction" not in o["summary"]]
    assert len(undirected) == 1 and undirected[0]["summary"]["query_id"] == "q002"
    assert "no direction yet" in undirected[0]["selection_reason"]
    protected = [o for o in observations if "always kept" in o["selection_reason"]]
    assert len(protected) == 1 and protected[0]["summary"]["value"] == 90  # the stronger of the two falls


def test_critique_keeps_refuting_item_until_it_alone_exceeds_budget(seeded) -> None:
    store, ids = seeded
    builder = ContextBuilder(store)
    intent = Intent(kind="critique", hypothesis_id=ids["h1"])
    full = builder.build(intent, 100_000)
    refuting = next(i for i in full["items"] if "always kept" in i["selection_reason"])
    # The smallest budget that still holds the refuting item alone (plus the dropped-id list).
    for budget in range(400, 5000, 25):
        payload = builder.build(intent, budget)
        if payload["items"]:
            break
    assert [item["id"] for item in payload["items"]] == [refuting["id"]]
    assert ids["h1"] in payload["dropped"]["ids"]  # higher priority, but not protected
    _check_budget(payload, budget)
    below = builder.build(intent, budget - 25)
    assert below["items"] == [] and refuting["id"] in below["dropped"]["ids"]
    _check_budget(below, budget - 25)


def test_budget_range_including_below_one_item(seeded) -> None:
    store, ids = seeded
    builder = ContextBuilder(store)
    intents = [Intent(kind="critique", hypothesis_id=ids["h1"]), Intent(kind="investigate", hypothesis_id=ids["h1"]),
               Intent(kind="plan", question_id=ids["question"]), Intent(kind="report")]
    for intent in intents:
        full = builder.build(intent, 1_000_000)
        smallest_item = min(len(serialise(item)) for item in full["items"])
        floor = len(serialise(builder.build(intent, 1_000_000) | {"items": []}))
        budgets = sorted({600, smallest_item - 1, 1000, 1500, 2000, 3000, 5000, full["used_chars"],
                          full["used_chars"] - 1})
        previous_kept = -1
        for budget in budgets:
            try:
                payload = builder.build(intent, budget)
            except ValueError as exc:
                assert "minimum payload" in str(exc)
                assert budget < floor + 50 * full["candidates"]
                continue
            _check_budget(payload, budget)
            assert len(payload["items"]) >= previous_kept or intent.kind == "critique"
            previous_kept = len(payload["items"])
        # The exact size of the complete payload at a budget of that size: it fits; one char less does not.
        exact = builder.build(intent, full["used_chars"])["used_chars"]
        assert builder.build(intent, exact)["dropped"]["count"] == 0
        assert builder.build(intent, exact - 1)["dropped"]["count"] >= 1
    # A budget smaller than any single item: nothing is kept, everything is listed as dropped.
    tiny = builder.build(Intent(kind="investigate", hypothesis_id=ids["h1"]), 300)
    assert tiny["items"] == [] and tiny["dropped"]["count"] == tiny["candidates"] == 5
    _check_budget(tiny, 300)


def test_tiny_budget_lists_as_many_dropped_ids_as_fit_and_rejects_impossible(seeded) -> None:
    store, ids = seeded
    builder = ContextBuilder(store)
    intent = Intent(kind="critique", hypothesis_id=ids["h1"])
    payload = builder.build(intent, 260)
    _check_budget(payload, 260)
    assert payload["items"] == [] and payload["dropped"]["ids_complete"] is False
    assert payload["dropped"]["count"] == 9 and len(payload["dropped"]["ids"]) < 9
    with pytest.raises(ValueError, match="minimum payload"):
        builder.build(intent, 50)


def test_investigate_lists_queries_with_outcomes_and_sources(seeded) -> None:
    store, ids = seeded
    payload = ContextBuilder(store).build(Intent(kind="investigate", hypothesis_id=ids["h1"]), 100_000)
    assert [item["type"] for item in payload["items"]] == ["hypothesis", "query", "query", "source", "source"]
    first, second = payload["items"][1]["summary"], payload["items"][2]["summary"]
    assert first["query_id"] == "q001" and first["observations"] == 7
    assert (first["supports"], first["refutes"], first["alerts"]) == (5, 2, 5)
    assert first["strongest"]["rel_change"] == 0.8
    assert second["query_id"] == "q002" and second["supports"] == second["refutes"] == 0
    assert [item["summary"]["name"] for item in payload["items"][3:]] == ["orders", "payments"]


def test_plan_and_report_show_question_hypotheses_and_top_observations(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ids = seeded
    monkeypatch.setattr(context_module, "TOP_OBSERVATIONS", 4)  # 9 observations exist; the cap applies
    builder = ContextBuilder(store)
    for kind in ("plan", "report"):
        payload = builder.build(Intent(kind=kind, question_id=ids["question"]), 100_000)
        types = [item["type"] for item in payload["items"]]
        assert types[:3] == ["question", "hypothesis", "hypothesis"]
        assert [item["summary"]["label"] for item in payload["items"][1:3]] == ["H1", "H2"]
        assert payload["items"][1]["summary"]["supports"] == 5 and payload["items"][1]["summary"]["refutes"] == 2
        observations = payload["items"][3:]
        assert len(observations) == context_module.TOP_OBSERVATIONS
        assert observations[0]["summary"]["value"] == 300  # H2's +200 % is the strongest effect
        rels = [abs(item["summary"]["rel_change"]) for item in observations]
        assert rels == sorted(rels, reverse=True)
    assert builder.build(Intent(kind="report"), 100_000)["items"][0]["type"] == "question"


def test_every_item_has_a_selection_reason(seeded) -> None:
    store, ids = seeded
    builder = ContextBuilder(store)
    for intent in (Intent(kind="critique", hypothesis_id=ids["h1"]), Intent(kind="investigate", hypothesis_id=ids["h2"]),
                   Intent(kind="plan"), Intent(kind="report", question_id=ids["question"])):
        payload = builder.build(intent, 100_000)
        assert payload["items"]
        for item in payload["items"]:
            assert set(item) == {"id", "type", "summary", "selection_reason"}
            assert isinstance(item["selection_reason"], str) and item["selection_reason"].strip()


def test_payload_is_byte_identical_for_the_same_store_and_intent(tmp_path: Path, seeded) -> None:
    store, ids = seeded
    intents = [Intent(kind="critique", hypothesis_id=ids["h1"]), Intent(kind="investigate", hypothesis_id=ids["h1"]),
               Intent(kind="plan", question_id=ids["question"]), Intent(kind="report")]
    first = [serialise(ContextBuilder(store).build(intent, 1800)) for intent in intents]
    assert first == [serialise(ContextBuilder(store).build(intent, 1800)) for intent in intents]
    with WorldStore(store.path) as reopened:
        assert first == [serialise(ContextBuilder(reopened).build(intent, 1800)) for intent in intents]
    # The same content written in another order gives the same payload too.
    with WorldStore(tmp_path / "reversed.db") as other:
        other_ids = seed(other, reverse=True)
        assert other_ids == ids
        assert first == [serialise(ContextBuilder(other).build(intent, 1800)) for intent in intents]


def test_intent_validation_and_unknown_ids(seeded) -> None:
    store, ids = seeded
    with pytest.raises(ValueError, match="unknown intent kind"):
        Intent(kind="guess")
    with pytest.raises(ValueError, match="needs a hypothesis_id"):
        Intent(kind="critique")
    with pytest.raises(ValueError, match="no hypothesis"):
        ContextBuilder(store).build(Intent(kind="critique", hypothesis_id=ids["question"]), 1000)
    with pytest.raises(ValueError, match="no question"):
        ContextBuilder(store).build(Intent(kind="plan", question_id="qst_missing"), 1000)


def test_context_builder_makes_no_model_calls() -> None:
    source = Path(context_module.__file__).read_text()
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", source, re.MULTILINE)
    assert all(not name.startswith(("app.llm", "app.agents", "openai", "httpx")) for name in imports), imports


def test_sample_cli_prints_critique_payload(tmp_path: Path) -> None:
    env = {**os.environ, "WORLD_DB_PATH": str(tmp_path / "world.db"), "LOG_DIR": str(tmp_path / "logs"),
           "SAMPLE_MODE": "true"}
    out = subprocess.run([sys.executable, "-m", "app.engines.world_model.context", "--sample", "--intent", "critique"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=180, check=True).stdout
    payload = json.loads("\n".join(out.splitlines()[:-1]))
    _check_budget(payload, 4000)
    directions = _directions(payload)
    assert "supports" in directions and "refutes" in directions
    assert "used_chars=" in out.splitlines()[-1]


def test_candidate_cap_counts_the_rest_and_keeps_the_refuting_item(seeded, monkeypatch: pytest.MonkeyPatch) -> None:
    store, ids = seeded
    monkeypatch.setattr(context_module, "MAX_CANDIDATES", 3)
    payload = ContextBuilder(store).build(Intent(kind="critique", hypothesis_id=ids["h1"]), 100_000)
    assert payload["candidates"] == 3 and payload["over_cap"] == 6
    assert [item["type"] for item in payload["items"]] == ["hypothesis", "observation", "observation"]
    assert _directions(payload) == ["supports", "refutes"]  # the refuting item replaced the last slot

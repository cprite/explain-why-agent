"""Tests for the World Model store (app/engines/world_model/store.py), build-plan task 7."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.engines.world_model.store import (
    EDGE_TYPES,
    Checkpoint,
    WorldStore,
    edge_id,
    entity_id,
    entity_type_of,
)

ROOT = Path(__file__).resolve().parents[1]

OBSERVATION = {
    "query_entity_id": "qry_0000000000000001",
    "query_id": "q001",
    "metric": "orders",
    "segment": "state=SP",
    "window": "2018-05-21",
    "baseline_window": "2018-04-23/2018-05-21",
    "value": 120.0,
    "baseline": 160.0,
    "rel_change": -0.25,
}


@pytest.fixture
def store(tmp_path: Path) -> WorldStore:
    with WorldStore(tmp_path / "world.db") as world:
        yield world


def _seed_graph(store: WorldStore, run_id: str = "r1") -> dict[str, str]:
    ids = {
        "source": store.put_entity("source", {"name": "orders"}, agent="ingest", run_id=run_id),
        "query": store.put_entity("query", {"source": "orders", "sql": "SELECT 1"}, agent="ingest", run_id=run_id),
        "hypothesis": store.put_entity("hypothesis", {"statement": "Orders fell", "family": "volume",
                                                      "question_id": None}, agent="planner", run_id=run_id),
    }
    ids["observation"] = store.put_entity(
        "observation", {**OBSERVATION, "query_entity_id": ids["query"]}, agent="ingest", run_id=run_id)
    return ids


def test_world_db_path_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WORLD_DB_PATH", raising=False)
    assert Settings().world_db_path == "logs/world.db"
    monkeypatch.setenv("WORLD_DB_PATH", str(tmp_path / "custom.db"))
    with WorldStore() as world:
        assert world.path == tmp_path / "custom.db"
    assert (tmp_path / "custom.db").is_file()


def test_ids_are_content_hashes_with_type_tags() -> None:
    obs_id = entity_id("observation", OBSERVATION)
    assert re.fullmatch(r"obs_[0-9a-f]{16}", obs_id)
    assert entity_type_of(obs_id) == "observation"
    # Key order, int/float spelling and float noise below 12 significant digits do not change the id.
    reordered = dict(reversed(list(OBSERVATION.items())))
    assert entity_id("observation", reordered) == obs_id
    assert entity_id("observation", {**OBSERVATION, "value": 120}) == obs_id
    assert entity_id("observation", {**OBSERVATION, "value": 120.0 + 1e-13}) == obs_id
    # Non-canonical fields (the run-local query label, derived numbers) do not either ...
    assert entity_id("observation", {**OBSERVATION, "query_id": "q007", "rel_change": None}) == obs_id
    # ... but a canonical field does.
    assert entity_id("observation", {**OBSERVATION, "value": 121.0}) != obs_id
    assert entity_id("observation", {**OBSERVATION, "segment": "state=RJ"}) != obs_id
    # The type is part of the hash: the same name as a metric and a source gives different ids.
    assert entity_id("metric", {"name": "orders"}).split("_")[1] != entity_id("source", {"name": "orders"}).split("_")[1]
    with pytest.raises(ValueError, match="unknown entity type"):
        entity_id("person", {})


def test_ids_are_stable_across_processes() -> None:
    code = (
        "import json, sys; from app.engines.world_model.store import entity_id, edge_id; "
        "obs = json.loads(sys.argv[1]); "
        "print(json.dumps([entity_id('observation', obs), entity_id('source', {'name': 'orders'}), "
        "edge_id('supports', 'obs_a', 'hyp_b')]))"
    )
    expected = [entity_id("observation", OBSERVATION), entity_id("source", {"name": "orders"}),
                edge_id("supports", "obs_a", "hyp_b")]
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
        out = subprocess.run([sys.executable, "-c", code, json.dumps(OBSERVATION)], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=60, check=True)
        assert json.loads(out.stdout) == expected
    # Pinned value: a change to the hashing scheme must be deliberate (it orphans existing stores).
    assert entity_id("source", {"name": "orders"}) == "src_" + __import__("hashlib").sha256(
        b'source:{"name":"orders"}').hexdigest()[:16]


def test_plan_check_task7_same_observation_twice_is_one_record(store: WorldStore) -> None:
    """Plan check (task 7): writing the same observation twice leaves one record and one id; the log
    shows the second write as a no-op."""
    first = store.put_entity("observation", OBSERVATION, agent="investigator", run_id="run-a")
    second = store.put_entity("observation", dict(OBSERVATION), agent="critic", run_id="run-b")
    rows = store.connection.execute("SELECT id, agent, run_id FROM entities WHERE type = 'observation'").fetchall()
    log = [row for row in store.log_rows() if row["target_id"] == first]
    print(f"plan check task 7: ids {first} / {second}; entity rows {[tuple(r) for r in rows]}")
    for row in log:
        print(f"  log seq={row['seq']} agent={row['agent']} run={row['run_id']} op={row['operation']} "
              f"noop={row['noop']}")
    assert first == second
    assert len(rows) == 1
    assert tuple(rows[0]) == (first, "investigator", "run-a")  # the first write is kept
    assert [(r["operation"], r["noop"], r["agent"], r["run_id"]) for r in log] == [
        ("put_entity", False, "investigator", "run-a"),
        ("put_entity", True, "critic", "run-b"),
    ]


def test_edges_record_agent_and_run_and_are_idempotent(store: WorldStore) -> None:
    ids = _seed_graph(store)
    first = store.put_edge("supports", ids["observation"], ids["hypothesis"], agent="critic", run_id="r1")
    again = store.put_edge("supports", ids["observation"], ids["hypothesis"], agent="critic", run_id="r2")
    assert first == again
    edge = store.get_edge(first)
    assert (edge.type, edge.src, edge.dst, edge.agent, edge.run_id) == (
        "supports", ids["observation"], ids["hypothesis"], "critic", "r1")
    assert store.counts()["edges"] == 1
    edge_log = [(r["noop"], r["run_id"]) for r in store.log_rows() if r["target_kind"] == "edge"]
    assert edge_log == [(False, "r1"), (True, "r2")]
    # supports and refutes between the same ends are two different edges.
    assert store.put_edge("refutes", ids["observation"], ids["hypothesis"], agent="critic", run_id="r1") != first


def test_edge_types_and_ends_are_checked(store: WorldStore) -> None:
    ids = _seed_graph(store)
    assert set(EDGE_TYPES) == {"tests", "supports", "refutes", "derived_from", "from_source"}
    with pytest.raises(ValueError, match="unknown edge type"):
        store.put_edge("likes", ids["observation"], ids["hypothesis"], agent="a", run_id="r")
    with pytest.raises(ValueError, match="needs observation -> hypothesis"):
        store.put_edge("supports", ids["query"], ids["hypothesis"], agent="a", run_id="r")
    with pytest.raises(ValueError, match="not in the store"):
        store.put_edge("tests", ids["query"], "hyp_missing", agent="a", run_id="r")
    assert store.counts()["edges"] == 0


def test_read_helpers(store: WorldStore) -> None:
    ids = _seed_graph(store)
    store.put_edge("from_source", ids["query"], ids["source"], agent="ingest", run_id="r1")
    store.put_edge("tests", ids["query"], ids["hypothesis"], agent="ingest", run_id="r1")
    store.put_edge("derived_from", ids["observation"], ids["query"], agent="ingest", run_id="r1")
    other = store.put_entity("observation", {**OBSERVATION, "window": "2018-05-22"}, agent="ingest", run_id="r1")
    store.put_edge("refutes", other, ids["hypothesis"], agent="critic", run_id="r1")

    assert store.get(ids["source"]).content == {"name": "orders"}
    assert store.get("obs_missing") is None
    assert [e.id for e in store.neighbours(ids["query"], "from_source")] == [ids["source"]]
    assert [e.id for e in store.neighbours(ids["hypothesis"], "tests", direction="in")] == [ids["query"]]
    assert [e.id for e in store.observations_for(ids["hypothesis"])] == sorted([ids["observation"], other])
    assert [e.id for e in store.entities("observation")] == sorted([ids["observation"], other])
    assert store.counts()["entities_by_type"] == {"hypothesis": 1, "observation": 2, "query": 1, "source": 1}


def test_log_is_append_only(store: WorldStore) -> None:
    """No UPDATE or DELETE statement ever reaches the database, the log row count only grows, and
    the triggers refuse an UPDATE or DELETE issued directly."""
    statements: list[str] = []
    store.connection.set_trace_callback(statements.append)
    sizes = [store.counts()["log_rows"]]
    for run in ("r1", "r2"):  # the second pass is all no-ops
        ids = _seed_graph(store, run_id=run)
        sizes.append(store.counts()["log_rows"])
        store.put_edge("tests", ids["query"], ids["hypothesis"], agent="ingest", run_id=run)
        store.put_edge("supports", ids["observation"], ids["hypothesis"], agent="critic", run_id=run)
        store.put_checkpoint(Checkpoint(ingest_key="ing_1", query_id="q001", rows_done=1, rows_total=1,
                                        finished=True, truncated=False), agent="ingest", run_id=run)
        sizes.append(store.counts()["log_rows"])
    store.connection.set_trace_callback(None)

    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes), sizes
    assert statements
    writes = [s for s in statements if re.match(r"\s*(UPDATE|DELETE|REPLACE|INSERT\s+OR\s+REPLACE)\b", s, re.IGNORECASE)]
    assert writes == []
    assert all("log" not in s or s.lstrip().upper().startswith(("INSERT", "SELECT")) for s in statements)

    # Every table has rows here (the triggers are row-level), so each statement would touch one.
    for table in ("log", "entities", "edges", "checkpoints"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            store.connection.execute(f"DELETE FROM {table}")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            store.connection.execute(f"UPDATE {table} SET id = id" if table in ("entities", "edges")
                                     else f"UPDATE {table} SET seq = seq")
    assert store.counts()["log_rows"] == sizes[-1]


def test_transaction_rolls_back_every_table(store: WorldStore) -> None:
    before = store.counts()
    with pytest.raises(RuntimeError), store.transaction():
        _seed_graph(store)
        raise RuntimeError("boom")
    assert store.counts() == before


def test_export_log_jsonl(store: WorldStore, tmp_path: Path) -> None:
    _seed_graph(store, run_id="r9")
    path = store.export_log_jsonl("r9", tmp_path / "world-r9.jsonl")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 4
    assert {line["run_id"] for line in lines} == {"r9"}
    assert {"seq", "ts", "agent", "operation", "target_id", "noop"} <= set(lines[0])

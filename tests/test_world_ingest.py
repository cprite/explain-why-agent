"""Tests for the World Model ingest pipeline (app/engines/world_model/ingest.py), build-plan task 8."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.data.layer import QueryError, QueryResult
from app.engines.world_model.ingest import IngestPipeline, effect_size, robust_z
from app.engines.world_model.store import WorldStore
from app.schemas import Hypothesis, Window

ROOT = Path(__file__).resolve().parents[1]
WINDOW = Window(start="2018-05-21", end="2018-05-28")
BASELINE = Window(start="2018-04-23", end="2018-05-21")


def _result(rows: list[dict], *, source: str | None = "orders", sql: str = "SELECT day, orders FROM orders.daily",
            query_id: str = "q001", truncated: bool = False) -> QueryResult:
    columns = list(rows[0]) if rows else ["day", "orders"]
    return QueryResult(query_id=query_id, source=source, sql=sql, adapter="local", columns=columns, rows=rows,
                       row_count=len(rows), truncated=truncated, duration_ms=1.0)


def _daily_rows(n: int) -> list[dict]:
    return [{"day": f"2018-06-{i + 1:02d}" if i < 30 else f"2018-07-{i - 29:02d}", "state": "SP" if i % 2 else "RJ",
             "orders": 100 + i, "payment_value": 1000.0 + 10 * i} for i in range(n)]


def _baseline_rows() -> list[dict]:
    return [{"day": f"2018-05-{d:02d}", "state": s, "orders": 90 + d % 7, "payment_value": 950.0 + d}
            for d in range(1, 21) for s in ("SP", "RJ")]


@pytest.fixture
def store(tmp_path: Path) -> WorldStore:
    with WorldStore(tmp_path / "world.db") as world:
        yield world


def _hypothesis(store: WorldStore) -> str:
    return store.put_entity("hypothesis", {"statement": "Orders rose", "family": "volume", "question_id": None},
                            agent="planner", run_id="r1")


def _snapshot(store: WorldStore) -> tuple[list, list]:
    con = store.connection
    entities = con.execute("SELECT id, type, content, agent, run_id FROM entities ORDER BY id").fetchall()
    edges = con.execute("SELECT id, type, src, dst, agent, run_id FROM edges ORDER BY id").fetchall()
    return [tuple(r) for r in entities], [tuple(r) for r in edges]


# --- effect size and alerts -------------------------------------------------------------------------


def test_effect_size_and_robust_z_helpers() -> None:
    assert effect_size(130.0, 100.0) == pytest.approx((30.0, 0.3))
    assert effect_size(70.0, 100.0) == pytest.approx((-30.0, -0.3))
    assert effect_size(5.0, 0.0) == (5.0, None)
    assert effect_size(5.0, None) == (None, None)
    series = [90.0, 95.0, 100.0, 105.0, 110.0]  # median 100, MAD 5 -> spread 7.413
    assert robust_z(126.0, series) == pytest.approx(26.0 / (1.4826 * 5.0))
    assert robust_z(126.0, series[:2]) is None  # fewer than three points: no z
    assert robust_z(101.0, [100.0, 100.0, 100.0]) == pytest.approx(1.0)  # MAD 0: spread floored at 1 % of median
    assert robust_z(1.0, [0.0, 0.0, 0.0]) is None


@pytest.mark.parametrize(
    ("value", "rel", "alert"),
    [(124.0, 0.24, False), (125.0, 0.25, True), (130.0, 0.30, True), (76.0, -0.24, False), (75.0, -0.25, True)],
)
def test_relative_change_alert_on_both_sides_of_threshold(store: WorldStore, value: float, rel: float,
                                                          alert: bool) -> None:
    pipeline = IngestPipeline(store, alert_rel_change=0.25, alert_z=3.5)
    report = pipeline.ingest(
        _result([{"day": "2018-05-21", "orders": value}]), run_id="r1", window=WINDOW, window_column="day",
        baseline_rows=[{"day": "2018-05-01", "orders": 100}], baseline_window=BASELINE,
    )
    obs = store.get(report.observations[0]).content
    assert obs["baseline"] == 100.0
    assert obs["abs_change"] == pytest.approx(value - 100.0)
    assert obs["rel_change"] == pytest.approx(rel)
    assert obs["z"] is None and obs["baseline_points"] == 1
    assert obs["alert"] is alert
    assert report.alerts == int(alert)
    assert bool(obs["alert_reasons"]) is alert


@pytest.mark.parametrize(("value", "alert"), [(125.0, False), (126.0, True), (74.0, True), (75.0, False)])
def test_robust_z_alert_on_both_sides_of_threshold(store: WorldStore, value: float, alert: bool) -> None:
    # Relative threshold out of reach, so only the z-score can raise the alert: |z| = 3.37 at 125, 3.51 at 126.
    pipeline = IngestPipeline(store, alert_rel_change=10.0, alert_z=3.5)
    baseline = [{"orders": v} for v in (90, 95, 100, 105, 110)]
    report = pipeline.ingest(_result([{"orders": value}]), run_id="r1", baseline_rows=baseline, window=WINDOW)
    obs = store.get(report.observations[0]).content
    assert obs["baseline"] == 100.0 and obs["baseline_points"] == 5
    assert obs["z"] == pytest.approx((value - 100.0) / (1.4826 * 5.0))
    assert obs["alert"] is alert
    assert obs["window"] == "2018-05-21/2018-05-28"


def test_alert_thresholds_and_row_cap_from_environment(monkeypatch: pytest.MonkeyPatch, store: WorldStore) -> None:
    for key in ("ALERT_REL_CHANGE", "ALERT_Z", "MAX_INGEST_ROWS"):
        monkeypatch.delenv(key, raising=False)
    default = IngestPipeline(store)
    assert (default.alert_rel_change, default.alert_z, default.max_rows) == (0.25, 3.5, 5000)
    monkeypatch.setenv("ALERT_REL_CHANGE", "0.1")
    monkeypatch.setenv("ALERT_Z", "2")
    monkeypatch.setenv("MAX_INGEST_ROWS", "7")
    configured = IngestPipeline(store)
    assert (configured.alert_rel_change, configured.alert_z, configured.max_rows) == (0.1, 2.0, 7)


# --- normalisation and edges ------------------------------------------------------------------------


def test_rows_become_observations_with_metric_segment_window_and_edges(store: WorldStore) -> None:
    hyp = _hypothesis(store)
    pipeline = IngestPipeline(store, agent="investigator")
    report = pipeline.ingest(
        _result(_daily_rows(4), source=None,
                sql="SELECT ... FROM orders.orders o JOIN payments.order_payments p ON p.order_id = o.order_id"),
        run_id="r1", hypothesis=hyp, window=WINDOW, window_column="day", segment_columns=["state"],
        baseline_rows=_baseline_rows(), baseline_window=BASELINE,
    )
    assert report.rows_ingested == 4 and not report.noop and not report.truncated
    assert len(report.observations) == 8  # 4 rows x 2 numeric columns
    obs = store.get(report.observations[0]).content
    assert obs["metric"] == "orders" and obs["segment"] == "state=RJ" and obs["window"] == "2018-06-01"
    assert obs["baseline_window"] == "2018-04-23/2018-05-21"
    assert obs["baseline_points"] == 20 and obs["z"] is not None
    assert obs["source"] == "orders+payments" and obs["query_id"] == "q001"
    assert store.get(obs["metric_id"]).type == "metric" and store.get(obs["segment_id"]).type == "segment"

    counts = store.counts()
    assert counts["entities_by_type"] == {"hypothesis": 1, "metric": 2, "observation": 8, "query": 1,
                                          "segment": 2, "source": 2}
    # No direction given: no supports/refutes edges (the Critic decides later).
    assert counts["edges_by_type"] == {"derived_from": 8, "from_source": 2, "tests": 1}
    query = store.get(report.query_entity_id)
    assert sorted(e.content["name"] for e in store.neighbours(query.id, "from_source")) == ["orders", "payments"]
    assert [e.id for e in store.neighbours(query.id, "tests")] == [hyp]
    for edge in store.edges(report.observations[0], "derived_from"):
        assert (edge.dst, edge.agent, edge.run_id) == (query.id, "investigator", "r1")


def test_direction_writes_supports_or_refutes(store: WorldStore) -> None:
    hyp = _hypothesis(store)
    pipeline = IngestPipeline(store)
    rows = [{"orders": 150}, {"orders": 80}, {"orders": 100}]
    pipeline.ingest(_result(rows), run_id="r1", hypothesis=hyp, baseline_rows=[{"orders": 100}],
                    direction=lambda o: None if o["rel_change"] == 0 else ("supports" if o["rel_change"] > 0
                                                                          else "refutes"))
    assert [e.content["value"] for e in store.neighbours(hyp, "supports", direction="in")] == [150.0]
    assert [e.content["value"] for e in store.neighbours(hyp, "refutes", direction="in")] == [80.0]
    pipeline.ingest(_result([{"orders": 60}], query_id="q002", sql="SELECT 2"), run_id="r1", hypothesis=hyp,
                    direction="refutes")
    assert len(store.edges(hyp, "refutes", direction="in")) == 2
    with pytest.raises(ValueError, match="needs a hypothesis"):
        pipeline.ingest(_result([{"orders": 1}], sql="SELECT 3"), run_id="r1", direction=True)


def test_planner_hypothesis_is_written_and_tested(store: WorldStore) -> None:
    hypothesis = Hypothesis(id="H1", family="volume", statement="Orders rose broadly", priority=1,
                            test={"description": "daily orders"})
    report = IngestPipeline(store).ingest(_result([{"orders": 5}]), run_id="r1", hypothesis=hypothesis)
    [hyp] = store.entities("hypothesis")
    assert hyp.content["label"] == "H1" and hyp.content["statement"] == "Orders rose broadly"
    assert [e.id for e in store.neighbours(report.query_entity_id, "tests")] == [hyp.id]


def test_failed_query_is_refused(store: WorldStore) -> None:
    error = QueryError(query_id="q001", source="orders", sql="DELETE", adapter="local", code="rejected",
                       message="nope")
    with pytest.raises(ValueError, match="failed query"):
        IngestPipeline(store).ingest(error, run_id="r1")


# --- idempotence, resume, caps ----------------------------------------------------------------------


def test_reingest_is_a_noop(store: WorldStore) -> None:
    pipeline = IngestPipeline(store)
    kwargs = {"run_id": "r1", "hypothesis": _hypothesis(store), "window_column": "day", "segment_columns": ["state"],
              "baseline_rows": _baseline_rows()}
    first = pipeline.ingest(_result(_daily_rows(6)), **kwargs)
    snapshot, log_size = _snapshot(store), store.counts()["log_rows"]
    second = pipeline.ingest(_result(_daily_rows(6)), **kwargs)
    assert second.noop and second.rows_ingested == 0 and second.ingest_key == first.ingest_key
    assert _snapshot(store) == snapshot
    assert store.counts()["log_rows"] == log_size  # a finished ingest writes nothing at all
    # A different run of the same query (new query label, new run id) adds no observations either.
    third = pipeline.ingest(_result(_daily_rows(6), query_id="q042"), **{**kwargs, "run_id": "r2"})
    assert third.noop


def test_plan_check_task8_interrupted_ingest_resumes_without_duplicates(tmp_path: Path) -> None:
    """Plan check (task 8): an ingest interrupted after N rows resumes from its checkpoint and ends
    with exactly the same records as an uninterrupted run, with no duplicates."""
    rows, fail_after, batch = _daily_rows(25), 10, 4

    def run(store: WorldStore, pipeline: IngestPipeline):
        return pipeline.ingest(_result(rows), run_id="r1", hypothesis=_hypothesis(store), window=WINDOW,
                               window_column="day", segment_columns=["state"], baseline_rows=_baseline_rows(),
                               baseline_window=BASELINE, direction=lambda o: "supports")

    with WorldStore(tmp_path / "clean.db") as clean:
        clean_report = run(clean, IngestPipeline(clean, checkpoint_every=batch))
        expected = _snapshot(clean)

    with WorldStore(tmp_path / "interrupted.db") as store:
        pipeline = IngestPipeline(store, checkpoint_every=batch)
        real_row = pipeline._ingest_row
        calls = {"n": 0}

        def failing_row(ctx, index, row):
            if calls["n"] == fail_after:
                raise RuntimeError(f"simulated crash at row {index}")
            calls["n"] += 1
            return real_row(ctx, index, row)

        pipeline._ingest_row = failing_row
        with pytest.raises(RuntimeError, match="simulated crash at row 10"):
            run(store, pipeline)
        checkpoint = store.latest_checkpoint(clean_report.ingest_key)
        partial = store.counts()["entities_by_type"]["observation"]

        resumed = run(store, IngestPipeline(store, checkpoint_every=batch))
        final = _snapshot(store)
        again = run(store, IngestPipeline(store, checkpoint_every=batch))

    print(f"plan check task 8: crash after {fail_after} rows (batches of {batch}); checkpoint rows_done="
          f"{checkpoint.rows_done}; {partial} observations committed before the crash")
    print(f"  resumed from row {resumed.resumed_from}: {resumed.rows_ingested} rows, "
          f"{len(resumed.observations)} observations; finished={store_finished(tmp_path)}")
    print(f"  uninterrupted: {len(expected[0])} entities, {len(expected[1])} edges; "
          f"interrupted+resumed: {len(final[0])} entities, {len(final[1])} edges; identical={final == expected}")
    assert checkpoint.rows_done == 8 and not checkpoint.finished  # the batch holding row 10 rolled back
    assert partial == 8 * 2
    assert resumed.resumed_from == 8 and resumed.rows_ingested == 17
    assert final == expected
    obs_ids = [row[0] for row in final[0] if row[1] == "observation"]
    assert len(obs_ids) == len(set(obs_ids)) == 25 * 2
    assert again.noop


def store_finished(tmp_path: Path) -> bool:
    with WorldStore(tmp_path / "interrupted.db") as store:
        keys = store.connection.execute("SELECT DISTINCT ingest_key FROM checkpoints").fetchall()
        return all(store.latest_checkpoint(key[0]).finished for key in keys)


def test_ingest_stops_at_max_ingest_rows_and_records_truncation(store: WorldStore) -> None:
    pipeline = IngestPipeline(store, max_rows=5, checkpoint_every=2)
    report = pipeline.ingest(_result(_daily_rows(12)), run_id="r1", window_column="day", segment_columns=["state"],
                             value_columns=["orders"])
    assert report.truncated and report.rows_total == 12 and report.rows_capped == 5 and report.rows_ingested == 5
    assert store.counts()["entities_by_type"]["observation"] == 5
    checkpoint = store.latest_checkpoint(report.ingest_key)
    assert checkpoint.finished and checkpoint.truncated and checkpoint.rows_done == 5 and checkpoint.rows_total == 12
    last = [row for row in store.log_rows() if row["operation"] == "checkpoint"][-1]
    assert last["detail"]["truncated"] is True and last["detail"]["rows_total"] == 12
    # The data layer's own truncation is reported separately.
    assert IngestPipeline(store).ingest(_result([{"orders": 1}], sql="SELECT 9", truncated=True),
                                        run_id="r1").source_truncated


def test_sample_demo_twice_prints_identical_counts(tmp_path: Path) -> None:
    env = {**os.environ, "WORLD_DB_PATH": str(tmp_path / "world.db"), "LOG_DIR": str(tmp_path / "logs"),
           "SAMPLE_MODE": "true"}
    outputs = []
    for _ in range(2):
        out = subprocess.run([sys.executable, "-m", "app.engines.world_model.ingest", "--sample"], cwd=ROOT,
                             env=env, capture_output=True, text=True, timeout=180, check=True)
        outputs.append(out.stdout)
    counts = [[line for line in text.splitlines() if line.startswith("COUNTS ")] for text in outputs]
    assert len(counts[0]) == 1 and counts[0] == counts[1]
    assert '"observation": 42' in counts[0][0]
    assert "no-op" in outputs[1]

"""IngestPipeline: query results into World Model observations (architecture §5.1).

`IngestPipeline.ingest` takes one `QueryResult` from `DataLayer.query`, the hypothesis it tests and
the baseline rows, and writes:

- one Observation per (row, value column): metric, segment, window, value, baseline value, absolute
  and relative change, a robust z-score where the baseline is a series (three or more points) and an
  alert flag when |relative change| >= `ALERT_REL_CHANGE` or |z| >= `ALERT_Z`;
- the Query, Source, Metric and Segment entities they refer to;
- edges `derived_from` (observation → query), `from_source` (query → source), `tests` (query →
  hypothesis) and, only when the caller passes a direction, `supports` / `refutes`.

The ingest is idempotent and resumable. Rows are written in batches; each batch commits together with
an append-only checkpoint (rows done so far) keyed by the query and the ingest inputs. An interrupted
ingest resumes after the last committed batch; a finished one is a no-op. At most `MAX_INGEST_ROWS`
rows are ingested; the rest is skipped and the checkpoint says the ingest was truncated.

Sample-mode demo (one real query on the sample data through the local DuckDB adapter):

    python -m app.engines.world_model.ingest --sample
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.data.layer import QueryError, QueryResult
from app.data.local import DEFAULT_SOURCES
from app.engines.world_model.store import (
    Checkpoint,
    WorldStore,
    canonical_json,
    entity_id,
)
from app.schemas import Hypothesis, Window

MIN_SERIES_POINTS = 3
"""A baseline needs this many points before a robust z-score is computed."""

MAD_SCALE = 1.4826
"""Scales the median absolute deviation to a standard deviation under normality."""

MAD_FLOOR = 0.01
"""The robust spread is floored at 1 % of |baseline median| (the scanner's rule, decision D-2ea141)."""

Direction = str | bool | Callable[[dict[str, Any]], str | bool | None] | None
"""`"supports"` / `"refutes"` (or True / False) for every observation, a function of the
observation's fields returning one of those (or None), or None for no direction."""


@dataclass(frozen=True)
class IngestReport:
    """What one `ingest` call did."""

    ingest_key: str
    query_id: str
    query_entity_id: str
    rows_total: int
    rows_capped: int
    rows_ingested: int
    resumed_from: int
    truncated: bool
    source_truncated: bool
    observations: list[str] = field(default_factory=list)
    alerts: int = 0
    noop: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form."""
        return asdict(self)


def robust_z(value: float, series: Sequence[float]) -> float | None:
    """(value − median) / (1.4826 × MAD), the spread floored at 1 % of |median|.

    None when the series is shorter than `MIN_SERIES_POINTS` or the spread is zero.
    """
    if len(series) < MIN_SERIES_POINTS:
        return None
    median = statistics.median(series)
    mad = statistics.median(abs(x - median) for x in series)
    spread = max(MAD_SCALE * mad, MAD_FLOOR * abs(median))
    if spread == 0:
        return None
    return (value - median) / spread


def effect_size(value: float, baseline: float | None) -> tuple[float | None, float | None]:
    """(absolute change, relative change) of a value against its baseline.

    The relative change is None when the baseline is missing or zero.
    """
    if baseline is None:
        return None, None
    absolute = value - baseline
    relative = None if baseline == 0 else value / baseline - 1.0
    return absolute, relative


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _window_label(window: Window | None) -> str | None:
    return f"{window.start}/{window.end}" if window else None


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sql_sources(sql: str) -> list[str]:
    """Sources named as `<source>.<table>` qualifiers in a cross-source statement."""
    found = {m.group(1).lower() for m in re.finditer(r"\b([A-Za-z_]+)\.[A-Za-z_]", sql)}
    return [source for source in DEFAULT_SOURCES if source in found]


def _direction_label(direction: Direction) -> str | None:
    if callable(direction):
        return f"fn:{getattr(direction, '__module__', '')}.{getattr(direction, '__qualname__', repr(direction))}"
    return None if direction is None else str(direction)


def _edge_for(direction: str | bool | None) -> str | None:
    if direction is True or direction == "supports":
        return "supports"
    if direction is False or direction == "refutes":
        return "refutes"
    if direction is None:
        return None
    raise ValueError(f"direction must be 'supports', 'refutes', True, False or None, got {direction!r}")


@dataclass
class _Context:
    """Everything one ingest needs per row; built once per call."""

    run_id: str
    agent: str
    query_entity_id: str
    query_id: str
    sources: list[str]
    hypothesis_id: str | None
    window: str | None
    baseline_window: str | None
    window_column: str | None
    segment_columns: tuple[str, ...]
    value_columns: tuple[str, ...]
    baselines: dict[tuple[str, str], list[float]]
    direction: Direction
    written: set[str] = field(default_factory=set)


class IngestPipeline:
    """Normalise query results into Observation entities with provenance edges."""

    def __init__(
        self,
        store: WorldStore,
        *,
        settings: Settings | None = None,
        alert_rel_change: float | None = None,
        alert_z: float | None = None,
        max_rows: int | None = None,
        checkpoint_every: int = 100,
        agent: str = "ingest",
    ) -> None:
        settings = settings or get_settings()
        self.store = store
        self.alert_rel_change = alert_rel_change if alert_rel_change is not None else settings.alert_rel_change
        self.alert_z = alert_z if alert_z is not None else settings.alert_z
        self.max_rows = max_rows if max_rows is not None else settings.max_ingest_rows
        if checkpoint_every < 1:
            raise ValueError("checkpoint_every must be at least 1")
        self.checkpoint_every = checkpoint_every
        self.agent = agent

    # --- public ----------------------------------------------------------------------------------

    def put_hypothesis(
        self, hypothesis: Hypothesis | str, *, run_id: str, question_id: str | None = None, agent: str | None = None
    ) -> str:
        """Write a hypothesis entity (from the Planner's `Hypothesis` or a bare statement); return its id."""
        if isinstance(hypothesis, Hypothesis):
            fields = {"statement": hypothesis.statement, "family": hypothesis.family, "question_id": question_id,
                      "label": hypothesis.id, "priority": hypothesis.priority}
        else:
            fields = {"statement": hypothesis, "family": None, "question_id": question_id}
        return self.store.put_entity("hypothesis", fields, agent=agent or self.agent, run_id=run_id)

    def is_alert(self, rel_change: float | None, z: float | None) -> list[str]:
        """The thresholds an observation crosses (empty list: no alert)."""
        reasons = []
        if rel_change is not None and abs(rel_change) >= self.alert_rel_change:
            reasons.append(f"|relative change| {abs(rel_change):.4g} >= {self.alert_rel_change:g}")
        if z is not None and abs(z) >= self.alert_z:
            reasons.append(f"|robust z| {abs(z):.4g} >= {self.alert_z:g}")
        return reasons

    def ingest(
        self,
        result: QueryResult,
        *,
        run_id: str,
        hypothesis: Hypothesis | str | None = None,
        window: Window | None = None,
        baseline_rows: Sequence[dict[str, Any]] | None = None,
        baseline_window: Window | None = None,
        window_column: str | None = None,
        segment_columns: Sequence[str] = (),
        value_columns: Sequence[str] | None = None,
        direction: Direction = None,
        sources: Sequence[str] | None = None,
        agent: str | None = None,
    ) -> IngestReport:
        """Ingest one query result; see the module docstring.

        `hypothesis` is a stored hypothesis id, a Planner `Hypothesis` (written here) or None (the
        change check). Each row gives one observation per value column (default: every numeric
        column that is not the window or a segment column). `window_column` labels each row's window
        (for daily rows); otherwise the row's window is `window`. The baseline for a row is the
        median of `baseline_rows` with the same segment; with three or more baseline points a robust
        z-score is computed too.
        """
        if isinstance(result, QueryError) or not getattr(result, "ok", False):
            raise ValueError(f"cannot ingest a failed query: {getattr(result, 'message', result)}")
        agent = agent or self.agent
        segment_columns = tuple(segment_columns)
        if value_columns is None:
            value_columns = self._numeric_columns(result, {window_column, *segment_columns})
        value_columns = tuple(value_columns)
        source_names = list(sources) if sources else ([result.source] if result.source else _sql_sources(result.sql))
        source_names = source_names or ["unknown"]
        query_fields = {"source": "+".join(source_names), "sql": " ".join(result.sql.split()),
                        "query_id": result.query_id, "adapter": result.adapter}
        query_entity_id = entity_id("query", query_fields)

        hypothesis_id = hypothesis if isinstance(hypothesis, str) else None
        if isinstance(hypothesis, Hypothesis):
            hypothesis_id = entity_id("hypothesis", {"statement": hypothesis.statement, "family": hypothesis.family,
                                                     "question_id": None})

        rows = result.rows
        capped = rows[: self.max_rows]
        truncated = len(rows) > len(capped)
        ingest_key = "ing_" + _digest({
            "query": query_entity_id, "hypothesis": hypothesis_id, "rows": _digest(rows),
            "baseline_rows": _digest(list(baseline_rows or [])), "window": _window_label(window),
            "baseline_window": _window_label(baseline_window), "window_column": window_column,
            "segment_columns": segment_columns, "value_columns": value_columns,
            "direction": _direction_label(direction), "max_rows": self.max_rows,
        })[:16]

        def report(**kwargs: Any) -> IngestReport:
            return IngestReport(ingest_key=ingest_key, query_id=result.query_id, query_entity_id=query_entity_id,
                                rows_total=len(rows), rows_capped=len(capped), truncated=truncated,
                                source_truncated=result.truncated, **kwargs)

        checkpoint = self.store.latest_checkpoint(ingest_key)
        if checkpoint is not None and checkpoint.finished:
            return report(rows_ingested=0, resumed_from=checkpoint.rows_done, noop=True)
        start = checkpoint.rows_done if checkpoint else 0

        ctx = _Context(
            run_id=run_id, agent=agent, query_entity_id=query_entity_id, query_id=result.query_id,
            sources=source_names, hypothesis_id=hypothesis_id, window=_window_label(window),
            baseline_window=_window_label(baseline_window), window_column=window_column,
            segment_columns=segment_columns, value_columns=value_columns,
            baselines=self._baselines(baseline_rows or [], segment_columns, value_columns), direction=direction,
        )
        observations: list[str] = []
        alerts = 0
        with self.store.transaction():
            self._write_query(ctx, query_fields, hypothesis)
        # One loop iteration per batch: bounded by the row cap.
        batch_start = start
        while True:
            batch_end = min(batch_start + self.checkpoint_every, len(capped))
            with self.store.transaction():
                for index in range(batch_start, batch_end):
                    for obs_id, alert in self._ingest_row(ctx, index, capped[index]):
                        observations.append(obs_id)
                        alerts += alert
                self.store.put_checkpoint(
                    Checkpoint(ingest_key=ingest_key, query_id=result.query_id, rows_done=batch_end,
                               rows_total=len(rows), finished=batch_end >= len(capped), truncated=truncated),
                    agent=agent, run_id=run_id,
                )
            batch_start = batch_end
            if batch_end >= len(capped):
                break
        return report(rows_ingested=len(capped) - start, resumed_from=start, observations=observations,
                      alerts=alerts)

    # --- internals -------------------------------------------------------------------------------

    @staticmethod
    def _numeric_columns(result: QueryResult, exclude: set[str | None]) -> tuple[str, ...]:
        columns = []
        for column in result.columns:
            if column in exclude:
                continue
            values = [row.get(column) for row in result.rows if row.get(column) is not None]
            if values and all(_is_number(v) for v in values):
                columns.append(column)
        return tuple(columns)

    @staticmethod
    def _segment(row: dict[str, Any], segment_columns: tuple[str, ...]) -> str:
        if not segment_columns:
            return "all"
        return ",".join(f"{column}={row.get(column)}" for column in segment_columns)

    def _baselines(
        self, rows: Sequence[dict[str, Any]], segment_columns: tuple[str, ...], value_columns: tuple[str, ...]
    ) -> dict[tuple[str, str], list[float]]:
        series: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            segment = self._segment(row, segment_columns)
            for metric in value_columns:
                value = row.get(metric)
                if _is_number(value):
                    series.setdefault((metric, segment), []).append(float(value))
        return series

    def _put_once(self, ctx: _Context, entity_type: str, fields: dict[str, Any]) -> str:
        """Write an entity at most once per ingest call (later rows reuse it without a log no-op)."""
        key = entity_id(entity_type, fields)
        if key not in ctx.written:
            self.store.put_entity(entity_type, fields, agent=ctx.agent, run_id=ctx.run_id)
            ctx.written.add(key)
        return key

    def _write_query(self, ctx: _Context, query_fields: dict[str, Any], hypothesis: Hypothesis | str | None) -> None:
        self.store.put_entity("query", query_fields, agent=ctx.agent, run_id=ctx.run_id)
        for name in ctx.sources:
            source_id = self.store.put_entity("source", {"name": name}, agent=ctx.agent, run_id=ctx.run_id)
            self.store.put_edge("from_source", ctx.query_entity_id, source_id, agent=ctx.agent, run_id=ctx.run_id)
        if isinstance(hypothesis, Hypothesis):
            self.put_hypothesis(hypothesis, run_id=ctx.run_id, agent=ctx.agent)
        if ctx.hypothesis_id is not None:
            self.store.put_edge("tests", ctx.query_entity_id, ctx.hypothesis_id, agent=ctx.agent, run_id=ctx.run_id)

    def _ingest_row(self, ctx: _Context, index: int, row: dict[str, Any]) -> list[tuple[str, bool]]:
        """Write the observations of one row; return (observation id, alert) pairs."""
        segment = self._segment(row, ctx.segment_columns)
        window = str(row.get(ctx.window_column)) if ctx.window_column else ctx.window
        written = []
        for metric in ctx.value_columns:
            value = row.get(metric)
            if not _is_number(value):
                continue
            value = float(value)
            series = ctx.baselines.get((metric, segment), [])
            baseline = statistics.median(series) if series else None
            absolute, relative = effect_size(value, baseline)
            z = robust_z(value, series)
            reasons = self.is_alert(relative, z)
            fields = {
                "query_entity_id": ctx.query_entity_id, "query_id": ctx.query_id, "source": "+".join(ctx.sources),
                "metric": metric, "metric_id": self._put_once(ctx, "metric", {"name": metric}),
                "segment": segment, "segment_id": self._put_once(ctx, "segment", {"name": segment}),
                "window": window, "baseline_window": ctx.baseline_window,
                "value": value, "baseline": baseline, "baseline_points": len(series),
                "abs_change": absolute, "rel_change": relative, "z": z,
                "alert": bool(reasons), "alert_reasons": reasons,
                "hypothesis_id": ctx.hypothesis_id, "row_index": index,
            }
            obs_id = self.store.put_entity("observation", fields, agent=ctx.agent, run_id=ctx.run_id)
            self.store.put_edge("derived_from", obs_id, ctx.query_entity_id, agent=ctx.agent, run_id=ctx.run_id)
            direction = ctx.direction(fields) if callable(ctx.direction) else ctx.direction
            edge_type = _edge_for(direction)
            if edge_type is not None:
                if ctx.hypothesis_id is None:
                    raise ValueError("a supports/refutes direction needs a hypothesis")
                self.store.put_edge(edge_type, obs_id, ctx.hypothesis_id, agent=ctx.agent, run_id=ctx.run_id)
            written.append((obs_id, bool(reasons)))
        return written


# --- sample-mode demo --------------------------------------------------------------------------------

SAMPLE_RUN_ID = "sample-world"
SAMPLE_QUESTION = "Why did daily orders in SP, RJ and MG change in the week from 21 May 2018?"
SAMPLE_HYPOTHESIS = (
    "Daily orders and payment value in SP, RJ and MG fell in the week from 21 May 2018 "
    "against the four weeks before."
)
SAMPLE_WINDOW = Window(start="2018-05-21", end="2018-05-28")
SAMPLE_BASELINE = Window(start="2018-04-23", end="2018-05-21")
SAMPLE_SQL = """
SELECT CAST(o.order_purchase_timestamp AS DATE)  AS day,
       c.customer_state                         AS state,
       count(DISTINCT o.order_id)               AS orders,
       round(sum(p.payment_value), 2)           AS payment_value
FROM orders.orders AS o
JOIN orders.customers AS c ON c.customer_id = o.customer_id
JOIN payments.order_payments AS p ON p.order_id = o.order_id
WHERE o.order_purchase_timestamp >= TIMESTAMP '2018-04-23'
  AND o.order_purchase_timestamp <  TIMESTAMP '2018-05-28'
  AND c.customer_state IN ('SP', 'RJ', 'MG')
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


def sample_direction(observation: dict[str, Any]) -> str | None:
    """The demo's stand-in for the Critic: a fall supports the hypothesis, a rise refutes it."""
    rel = observation.get("rel_change")
    if rel is None or rel == 0:
        return None
    return "supports" if rel < 0 else "refutes"


def seed_sample(store: WorldStore, *, run_id: str = SAMPLE_RUN_ID, settings: Settings | None = None) -> dict[str, Any]:
    """Run the demo query on the sample data and ingest it; return the ids and the ingest report.

    The query returns daily orders and payment value per state for five weeks. The last week is the
    window (one observation per day, state and metric); the four weeks before are the baseline series.
    """
    from app.data.local import LocalDataLayer

    settings = settings or get_settings()
    with LocalDataLayer(run_id=run_id, settings=settings) as layer:
        result = layer.query(None, SAMPLE_SQL)
    if not result.ok:
        raise RuntimeError(f"sample query failed: {result.code}: {result.message}")
    window_rows = [row for row in result.rows if str(row["day"]) >= SAMPLE_WINDOW.start]
    baseline_rows = [row for row in result.rows if str(row["day"]) < SAMPLE_WINDOW.start]
    window_result = QueryResult(**{**result.to_dict(), "rows": window_rows, "row_count": len(window_rows)})

    pipeline = IngestPipeline(store, settings=settings, agent="investigator")
    question_id = store.put_entity("question", {"text": SAMPLE_QUESTION}, agent="planner", run_id=run_id)
    hypothesis_id = pipeline.put_hypothesis(
        Hypothesis(id="H1", family="volume", statement=SAMPLE_HYPOTHESIS, priority=1,
                   test={"description": "Daily orders and payment value per state, window vs four weeks before",
                         "sources": ["orders", "payments"]}),
        run_id=run_id, question_id=question_id, agent="planner",
    )
    report = pipeline.ingest(
        window_result, run_id=run_id, hypothesis=hypothesis_id, window=SAMPLE_WINDOW,
        baseline_rows=baseline_rows, baseline_window=SAMPLE_BASELINE, window_column="day",
        segment_columns=("state",), value_columns=("orders", "payment_value"), direction=sample_direction,
    )
    return {"question_id": question_id, "hypothesis_id": hypothesis_id, "report": report,
            "query_rows": result.row_count}


def main(argv: list[str] | None = None) -> int:
    """`python -m app.engines.world_model.ingest --sample [--db PATH] [--run-id ID]`."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sample", action="store_true", help="ingest one real query on the sample data")
    parser.add_argument("--db", default=None, help="SQLite file (default WORLD_DB_PATH, logs/world.db)")
    parser.add_argument("--run-id", default=SAMPLE_RUN_ID)
    args = parser.parse_args(argv)
    if not args.sample:
        print("only sample mode exists so far: pass --sample", file=sys.stderr)
        return 2
    with WorldStore(args.db) as store:
        seeded = seed_sample(store, run_id=args.run_id)
        report: IngestReport = seeded["report"]
        counts = store.counts()
        print(f"world store: {store.path}")
        print(f"query {report.query_id} ({report.query_entity_id}): {seeded['query_rows']} rows, "
              f"{report.rows_total} in the window")
        if report.noop:
            print(f"ingest {report.ingest_key}: already finished, nothing written (no-op)")
        else:
            print(f"ingest {report.ingest_key}: {report.rows_ingested} rows from row {report.resumed_from}, "
                  f"{len(report.observations)} observations, {report.alerts} alerts, truncated={report.truncated}")
        print("COUNTS " + json.dumps({"entities": counts["entities_by_type"], "edges": counts["edges_by_type"]},
                                     sort_keys=True))
        print(f"totals: {counts['entities']} entities, {counts['edges']} edges, "
              f"{counts['log_rows']} log rows (the log only grows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

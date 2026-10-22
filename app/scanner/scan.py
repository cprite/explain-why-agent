"""Scan every configured metric and segment, rank the flagged episodes and build anomaly cards.

Steps (docs/architecture.md §6a): one query per metric and segment type -> one series per segment ->
detect.score_series -> episodes -> score = |z| x ln(volume) -> Adtributor attribution for the top
episodes -> parent/child merge (a whole-shop card whose attribution names a flagged child absorbs
that child's card) -> top ten cards.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np

from app.config import get_settings
from app.scanner import db
from app.scanner.attribution import DimensionResult, SliceValues, attribute
from app.scanner.detect import Episode, SeriesScore, find_episodes, score_series
from app.scanner.models import (
    AnomalyCard,
    DimensionAttribution,
    Period,
    ScanReport,
    Segment,
    SliceAttribution,
)
from app.scanner.settings import Metric, ScannerConfig, load_config, timeout_seconds

RunSql = Callable[[str], list[dict]]
WHOLE_SHOP = "all"


class ScanTimeout(RuntimeError):
    """The run reached SCANNER_TIMEOUT_S or a loop cap."""


@dataclass
class Series:
    metric: Metric
    segment_type: str
    segment_value: str
    periods: list[date]
    num: np.ndarray
    den: np.ndarray | None
    volume: np.ndarray
    score: SeriesScore | None = None

    @property
    def values(self) -> np.ndarray:
        if self.den is None:
            return self.num.astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.den > 0, self.num / np.where(self.den > 0, self.den, 1), np.nan)


@dataclass
class Candidate:
    series: Series
    episode: Episode
    score: float
    attribution: list[DimensionResult] | None = None
    merged: list[Candidate] = field(default_factory=list)

    @property
    def start(self) -> date:
        return self.series.periods[self.episode.start]

    @property
    def end(self) -> date:
        last = self.series.periods[self.episode.end]
        return last + timedelta(days=6) if self.series.metric.grain == "week" else last


@dataclass
class ScanResult:
    report: ScanReport
    candidates: list[Candidate]  # every episode, best first (merged children removed)
    series: dict[tuple[str, str, str], Series]


def sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class Budget:
    """Wall-clock deadline plus a query cap; every loop checks it."""

    def __init__(self, timeout_s: float, max_queries: int) -> None:
        self.deadline = time.monotonic() + timeout_s
        self.max_queries = max_queries
        self.queries = 0

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def check(self) -> None:
        if self.remaining() <= 0:
            raise ScanTimeout("time cap reached")

    def take_query(self) -> float:
        self.check()
        if self.queries >= self.max_queries:
            raise ScanTimeout(f"query cap of {self.max_queries} reached")
        self.queries += 1
        return self.remaining()


class Scanner:
    def __init__(
        self,
        config: ScannerConfig | None = None,
        run_sql: Callable[..., list[dict]] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.config = config or load_config()
        self._run_sql = run_sql or db.run_sql
        self.budget = Budget(timeout_s or timeout_seconds(), self.config.limits.max_queries)

    # ------------------------------------------------------------------ data
    def query(self, sql: str) -> list[dict]:
        remaining = self.budget.take_query()
        if self._run_sql is db.run_sql:
            return db.run_sql(sql, timeout_s=min(remaining, _query_timeout()))
        return self._run_sql(sql)

    def _period_expr(self, metric: Metric) -> str:
        return self.config.grains[metric.grain].replace("{col}", metric.time)

    def _where(self, metric: Metric, extra: list[str] | None = None) -> str:
        clauses = [f"{metric.time} IS NOT NULL"]
        if metric.filter:
            clauses.append(f"({metric.filter})")
        clauses.extend(extra or [])
        return " AND ".join(clauses)

    def series_sql(self, metric: Metric, segment_type: str) -> str:
        period = self._period_expr(metric)
        column = self.config.segment(segment_type).column
        segment_expr = column if column else sql_literal(WHOLE_SHOP)
        group_by = f"{period}, {column}" if column else period
        den = metric.denominator or "NULL"
        return (
            f"SELECT {period} AS period, {segment_expr} AS segment, {metric.numerator} AS num, "
            f"{den} AS den, {metric.volume} AS volume "
            f"FROM ({self.config.fact_sql(metric.fact).strip()}) f "
            f"WHERE {self._where(metric)} GROUP BY {group_by}"
        )

    def range_sql(self, metric: Metric) -> str:
        return (
            f"SELECT MIN(CAST({metric.time} AS DATE)) AS first_day, MAX(CAST({metric.time} AS DATE)) AS last_day "
            f"FROM ({self.config.fact_sql(metric.fact).strip()}) f WHERE {self._where(metric)}"
        )

    def load_series(self, metric: Metric, segment_type: str, first_day: date, last_day: date) -> list[Series]:
        rows = self.query(self.series_sql(metric, segment_type))
        step = 1 if metric.grain == "day" else 7
        periods = _complete_periods(rows, first_day, last_day, step)
        if not periods:
            return []
        index = {p: i for i, p in enumerate(periods)}
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(str(row["segment"]), []).append(row)
        segment_cfg = self.config.segment(segment_type)
        out: list[Series] = []
        for value in sorted(grouped):
            num = np.zeros(len(periods))
            den = np.zeros(len(periods)) if metric.is_ratio else None
            volume = np.zeros(len(periods))
            for row in grouped[value]:
                i = index.get(_as_date(row["period"]))
                if i is None:
                    continue
                num[i] = float(row["num"] or 0)
                if den is not None:
                    den[i] = float(row["den"] or 0)
                volume[i] = float(row["volume"] or 0)
            if volume.sum() < segment_cfg.min_total_volume:
                continue
            if (volume >= self.config.detection.volume_floor).sum() <= self.config.detection.min_history[metric.grain]:
                continue  # can never be scored
            out.append(Series(metric, segment_type, value, periods, num, den, volume))
        return out

    # ------------------------------------------------------------------ scan
    def scan(self) -> ScanResult:
        started = time.monotonic()
        detection = self.config.detection
        limits = self.config.limits
        all_series: dict[tuple[str, str, str], Series] = {}
        candidates: list[Candidate] = []
        timed_out = False
        try:
            for metric in self.config.expanded_metrics():
                rng = self.query(self.range_sql(metric))
                if not rng or rng[0]["first_day"] is None:
                    continue
                first_day, last_day = _as_date(rng[0]["first_day"]), _as_date(rng[0]["last_day"])
                for segment_type in metric.segments:
                    for series in self.load_series(metric, segment_type, first_day, last_day):
                        self.budget.check()
                        if len(all_series) >= limits.max_series:
                            raise ScanTimeout(f"series cap of {limits.max_series} reached")
                        series.score = score_series(
                            series.values, series.volume, grain=metric.grain, config=detection
                        )
                        all_series[(metric.key, segment_type, series.segment_value)] = series
                        for episode in find_episodes(series.score, detection, limits.max_episodes_per_series):
                            volume = series.volume[episode.peak]
                            candidates.append(
                                Candidate(series, episode, abs(episode.z) * math.log(max(volume, 1.0)))
                            )
        except ScanTimeout:
            timed_out = True

        candidates.sort(key=_rank_key)
        if not timed_out:
            try:
                for candidate in candidates[: self.config.ranking.attribute_top]:
                    candidate.attribution = self.attribute_candidate(candidate)
            except ScanTimeout:
                timed_out = True
        kept = merge_parent_child(candidates)
        cards = [build_card(c, rank, self.config) for rank, c in enumerate(kept[: self.config.ranking.max_cards], 1)]
        report = ScanReport(
            generated_at=datetime.now(UTC),
            data_source="sample: DuckDB over data/sample (read-only)",
            elapsed_seconds=round(time.monotonic() - started, 2),
            timed_out=timed_out,
            queries=self.budget.queries,
            series_scanned=len(all_series),
            episodes_found=len(candidates),
            thresholds={
                "z_threshold": detection.z_threshold,
                "volume_floor": detection.volume_floor,
                "window_days": detection.windows["day"],
                "window_weeks": detection.windows["week"],
                "explains_threshold": self.config.attribution.explains_threshold,
            },
            cards=cards,
        )
        return ScanResult(report, kept, all_series)

    # ------------------------------------------------------------ attribution
    def attribute_candidate(self, candidate: Candidate) -> list[DimensionResult]:
        series = candidate.series
        metric = series.metric
        window = self.config.detection.windows[metric.grain]
        ep = candidate.episode
        base_lo = max(0, ep.start - window)
        baseline_periods = ep.start - base_lo
        if baseline_periods == 0:
            return []
        episode_periods = ep.end - ep.start + 1
        period_expr = self._period_expr(metric)
        start, end = series.periods[base_lo], series.periods[ep.end]
        extra = [f"{period_expr} >= DATE {sql_literal(start.isoformat())}",
                 f"{period_expr} <= DATE {sql_literal(end.isoformat())}"]
        own_column = self.config.segment(series.segment_type).column
        if own_column:
            extra.append(f"{own_column} = {sql_literal(series.segment_value)}")
        episode_start = series.periods[ep.start]
        den = metric.denominator or "NULL"
        cube: dict[str, dict[str, SliceValues]] = {}
        for dimension in metric.segments:
            column = self.config.segment(dimension).column
            if not column or dimension == series.segment_type:
                continue
            rows = self.query(
                f"SELECT {period_expr} AS period, {column} AS slice, {metric.numerator} AS num, {den} AS den "
                f"FROM ({self.config.fact_sql(metric.fact).strip()}) f "
                f"WHERE {self._where(metric, extra)} GROUP BY {period_expr}, {column}"
            )
            sums: dict[str, list[float]] = {}
            for row in rows:
                acc = sums.setdefault(str(row["slice"]), [0.0, 0.0, 0.0, 0.0])
                offset = 2 if _as_date(row["period"]) >= episode_start else 0
                acc[offset] += float(row["num"] or 0)
                acc[offset + 1] += float(row["den"] or 0)
            scale = episode_periods / baseline_periods
            cube[dimension] = {
                key: SliceValues(
                    forecast=v[0] * scale,
                    actual=v[2],
                    forecast_den=v[1] * scale if metric.is_ratio else None,
                    actual_den=v[3] if metric.is_ratio else None,
                )
                for key, v in sums.items()
            }
        cfg = self.config.attribution
        return attribute(
            cube,
            ratio=metric.is_ratio,
            explains_threshold=cfg.explains_threshold,
            slice_threshold=cfg.slice_threshold,
            top_dimensions=cfg.top_dimensions,
        )


def _query_timeout() -> float:
    return float(get_settings().query_timeout_seconds)


def _rank_key(c: Candidate) -> tuple:
    s = c.series
    return (-c.score, s.metric.key, s.segment_type, s.segment_value, c.episode.start)


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _complete_periods(rows: list[dict], first_day: date, last_day: date, step: int) -> list[date]:
    """Every period between the first and last complete one (partial edge weeks dropped)."""
    starts = sorted({_as_date(r["period"]) for r in rows})
    starts = [p for p in starts if p >= first_day and p + timedelta(days=step - 1) <= last_day]
    if not starts:
        return []
    out = []
    current = starts[0]
    while current <= starts[-1] and len(out) < 100_000:
        out.append(current)
        current += timedelta(days=step)
    return out


def _overlaps(a: Candidate, b: Candidate) -> bool:
    return a.start <= b.end and b.start <= a.end


def merge_parent_child(candidates: list[Candidate]) -> list[Candidate]:
    """Fold flagged children into their whole-shop parent when the parent's attribution names them.

    A child is folded when it is the same metric, moves in the same direction over an overlapping
    period, and its slice is in the explaining set of one of the parent's attributed dimensions.
    The parent keeps the larger of the scores so the merged card ranks where the stronger of the
    moves would have ranked.
    """
    absorbed: set[int] = set()
    for parent in candidates:
        if id(parent) in absorbed or parent.series.segment_type != WHOLE_SHOP or not parent.attribution:
            continue
        named = {(d.dimension, s.value) for d in parent.attribution for s in d.slices}
        for child in candidates:
            if child is parent or id(child) in absorbed:
                continue
            cs = child.series
            if (
                cs.metric.key == parent.series.metric.key
                and (cs.segment_type, cs.segment_value) in named
                and child.episode.direction == parent.episode.direction
                and _overlaps(parent, child)
            ):
                absorbed.add(id(child))
                parent.merged.append(child)
                parent.score = max(parent.score, child.score)
    kept = [c for c in candidates if id(c) not in absorbed]
    kept.sort(key=_rank_key)
    return kept


# ------------------------------------------------------------------ cards
def segment_label(config: ScannerConfig, segment_type: str, value: str) -> str:
    if segment_type == WHOLE_SHOP:
        return "whole shop"
    return f"{config.segment(segment_type).label} {value}"


def _episode_values(candidate: Candidate) -> tuple[float, float]:
    s = candidate.series
    score = s.score
    assert score is not None
    idx = [i for i in range(candidate.episode.start, candidate.episode.end + 1) if np.isfinite(score.expected[i])]
    if s.den is None:
        observed = float(np.mean(s.values[idx]))
        baseline = float(np.mean(score.expected[idx]))
    else:
        weights = s.den[idx]
        observed = float(s.num[idx].sum() / weights.sum())
        baseline = float(np.average(score.expected[idx], weights=weights))
    return baseline, observed


def _period_phrase(candidate: Candidate) -> str:
    grain = candidate.series.metric.grain
    start, end = candidate.start, candidate.end
    if grain == "day":
        return f"on {start.isoformat()}" if start == end else f"between {start.isoformat()} and {end.isoformat()}"
    if candidate.episode.start == candidate.episode.end:
        return f"in the week of {start.isoformat()}"
    return f"between {start.isoformat()} and {end.isoformat()}"


def attribution_text(config: ScannerConfig, attribution: list[DimensionResult] | None) -> str | None:
    if not attribution:
        return None
    top = attribution[0]
    label = config.segment(top.dimension).label
    if len(top.slices) == 1:
        s = top.slices[0]
        return f"driven by {label} {s.value}: {s.explanatory_power:.0%} of the change"
    parts = ", ".join(f"{s.value} {s.explanatory_power:.0%}" for s in top.slices)
    return f"driven by {label} {parts} ({top.explained:.0%} of the change)"


def build_card(candidate: Candidate, rank: int, config: ScannerConfig) -> AnomalyCard:
    s = candidate.series
    ep = candidate.episode
    baseline, observed = _episode_values(candidate)
    change = observed - baseline
    direction = "rise" if ep.direction > 0 else "fall"
    seg_label = segment_label(config, s.segment_type, s.segment_value)
    where = "across the whole shop" if s.segment_type == WHOLE_SHOP else f"for {seg_label}"
    question = f"Why did {s.metric.label} {where} {direction} {_period_phrase(candidate)}?"
    attribution = [
        DimensionAttribution(
            dimension=d.dimension,
            explained=round(d.explained, 4),
            surprise=round(d.surprise, 6),
            slices=[
                SliceAttribution(
                    value=x.value,
                    explanatory_power=round(x.explanatory_power, 4),
                    surprise=round(x.surprise, 6),
                    baseline=round(x.forecast, 4),
                    observed=round(x.actual, 4),
                )
                for x in d.slices
            ],
        )
        for d in (candidate.attribution or [])
    ]
    return AnomalyCard(
        id=f"{s.metric.key}|{s.segment_type}|{s.segment_value}|{candidate.start.isoformat()}",
        rank=rank,
        metric=s.metric.key,
        metric_label=s.metric.label,
        segment=Segment(type=s.segment_type, value=s.segment_value, label=seg_label),
        period=Period(start=candidate.start, end=candidate.end, grain=s.metric.grain, periods=ep.end - ep.start + 1),
        baseline=round(baseline, 4),
        observed=round(observed, 4),
        change=round(change, 4),
        change_pct=round(change / baseline, 4) if baseline else None,
        direction=direction,
        z_score=round(ep.z, 2),
        volume=int(s.volume[ep.peak]),
        score=round(candidate.score, 3),
        method=str(s.score.methods[ep.peak]) if s.score else "",
        top_attribution=attribution_text(config, candidate.attribution),
        attribution=attribution,
        merged=[
            f"{segment_label(config, c.series.segment_type, c.series.segment_value)} "
            f"(z {c.episode.z:.1f}, {c.start.isoformat()}..{c.end.isoformat()})"
            for c in candidate.merged
        ],
        question=question,
    )


def scan(config: ScannerConfig | None = None, run_sql: RunSql | None = None, timeout_s: float | None = None) -> ScanResult:
    return Scanner(config=config, run_sql=run_sql, timeout_s=timeout_s).scan()

"""Unit tests for the plan-check helpers in eval/scanner_check.py (no scan is run here)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.scanner.models import (
    AnomalyCard,
    DimensionAttribution,
    Period,
    Segment,
    SliceAttribution,
)

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("scanner_check", ROOT / "eval" / "scanner_check.py")
check = importlib.util.module_from_spec(_spec)
sys.modules["scanner_check"] = check  # dataclasses look the module up
_spec.loader.exec_module(check)


def _card(metric: str, seg_type: str, value: str, start: date, end: date, grain: str = "week",
          top: tuple[str, str] | None = None) -> AnomalyCard:
    attribution = []
    if top:
        attribution = [DimensionAttribution(dimension=top[0], explained=0.8, surprise=0.1, slices=[
            SliceAttribution(value=top[1], explanatory_power=0.8, surprise=0.1, baseline=1.0, observed=2.0)])]
    return AnomalyCard(
        id="x", rank=1, metric=metric, metric_label=metric, segment=Segment(type=seg_type, value=value, label=value),
        period=Period(start=start, end=end, grain=grain, periods=1), baseline=1.0, observed=2.0, change=1.0,
        change_pct=1.0, direction="rise", z_score=5.0, volume=100, score=1.0, method="trailing_median",
        top_attribution=None, attribution=attribution, question="Why did x rise?",
    )


def test_answer_key_targets_map_to_scanner_segments() -> None:
    targets = {t.id: t for t in check.load_targets()}
    assert len(targets) == 10
    assert (targets["incident-04"].segment_type, targets["incident-04"].segment_value) == ("state", "RJ")
    assert targets["incident-06"].segment_type == "category"
    assert targets["incident-07"].segment_value == "paid_search"
    assert targets["incident-01"].segment_value == "all"
    assert sum(t.determinable for t in targets.values()) == 8


def test_card_matches_by_own_segment_or_attribution_and_window() -> None:
    t04 = {t.id: t for t in check.load_targets()}["incident-04"]
    own = _card("avg_freight", "state", "RJ", date(2018, 8, 6), date(2018, 8, 12))
    via_parent = _card("avg_freight", "all", "all", date(2018, 8, 6), date(2018, 8, 12), top=("state", "RJ"))
    wrong_window = _card("avg_freight", "state", "RJ", date(2018, 6, 4), date(2018, 6, 10))
    wrong_metric = _card("revenue", "state", "RJ", date(2018, 8, 6), date(2018, 8, 12))
    assert check.full_hit(own, t04) and check.full_hit(via_parent, t04)
    assert not check.segment_hit(wrong_window, t04)
    assert check.segment_hit(wrong_metric, t04) and not check.full_hit(wrong_metric, t04)


def test_weekly_cycle_only_detects_a_normal_weekday() -> None:
    start = date(2018, 1, 1)
    periods = [start + timedelta(days=i) for i in range(42)]
    values = np.array([100.0 if p.weekday() < 5 else 40.0 for p in periods])
    values[40] = 400.0
    series = SimpleNamespace(periods=periods, values=values)
    result = SimpleNamespace(series={("daily_orders", "all", "all"): series})
    sunday = next(p for p in periods[30:] if p.weekday() == 6)
    normal = _card("daily_orders", "all", "all", sunday, sunday, grain="day")
    spike = _card("daily_orders", "all", "all", periods[40], periods[40], grain="day")
    assert check.weekly_cycle_only(normal, result)
    assert not check.weekly_cycle_only(spike, result)

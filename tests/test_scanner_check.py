"""Unit tests for the plan-check helpers in eval/scanner_check.py (no scan is run here)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

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


def _cand(metric: str, seg_type: str, value: str, start: date, end: date, z: float = 5.0, merged=()):
    series = SimpleNamespace(metric=SimpleNamespace(key=metric), segment_type=seg_type, segment_value=value)
    return SimpleNamespace(series=series, start=start, end=end, episode=SimpleNamespace(z=z), merged=list(merged))


def _result(candidates: list, cards: list[AnomalyCard] | None = None, timed_out: bool = False):
    report = SimpleNamespace(cards=cards or [], timed_out=timed_out)
    return SimpleNamespace(report=report, candidates=candidates, series={})


JAN = (date(2018, 1, 15), date(2018, 1, 21))


def test_placement_gives_overall_rank_and_rank_within_the_metric() -> None:
    t06 = {t.id: t for t in check.load_targets()}["incident-06"]
    candidates = [
        _cand("late_delivery_rate", "state", "MG", *JAN),
        _cand("avg_review_score", "all", "all", *JAN),
        _cand("payment_share:boleto", "state", "SP", *JAN),
        _cand("avg_review_score", "category", "relogios_presentes", date(2018, 6, 4), date(2018, 6, 10)),
        _cand("avg_review_score", "category", "relogios_presentes", *JAN, z=-8.4),
    ]
    p = check.place(_result(candidates), t06)
    assert (p.overall_rank, p.metric_rank) == (5, 3)
    assert p.candidate is candidates[4]
    # A child merged into a parent counts at the parent's rank.
    child = _cand("avg_review_score", "category", "relogios_presentes", *JAN)
    parent = _cand("avg_review_score", "all", "all", *JAN, merged=[child])
    p = check.place(_result([candidates[0], parent]), t06)
    assert (p.overall_rank, p.metric_rank, p.candidate) == (2, 1, child)
    # Wrong metric on the right segment and window is not a placement.
    assert check.place(_result([_cand("revenue", "category", "relogios_presentes", *JAN)]), t06) is None


def test_check_passes_with_one_planted_incident_flagged_outside_the_top_ten() -> None:
    targets = check.load_targets()
    top = _card("late_delivery_rate", "state", "MG", date(2017, 12, 18), date(2017, 12, 24))
    flagged = [_cand("late_delivery_rate", "state", "MG", date(2017, 12, 18), date(2017, 12, 24))] * 36 + [
        _cand("avg_review_score", "category", "relogios_presentes", *JAN)]
    outcome = check.evaluate(_result(flagged, [top]), targets)
    assert outcome.recall == 1 and outcome.determinable == 8
    assert outcome.placements["incident-06"].overall_rank == 37
    assert outcome.placements["incident-04"] is None
    # The previous top-ten rule still reports its failures; they no longer decide the result.
    assert not outcome.old_a and not outcome.old_b
    assert outcome.top_ten_recall_metric == 0
    assert outcome.passed


def test_check_fails_with_no_planted_incident_flagged_a_weekly_cycle_card_or_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = check.load_targets()
    unrelated = [_cand("late_delivery_rate", "state", "MG", date(2017, 12, 18), date(2017, 12, 24))]
    assert not check.evaluate(_result(unrelated), targets).passed

    hit = [_cand("avg_review_score", "category", "relogios_presentes", *JAN)]
    assert not check.evaluate(_result(hit, timed_out=True), targets).passed

    card = _card("daily_orders", "state", "SP", date(2018, 5, 20), date(2018, 5, 20), grain="day")
    monkeypatch.setattr(check, "weekly_cycle_only", lambda c, r: True)
    outcome = check.evaluate(_result(hit, [card]), targets)
    assert outcome.cycle_cards == [card.id] and not outcome.passed


def test_old_top_ten_rule_is_still_computed() -> None:
    targets = check.load_targets()
    cards = [
        _card("avg_review_score", "category", "relogios_presentes", *JAN),
        _card("avg_freight", "all", "all", date(2018, 8, 6), date(2018, 8, 12), top=("state", "RJ")),
    ]
    outcome = check.evaluate(_result([], cards), targets)
    assert outcome.old_a and outcome.old_b
    assert outcome.top_ten_recall_metric == 2
    assert outcome.recall == 0 and not outcome.passed

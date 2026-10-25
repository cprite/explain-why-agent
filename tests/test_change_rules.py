"""Unit tests for app/change_rules.py (Sprint 11c): the spread guard for shares, the relative rule
without a spread, and the fall-in-records test behind the Critic's sample-size rule."""

from __future__ import annotations

import math

import pytest

from app.change_rules import (
    is_share,
    number,
    records_fell,
    relative_change,
    relative_floor,
    share_standard_error,
    trusted_spread,
)


def test_number_accepts_real_numbers_only() -> None:
    assert number(3) == 3.0 and number(0.5) == 0.5
    assert number(True) is None and number("1") is None and number(None) is None
    assert number(float("nan")) is None and number(float("inf")) is None


def test_relative_rule_is_a_tenth_of_the_threshold() -> None:
    assert relative_floor(2.0) == pytest.approx(0.2)
    assert relative_change(142.7, 109.7) == pytest.approx(0.3008, abs=1e-4)
    assert relative_change(1.0, 0) is None and relative_change(None, 1.0) is None


def test_is_share() -> None:
    assert is_share(0.132, 0.0301) and is_share(0, 1)
    assert not is_share(142.7, 109.7) and not is_share(0.5, 1.2) and not is_share(None, 0.1)


def test_the_per_record_spread_of_a_share_is_rejected() -> None:
    """The real incident-02 numbers: 0.1699 is about sqrt(0.0301 x 0.9699) = 0.171, the standard deviation
    of a per-delivery 0/1 flag, not of the weekly share."""
    assert math.sqrt(0.0301 * 0.9699) == pytest.approx(0.1699, abs=2e-3)
    spread, notes = trusted_spread(0.132, 0.0301, 0.1699, None)
    assert spread is None and notes == {"spread_rejected": 0.1699, "spread_basis": "not_measured"}
    spread, notes = trusted_spread(0.132, 0.0301, 0.1699, 606)
    assert spread == pytest.approx(math.sqrt(0.0301 * 0.9699 / 606), abs=1e-6)
    assert notes["spread_basis"] == "standard_error"


def test_a_period_level_spread_is_kept() -> None:
    assert trusted_spread(0.1007, 0.0149, 0.0067, 606) == (0.0067, {})  # a share, spread below the baseline
    assert trusted_spread(111, 106.857, 17.677, 111) == (17.677, {})  # a count: no guard
    assert trusted_spread(0.2, 0.1, None, 50) == (None, {})
    assert trusted_spread(0.2, 0.1, 0, 50) == (None, {})


def test_share_standard_error_is_undefined_at_the_edges() -> None:
    assert share_standard_error(0.0, 100) is None and share_standard_error(1.0, 100) is None
    assert share_standard_error(0.5, 0) is None
    assert share_standard_error(0.5, 100) == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # incident-03 style: revenue dropped to zero; no baseline count needed.
        ({"n": 13, "n_baseline": None, "observed": 0.0, "baseline": 1520.5}, True),
        # the measure fell and records per day fell by more than 20 %: 13/14 a day against 96/28.
        ({"n": 13, "n_baseline": 96, "observed": 300.0, "baseline": 1520.5}, True),
        # incident-09 style: 3 records in 15 days against 5 in 30 - records per day did not fall.
        ({"n": 3, "n_baseline": 5, "observed": 1.67, "baseline": 3.0, "window_days": 15, "baseline_days": 30}, False),
        # the measure rose: never a fall, even with fewer records per day (the lateness week).
        ({"n": 606, "n_baseline": 5963, "observed": 0.1007, "baseline": 0.0149}, False),
        # records fell by less than 20 % a day.
        ({"n": 12, "n_baseline": 26, "observed": 10.0, "baseline": 12.0}, False),
        # nothing to tell from.
        ({"n": None, "n_baseline": None, "observed": None, "baseline": None}, None),
    ],
)
def test_records_fell(kwargs: dict, expected: bool | None) -> None:
    days = {"window_days": kwargs.pop("window_days", 14), "baseline_days": kwargs.pop("baseline_days", 28)}
    assert records_fell(kwargs["n"], kwargs["n_baseline"], days["window_days"], days["baseline_days"], threshold=2.0,
                        observed=kwargs["observed"], baseline=kwargs["baseline"]) is expected

"""Pure rules for reading the change check (architecture §4): is the spread trustworthy, is the change
large without one, and did the records behind the measure fall. Used by the orchestrator's change
branch and by the Critic's sample-size rule; no I/O.

- A share (observed and baseline both in [0, 1]) whose spread is larger than its baseline is not the
  variation of the share across baseline periods: it is the standard deviation of the per-record 0/1
  indicator, sqrt(p(1-p)). It is replaced by the standard error of the share, sqrt(p(1-p)/n), when the
  number of records `n` in the window is known, and otherwise treated as not measured.
- Without a trusted spread, a change larger than `CHANGE_VARIATION_THRESHOLD` x 10 % of the baseline
  (20 % at the default threshold) is never read as "no significant change".
- The change is a fall in records when the measure fell and the window holds fewer records per day
  than the baseline by more than the same relative amount, or when the measure dropped to zero from a
  positive baseline.
"""

from __future__ import annotations

import math
from typing import Any

RELATIVE_PER_THRESHOLD = 0.10
"""Relative change per unit of `CHANGE_VARIATION_THRESHOLD`: 2.0 -> 20 % of the baseline."""


def number(value: Any) -> float | None:
    """`value` as a float when it is a real number (not a bool, not NaN), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return None if math.isnan(value) or math.isinf(value) else value


def relative_floor(threshold: float) -> float:
    """The relative change that counts as large when no spread is trusted."""
    return threshold * RELATIVE_PER_THRESHOLD


def relative_change(observed: Any, baseline: Any) -> float | None:
    """|observed - baseline| / |baseline|; None without both numbers or with a zero baseline."""
    obs, base = number(observed), number(baseline)
    if obs is None or base is None or base == 0:
        return None
    return abs(obs - base) / abs(base)


def is_share(observed: Any, baseline: Any) -> bool:
    """True when both values lie in [0, 1], as a share or rate does."""
    obs, base = number(observed), number(baseline)
    return obs is not None and base is not None and 0.0 <= obs <= 1.0 and 0.0 <= base <= 1.0


def share_standard_error(p: float, n: float) -> float | None:
    """sqrt(p(1-p)/n), the standard error of a share p over n records; None when it is not defined."""
    if n <= 0 or not 0.0 < p < 1.0:
        return None
    return math.sqrt(p * (1.0 - p) / n)


def trusted_spread(observed: Any, baseline: Any, spread: Any, n: Any) -> tuple[float | None, dict[str, Any]]:
    """The spread to compare the change with, and the numbers explaining the choice.

    Returns (spread, notes). `notes` holds `spread_rejected` (the reported spread) and `spread_basis`
    (`standard_error` or `not_measured`) when a share's spread was larger than its baseline.
    """
    value = number(spread)
    if value is None or value <= 0:
        return None, {}
    base = number(baseline)
    if not (is_share(observed, baseline) and base is not None and value > base):
        return value, {}
    notes: dict[str, Any] = {"spread_rejected": value}
    records = number(n)
    error = share_standard_error(base, records) if records is not None else None
    if error is None:
        notes["spread_basis"] = "not_measured"
        return None, notes
    notes["spread_basis"] = "standard_error"
    return round(error, 6), notes


def records_fell(
    n: Any, n_baseline: Any, window_days: int, baseline_days: int, *, threshold: float,
    observed: Any = None, baseline: Any = None,
) -> bool | None:
    """Is the change a fall in the records behind the measure? None when it cannot be told.

    The measure dropped to zero from a positive baseline (a revenue or count that vanished): yes.
    Otherwise, with both counts: the measure fell and the window's records per day are below the
    baseline's by more than `relative_floor(threshold)`. A measure that rose is never a fall.
    """
    obs, ref = number(observed), number(baseline)
    if obs is not None and ref is not None:
        if ref > 0 and obs <= 0:
            return True
        if obs >= ref:
            return False
    window, base = number(n), number(n_baseline)
    if window is not None and base is not None and window_days > 0 and baseline_days > 0 and base > 0:
        per_day, base_per_day = window / window_days, base / baseline_days
        return per_day < base_per_day * (1.0 - relative_floor(threshold))
    return None

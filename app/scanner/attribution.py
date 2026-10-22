"""Adtributor-style attribution of a metric change to the slices behind it.

Method: R. Bhagwan, R. Kumar, R. Ramjee, G. Varghese, S. Mohapatra, H. Manoharan, P. Shah,
"Adtributor: Revenue Debugging in Advertising Systems", NSDI 2014
(https://www.usenix.org/conference/nsdi14/technical-sessions/presentation/bhagwan).

For every slice j of a dimension, with forecast F and actual A:

- explanatory power  EP_j = (A_j - F_j) / (A - F)   (sums to 1 over a dimension's slices);
- surprise           S_j  = JS(p_j, q_j), p_j = F_j / F, q_j = A_j / A (Jensen-Shannon term).

A ratio metric m = N / D is attributed through its numerator and denominator (the paper's derived
measures): EP_j = ((A_N,j - F_N,j) * F_D - (A_D,j - F_D,j) * F_N) / (F_D * A_D * (A_m - F_m)),
which again sums to 1, and S_j = S_j(N) + S_j(D).

Per dimension the smallest set of slices whose explanatory power reaches the threshold (67%) is
kept, each slice explaining at least 10%, and the set is listed by surprise; dimensions are ranked
by the total surprise of their set. Dimensions where no such set exists are dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

MAX_SLICES_PER_DIMENSION = 5000


@dataclass(frozen=True)
class SliceValues:
    """Forecast and actual for one slice. For additive metrics leave the denominators at None."""

    forecast: float
    actual: float
    forecast_den: float | None = None
    actual_den: float | None = None


@dataclass
class SliceResult:
    value: str
    explanatory_power: float
    surprise: float
    forecast: float
    actual: float


@dataclass
class DimensionResult:
    dimension: str
    slices: list[SliceResult]  # the explaining set, by surprise
    explained: float  # summed EP of the set
    surprise: float  # summed surprise of the set
    explanatory_powers: dict[str, float] = field(default_factory=dict)  # every slice


def _js_term(p: float, q: float) -> float:
    """Per-element Jensen-Shannon divergence between expected share p and actual share q."""
    m = (p + q) / 2
    total = 0.0
    if p > 0:
        total += 0.5 * p * math.log(p / m)
    if q > 0:
        total += 0.5 * q * math.log(q / m)
    return total


def _share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def _dimension_scores(slices: dict[str, SliceValues], ratio: bool) -> dict[str, tuple[float, float]] | None:
    """EP and surprise per slice, or None when the dimension shows no change to explain."""
    f_num = sum(s.forecast for s in slices.values())
    a_num = sum(s.actual for s in slices.values())
    scores: dict[str, tuple[float, float]] = {}
    if not ratio:
        change = a_num - f_num
        if change == 0:
            return None
        for key, s in slices.items():
            ep = (s.actual - s.forecast) / change
            surprise = _js_term(_share(s.forecast, f_num), _share(s.actual, a_num))
            scores[key] = (ep, surprise)
        return scores

    f_den = sum(s.forecast_den or 0.0 for s in slices.values())
    a_den = sum(s.actual_den or 0.0 for s in slices.values())
    if f_den == 0 or a_den == 0:
        return None
    change = _ratio(a_num, a_den) - _ratio(f_num, f_den)
    if change == 0:
        return None
    norm = f_den * a_den * change
    for key, s in slices.items():
        fd, ad = s.forecast_den or 0.0, s.actual_den or 0.0
        ep = ((s.actual - s.forecast) * f_den - (ad - fd) * f_num) / norm
        surprise = _js_term(_share(s.forecast, f_num), _share(s.actual, a_num)) + _js_term(
            _share(fd, f_den), _share(ad, a_den)
        )
        scores[key] = (ep, surprise)
    return scores


def attribute(
    cube: dict[str, dict[str, SliceValues]],
    *,
    ratio: bool = False,
    explains_threshold: float = 0.67,
    slice_threshold: float = 0.10,
    top_dimensions: int = 3,
) -> list[DimensionResult]:
    """Rank dimensions and slices that explain the change from forecast to actual.

    `cube` maps dimension -> slice value -> SliceValues. Every dimension must partition the same
    total (each row belongs to exactly one slice per dimension).
    """
    results: list[DimensionResult] = []
    for dimension, slices in cube.items():
        if len(slices) > MAX_SLICES_PER_DIMENSION:
            slices = dict(
                sorted(slices.items(), key=lambda kv: -abs(kv[1].actual - kv[1].forecast))[
                    :MAX_SLICES_PER_DIMENSION
                ]
            )
        scores = _dimension_scores(slices, ratio)
        if not scores:
            continue
        chosen: list[str] = []
        explained = 0.0
        for key in sorted(scores, key=lambda k: (-scores[k][0], k)):
            ep = scores[key][0]
            if ep < slice_threshold:
                break
            chosen.append(key)
            explained += ep
            if explained >= explains_threshold:
                break
        if explained < explains_threshold:
            continue
        chosen.sort(key=lambda k: (-scores[k][1], k))
        results.append(
            DimensionResult(
                dimension=dimension,
                slices=[
                    SliceResult(
                        value=k,
                        explanatory_power=scores[k][0],
                        surprise=scores[k][1],
                        forecast=_slice_value(slices[k], ratio, forecast=True),
                        actual=_slice_value(slices[k], ratio, forecast=False),
                    )
                    for k in chosen
                ],
                explained=explained,
                surprise=sum(scores[k][1] for k in chosen),
                explanatory_powers={k: v[0] for k, v in scores.items()},
            )
        )
    results.sort(key=lambda r: (-r.surprise, r.dimension))
    return results[:top_dimensions]


def _slice_value(s: SliceValues, ratio: bool, *, forecast: bool) -> float:
    if not ratio:
        return s.forecast if forecast else s.actual
    if forecast:
        return _ratio(s.forecast, s.forecast_den or 0.0)
    return _ratio(s.actual, s.actual_den or 0.0)

"""Flag unusual periods in one metric series (docs/architecture.md §6a, step 3).

Daily series are decomposed with robust STL (period 7) and the weekly cycle is removed, on each
unbroken stretch of periods above the volume floor that spans at least three cycles; shorter
stretches fall back to the raw values (the plain trailing-median test). Weekly series have no cycle
to remove at this data length (an annual cycle would need three years). What is left is scored
with a robust z-score against a strictly trailing window (28 days / 8 weeks):

    z_t = (x_t - median(x_window)) / (1.4826 * MAD(x_window))

The trailing median plays the part of the local trend: a centred trend fit would absorb a sustained
move, while the trailing window only looks backwards. Periods backed by fewer orders than the volume
floor are neither scored nor used as baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from statsmodels.tsa.seasonal import STL

from app.scanner.settings import DetectionConfig

MAD_SCALE = 1.4826
MEAN_AD_SCALE = 1.2533  # used when the MAD is zero (more than half the window identical)

METHOD_STL = "stl"
METHOD_TRAILING_MEDIAN = "trailing_median"


@dataclass
class SeriesScore:
    values: np.ndarray
    volumes: np.ndarray
    expected: np.ndarray  # baseline in the metric's own units (NaN where not scored)
    z: np.ndarray  # robust z (NaN where not scored)
    flagged: np.ndarray  # bool
    methods: np.ndarray  # per period: "stl" or "trailing_median"
    seasonal: np.ndarray = field(repr=False)

    @property
    def method(self) -> str:
        """"stl" when any period was deseasonalised, else "trailing_median"."""
        return METHOD_STL if (self.methods == METHOD_STL).any() else METHOD_TRAILING_MEDIAN


@dataclass
class Episode:
    start: int  # index of the first flagged period
    end: int  # index of the last flagged period (inclusive)
    peak: int  # index with the largest |z|
    z: float  # z at the peak, capped
    direction: int  # +1 rise, -1 fall


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs of True as (start, stop) index pairs, stop exclusive."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def score_series(
    values: np.ndarray | list[float],
    volumes: np.ndarray | list[float],
    *,
    grain: str,
    config: DetectionConfig,
) -> SeriesScore:
    values = np.asarray(values, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    n = len(values)
    valid = np.isfinite(values) & (volumes >= config.volume_floor)
    seasonal = np.zeros(n)
    methods = np.full(n, METHOD_TRAILING_MEDIAN, dtype=object)

    # STL runs on each unbroken stretch of periods above the volume floor that spans at least
    # `min_cycles` cycles; shorter stretches keep the raw values (plain trailing-median test).
    period = config.cycle.get(grain)
    if period:
        for start, stop in _runs(valid):
            if stop - start >= config.min_cycles * period:
                fit = STL(values[start:stop], period=period, seasonal=config.stl_seasonal, robust=True).fit()
                seasonal[start:stop] = np.asarray(fit.seasonal)
                methods[start:stop] = METHOD_STL

    adjusted = values - seasonal
    window = config.windows[grain]
    min_history = config.min_history[grain]
    expected = np.full(n, np.nan)
    z = np.full(n, np.nan)
    valid_idx = np.flatnonzero(valid)

    for t in valid_idx:
        lo = np.searchsorted(valid_idx, t - window)
        hi = np.searchsorted(valid_idx, t)
        base = adjusted[valid_idx[lo:hi]]
        if len(base) < min_history:
            continue
        median = float(np.median(base))
        deviations = np.abs(base - median)
        scale = MAD_SCALE * float(np.median(deviations))
        if scale <= 0:
            scale = MEAN_AD_SCALE * float(np.mean(deviations))
        diff = adjusted[t] - median
        if scale > 0:
            z[t] = diff / scale
        else:
            z[t] = 0.0 if diff == 0 else np.sign(diff) * np.inf
        expected[t] = median + seasonal[t]

    with np.errstate(invalid="ignore"):
        flagged = np.abs(z) >= config.z_threshold  # NaN (not scored) compares False
    return SeriesScore(values, volumes, expected, z, flagged, methods, seasonal)


def find_episodes(score: SeriesScore, config: DetectionConfig, max_episodes: int) -> list[Episode]:
    """Group flagged periods of the same direction into episodes (gaps up to `merge_gap`)."""
    episodes: list[Episode] = []
    current: list[int] = []
    current_sign = 0
    for t in np.flatnonzero(score.flagged):
        sign = 1 if score.z[t] > 0 else -1
        if current and sign == current_sign and t - current[-1] <= config.merge_gap + 1:
            current.append(int(t))
            continue
        if current:
            episodes.append(_episode(current, current_sign, score, config))
            if len(episodes) >= max_episodes:
                return episodes
        current, current_sign = [int(t)], sign
    if current and len(episodes) < max_episodes:
        episodes.append(_episode(current, current_sign, score, config))
    return episodes


def _episode(indices: list[int], sign: int, score: SeriesScore, config: DetectionConfig) -> Episode:
    peak = max(indices, key=lambda i: abs(score.z[i]))
    z = float(np.clip(score.z[peak], -config.z_cap, config.z_cap))
    return Episode(start=indices[0], end=indices[-1], peak=peak, z=z, direction=sign)

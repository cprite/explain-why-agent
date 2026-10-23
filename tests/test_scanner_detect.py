"""Detector tests on synthetic series (acceptance criterion 2)."""

from __future__ import annotations

import numpy as np
import pytest

from app.scanner.detect import (
    METHOD_STL,
    METHOD_TRAILING_MEDIAN,
    find_episodes,
    score_series,
)
from app.scanner.settings import load_config

DETECTION = load_config().detection
VOLUME = 200.0
WEEK = np.array([1.0, 1.0, 1.0, 1.05, 1.1, 0.8, 0.7])


def _daily(n: int, level: float = 200.0, noise: float = 6.0, seed: int = 0, weekly: bool = True) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cycle = np.tile(WEEK, n // 7 + 1)[:n] if weekly else np.ones(n)
    return level * cycle + rng.normal(0.0, noise, n)


def _episodes(values: np.ndarray, volumes: np.ndarray | float = VOLUME, grain: str = "day"):
    vols = np.broadcast_to(np.asarray(volumes, dtype=float), values.shape)
    score = score_series(values, vols, grain=grain, config=DETECTION)
    return score, find_episodes(score, DETECTION, max_episodes=50)


def test_thresholds_are_the_fixed_plan_values() -> None:
    assert DETECTION.z_threshold == 3.5
    assert DETECTION.volume_floor == 30
    assert DETECTION.windows == {"day": 28, "week": 12}
    assert DETECTION.mad_floor == 0.01
    assert DETECTION.cycle == {"day": 7}
    assert DETECTION.min_cycles == 3


def test_one_day_spike_is_flagged() -> None:
    values = _daily(140)
    values[100] += 120.0
    score, episodes = _episodes(values)
    assert score.method == METHOD_STL
    assert len(episodes) == 1
    assert episodes[0].start == episodes[0].end == 100
    assert episodes[0].direction == 1
    assert episodes[0].z >= DETECTION.z_threshold


def test_step_change_is_flagged_once_as_one_episode() -> None:
    values = _daily(168)
    values[84:] += 80.0
    _, episodes = _episodes(values)
    assert len(episodes) == 1
    assert episodes[0].start == 84
    assert episodes[0].direction == 1


def test_pure_noise_is_not_flagged() -> None:
    values = _daily(120, weekly=False, seed=0)
    _, episodes = _episodes(values)
    assert episodes == []


def test_pure_noise_false_flag_rate_is_bounded() -> None:
    """A MAD from 28 points is itself noisy, so |z| >= 3.5 is crossed more often than under a
    normal distribution (measured ~0.6% of periods without STL). Guard against regressions."""
    flagged = scored = 0
    for seed in range(30):
        values = _daily(120, weekly=False, seed=seed)
        score = score_series(values, np.full(120, VOLUME), grain="day", config=DETECTION)
        flagged += int(score.flagged.sum())
        scored += int(np.isfinite(score.z).sum())
    assert flagged / scored < 0.012


def test_low_volume_segment_is_skipped() -> None:
    values = _daily(140, level=10.0, noise=1.0)
    values[100] += 40.0  # a 5x spike, but only 10 orders a day
    score, episodes = _episodes(values, volumes=values.clip(min=0))
    assert episodes == []
    assert np.isnan(score.z).all()


def test_strong_weekly_cycle_is_not_flagged() -> None:
    # Sundays at 30% of a normal day: without the STL step every Sunday is an outlier.
    cycle = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.3])
    rng = np.random.default_rng(2)
    values = 200.0 * np.tile(cycle, 20) + rng.normal(0.0, 4.0, 140)
    score, episodes = _episodes(values)
    assert score.method == METHOD_STL
    assert episodes == []

    # Control: the same series without seasonal adjustment (grain with no cycle) is flagged.
    _, raw_episodes = _episodes(values, grain="week")
    assert raw_episodes, "the control should flag the Sundays, otherwise this test proves nothing"


def test_short_series_uses_trailing_median_fallback() -> None:
    values = _daily(15, weekly=False)  # fewer than three weekly cycles
    values[14] += 150.0
    score, episodes = _episodes(values)
    assert score.method == METHOD_TRAILING_MEDIAN
    assert (score.methods == METHOD_TRAILING_MEDIAN).all()
    assert (score.seasonal == 0).all()
    assert [(e.start, e.end) for e in episodes] == [(14, 14)]


def test_stl_runs_per_stretch_above_the_volume_floor() -> None:
    # 60 good days, 10 near-empty days, then an 8-day dense block: only the first stretch is
    # long enough for STL; the block uses the fallback and its jump is scored on raw values
    # against the valid days still inside its trailing 28-day window.
    values = np.concatenate([_daily(60), np.full(10, 2.0), _daily(8, level=600.0, seed=3)])
    score, episodes = _episodes(values, volumes=values.clip(min=0))
    assert (score.methods[:60] == METHOD_STL).all()
    assert (score.methods[60:] == METHOD_TRAILING_MEDIAN).all()
    assert np.isnan(score.z[60:70]).all()
    assert episodes[-1].start == 70 and episodes[-1].direction == 1


def test_episode_count_is_capped() -> None:
    values = _daily(200, weekly=False)
    values[40::10] += 200.0  # 16 separate spikes
    score = score_series(values, np.full(200, VOLUME), grain="day", config=DETECTION)
    assert len(find_episodes(score, DETECTION, max_episodes=3)) == 3


def test_mad_floor_keeps_a_near_constant_series_from_exploding() -> None:
    # Every trailing value is identical, so the MAD (and mean deviation) is zero: without the floor
    # a 2% dip would get an infinite z. With the floor the spread is 1% of the level.
    values = np.full(40, 5.0)
    values[30] = 4.9
    score, episodes = _episodes(values, grain="week")
    assert episodes == []
    assert score.z[30] == pytest.approx(-2.0)
    values[30] = 4.0  # a 20% fall is still flagged
    _, episodes = _episodes(values, grain="week")
    assert len(episodes) == 1 and episodes[0].direction == -1

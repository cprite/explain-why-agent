"""The anomaly board behind `GET /anomalies` and `POST /run {"anomaly_id"}` (architecture §6a, §7).

The scan runs in the API process on first use and is kept in memory until `?refresh=true`. It takes
the API's run lock (without waiting), so a scan and an investigation never hold two DuckDB
instances at once, and the scanner's connection is closed when the scan ends. Nothing here changes
a scanner setting: the per-metric expanded lists are the scanner's own merged ranking, cut per
metric, with cards built by the scanner's `build_card`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from app.scanner import db
from app.scanner.models import AnomalyCard, MetricBoard, ScanReport
from app.scanner.scan import ScanResult, build_card, metric_family, scan
from app.scanner.settings import ScannerConfig, load_config

MAX_METRIC_LIMIT = 25  # most cards `?metric=KEY&limit=N` returns for one metric


class Busy(RuntimeError):
    """The run lock is held: a run or another scan is in progress."""


@dataclass
class Board:
    report: ScanReport
    expanded: dict[str, MetricBoard]  # configured metric key -> up to MAX_METRIC_LIMIT cards, ranked within it
    by_id: dict[str, AnomalyCard] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cards = [*self.report.cards]
        for board in [*self.report.by_metric, *self.expanded.values()]:
            cards.extend(board.cards)
        for card in cards:
            self.by_id.setdefault(card.id, card)

    def metric(self, key: str, limit: int) -> MetricBoard | None:
        board = self.expanded.get(key)
        if board is None:
            return None
        return board.model_copy(update={"cards": board.cards[: min(limit, MAX_METRIC_LIMIT)]})


def build_board(result: ScanResult, config: ScannerConfig) -> Board:
    """The report plus, per configured metric, its flagged episodes ranked within the metric."""
    overall = {id(c): rank for rank, c in enumerate(result.candidates, 1)}
    families: dict[str, list] = {}
    for candidate in result.candidates:
        families.setdefault(metric_family(candidate.series.metric.key), []).append(candidate)
    expanded = {}
    for board in result.report.by_metric:
        family = families.get(board.metric, [])
        expanded[board.metric] = MetricBoard(
            metric=board.metric,
            metric_label=board.metric_label,
            episodes_found=board.episodes_found,
            cards=[
                build_card(c, rank, config, overall_rank=overall[id(c)])
                for rank, c in enumerate(family[:MAX_METRIC_LIMIT], 1)
            ],
        )
    return Board(result.report, expanded)


def run_scan() -> Board:
    """One full scan on the sample, with the scanner's connection closed afterwards."""
    config = load_config()
    try:
        return build_board(scan(config=config), config)
    finally:
        db.default_database().close()


class BoardCache:
    """The last scan, computed on first use; `get(refresh=True)` recomputes."""

    def __init__(self, run_lock: threading.Lock, compute: Callable[[], Board] = run_scan) -> None:
        self._run_lock = run_lock
        self._compute = compute
        self._board: Board | None = None

    def get(self, refresh: bool = False) -> Board:
        board = self._board
        if board is not None and not refresh:
            return board
        if not self._run_lock.acquire(blocking=False):
            raise Busy("a run or a scan is already in progress; try again when it has finished")
        try:
            self._board = self._compute()
        finally:
            self._run_lock.release()
        return self._board

    def clear(self) -> None:
        self._board = None

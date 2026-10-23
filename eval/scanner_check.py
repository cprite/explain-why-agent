"""Plan check for the anomaly scanner (build-plan tasks 19a/19b, issue #9 criterion 7).

Runs the scanner on the sample exactly as `python -m app.scanner` does, then — and only here —
reads eval/answer_key.json and REPORTS, for each planted incident, whether the scan flagged an
episode on its metric, segment and window, and that episode's rank overall and within its metric;
recall over the determinable incidents; and the previous top-ten numbers (card in the overall top
ten, the old asserts (a) incident-06 and (b) incident-04) so nothing is hidden. Unplanted cards in
the top ten are listed.

Pass rule (owner's decision of 23 Oct, taken after seeing the top-ten result; see
docs/sprints/12-anomaly-scanner.md): at least one planted incident is flagged, and (c) no card is
only the normal weekly cycle. Exit code 0 when both hold and the scan finished, 1 otherwise. The
scanner never sees this file's inputs.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scanner.models import AnomalyCard
from app.scanner.scan import Candidate, ScanResult, scan
from app.scanner.settings import load_config

ANSWER_KEY = ROOT / "eval" / "answer_key.json"

# How this check reads the answer key's free-text fields in scanner terms.
SEGMENT_TYPES = {"national": "all", "state": "state", "category": "category", "seller": "seller",
                 "marketing_cohort": "channel"}
METRICS = {
    "incident-01": {"daily_orders", "revenue"},
    "incident-02": {"late_delivery_rate"},
    "incident-03": {"revenue", "daily_orders"},
    "incident-04": {"avg_freight"},
    "incident-05": {"payment_share"},
    "incident-06": {"avg_review_score"},
    "incident-07": {"channel_revenue", "revenue"},
    "incident-08": {"revenue"},
    "incident-09": {"avg_review_score"},
    "incident-10": {"avg_order_value"},
}


@dataclass
class Target:
    id: str
    segment_type: str
    segment_value: str
    start: date
    end: date
    metrics: set[str]
    determinable: bool


def load_targets() -> list[Target]:
    targets = []
    for item in json.loads(ANSWER_KEY.read_text(encoding="utf-8")):
        seg_type = SEGMENT_TYPES[item["segment"]["type"]]
        value = item["segment"]["value"]
        if seg_type == "all":
            value = "all"
        elif seg_type == "channel":  # "sellers closed via paid_search in 2018-03"
            value = value.split(" via ")[1].split()[0]
        targets.append(
            Target(
                id=item["id"],
                segment_type=seg_type,
                segment_value=value,
                start=date.fromisoformat(item["window_start"]),
                end=date.fromisoformat(item["window_end"]),
                metrics=METRICS[item["id"]],
                determinable=bool(item["determinable"]),
            )
        )
    return targets


def _metric_family(key: str) -> str:
    return key.split(":")[0]


def _names(card: AnomalyCard, target: Target, top_only: bool = False) -> bool:
    dims = card.attribution[:1] if top_only else card.attribution
    return any(d.dimension == target.segment_type and any(s.value == target.segment_value for s in d.slices)
               for d in dims)


def segment_hit(card: AnomalyCard, target: Target) -> bool:
    if card.period.start > target.end or card.period.end < target.start:
        return False
    if card.segment.type == target.segment_type and card.segment.value == target.segment_value:
        return True
    return _names(card, target)


def full_hit(card: AnomalyCard, target: Target) -> bool:
    return segment_hit(card, target) and _metric_family(card.metric) in target.metrics


@dataclass
class Placement:
    """Where a planted incident's best own episode sits in the scan."""

    overall_rank: int  # among every flagged episode after the merge (merged children at their parent's)
    metric_rank: int  # among the flagged episodes of the same configured metric
    candidate: Candidate  # the matching episode (a merged child, or the ranked episode itself)


def place(result: ScanResult, target: Target) -> Placement | None:
    """Best-ranked episode anywhere in the scan (beyond the top ten too) with the incident's
    metric, segment and window; merged children count at their parent's rank."""
    per_metric: dict[str, int] = {}
    for rank, cand in enumerate(result.candidates, 1):
        family = _metric_family(cand.series.metric.key)
        per_metric[family] = per_metric.get(family, 0) + 1
        for c in [cand, *cand.merged]:
            s = c.series
            if (
                _metric_family(s.metric.key) in target.metrics
                and s.segment_type == target.segment_type
                and s.segment_value == target.segment_value
                and c.start <= target.end
                and c.end >= target.start
            ):
                return Placement(rank, per_metric[family], c)
    return None


def peak_z(result: ScanResult, target: Target) -> tuple[str, float] | None:
    """Largest |robust z| the incident's own series reached inside its window (flagged or not)."""
    best: tuple[str, float] | None = None
    for (key, seg_type, seg_value), series in result.series.items():
        if (_metric_family(key) not in target.metrics or (seg_type, seg_value)
                != (target.segment_type, target.segment_value) or series.score is None):
            continue
        span = timedelta(days=6) if series.metric.grain == "week" else timedelta(0)
        for period, z in zip(series.periods, series.score.z, strict=True):
            if period <= target.end and period + span >= target.start and np.isfinite(z) \
                    and (best is None or abs(z) > abs(best[1])):
                best = (key, float(z))
    return best


def best_candidate(result: ScanResult, target: Target) -> tuple[int, Candidate] | None:
    placement = place(result, target)
    return (placement.overall_rank, placement.candidate) if placement else None


def weekly_cycle_only(card: AnomalyCard, result: ScanResult) -> bool:
    """A daily card whose every observed day lies within the range of the same weekday over the
    previous four weeks is just the weekly cycle."""
    if card.period.grain != "day":
        return False
    series = result.series[(card.metric, card.segment.type, card.segment.value)]
    index = {p: i for i, p in enumerate(series.periods)}
    values = series.values
    day = card.period.start
    while day <= card.period.end:
        same_weekday = [values[index[d]] for d in (day - timedelta(weeks=w) for w in range(1, 5)) if d in index]
        if not same_weekday or not (min(same_weekday) <= values[index[day]] <= max(same_weekday)):
            return False
        day += timedelta(days=1)
    return True


@dataclass
class Outcome:
    placements: dict[str, Placement | None]
    recall: int  # determinable incidents with a flagged episode on their metric, segment and window
    determinable: int
    top_ten_recall_segment: int  # previous rule: a top-ten card on the segment and window
    top_ten_recall_metric: int  # previous rule, metric matching too
    old_a: bool  # previous rule (a): incident-06 has a top-ten card
    old_b: bool  # previous rule (b): incident-04 has a top-ten card (own, or top attribution RJ)
    cycle_cards: list[str]
    timed_out: bool

    @property
    def passed(self) -> bool:
        """Owner's rule of 23 Oct: at least one planted incident flagged, and no card is only the
        weekly cycle (and the scan finished)."""
        return self.recall >= 1 and not self.cycle_cards and not self.timed_out


def evaluate(result: ScanResult, targets: list[Target]) -> Outcome:
    cards = result.report.cards
    determinable = [t for t in targets if t.determinable]
    placements = {t.id: place(result, t) for t in targets}
    by_id = {t.id: t for t in targets}
    t06, t04 = by_id["incident-06"], by_id["incident-04"]
    return Outcome(
        placements=placements,
        recall=sum(placements[t.id] is not None for t in determinable),
        determinable=len(determinable),
        top_ten_recall_segment=sum(any(segment_hit(c, t) for c in cards) for t in determinable),
        top_ten_recall_metric=sum(any(full_hit(c, t) for c in cards) for t in determinable),
        old_a=any(full_hit(c, t06) for c in cards),
        old_b=any(
            _metric_family(c.metric) == "avg_freight"
            and segment_hit(c, t04)
            and ((c.segment.type, c.segment.value) == ("state", "RJ") or _names(c, t04, top_only=True))
            for c in cards
        ),
        cycle_cards=[c.id for c in cards if weekly_cycle_only(c, result)],
        timed_out=result.report.timed_out,
    )


def _pass(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> int:
    result = scan()
    report = result.report
    cards = report.cards
    targets = load_targets()
    outcome = evaluate(result, targets)
    total = len(result.candidates)
    print(f"Scanner: {report.series_scanned} series, {report.episodes_found} flagged episodes "
          f"({total} after the parent/child merge), {report.queries} queries, {report.elapsed_seconds:.1f}s, "
          f"timed_out={report.timed_out}")
    print(f"Thresholds: {report.thresholds}")
    print("\nOverall top ten:")
    for c in cards:
        print(f"  {c.rank:>2}. {c.metric} | {c.segment.label} | {c.period.start}..{c.period.end} | "
              f"z {c.z_score:+.1f} | {c.top_attribution or '-'}")

    board_top = load_config().ranking.per_metric_top
    episodes_per_metric: dict[str, int] = {}
    for cand in result.candidates:
        family = _metric_family(cand.series.metric.key)
        episodes_per_metric[family] = episodes_per_metric.get(family, 0) + 1
    print("\nPlanted incidents (best own flagged episode on metric + segment + window; ranks by score):")
    for t in targets:
        p = outcome.placements[t.id]
        tag = "" if t.determinable else " (not determinable)"
        seg_cards = [c.rank for c in cards if segment_hit(c, t)]
        full_cards = [c.rank for c in cards if full_hit(c, t)]
        if p:
            family = _metric_family(p.candidate.series.metric.key)
            where = (f"FLAGGED {p.candidate.series.metric.key}, z {p.candidate.episode.z:+.2f}, "
                     f"{p.candidate.start}..{p.candidate.end}; overall rank {p.overall_rank} of {total}, "
                     f"rank {p.metric_rank} of {episodes_per_metric[family]} within {family} "
                     f"({'on' if p.metric_rank <= board_top else 'not on'} the per-metric board, top {board_top})")
        else:
            peak = peak_z(result, t)
            where = (f"not flagged (peak {peak[0]} z {peak[1]:+.2f} in the window, threshold "
                     f"{report.thresholds['z_threshold']})" if peak
                     else "not flagged (series not scored in the window: below the volume floor or too little history)")
        print(f"  {t.id}{tag}: {t.segment_type}={t.segment_value} {t.start}..{t.end} -> {where}; "
              f"top-ten cards: segment+window {seg_cards or '-'}, with metric {full_cards or '-'}")

    print(f"\nRecall (flagged episode on metric + segment + window): {outcome.recall}/{outcome.determinable}")
    on_board = sum(p is not None and p.metric_rank <= board_top
                   for t in targets if t.determinable for p in [outcome.placements[t.id]])
    print(f"On the per-metric board (top {board_top} of their metric): {on_board}/{outcome.determinable}")
    print("Previous rule, kept for comparison (a card in the overall top ten):")
    print(f"  top-ten recall (segment+window): {outcome.top_ten_recall_segment}/{outcome.determinable}")
    print(f"  top-ten recall (segment+window+metric): {outcome.top_ten_recall_metric}/{outcome.determinable}")
    print(f"  (a) incident-06 in the top ten: {_pass(outcome.old_a)}")
    print(f"  (b) incident-04 in the top ten (own card or top attribution RJ): {_pass(outcome.old_b)}")

    unplanted = [c for c in cards if not any(segment_hit(c, t) for t in targets)]
    print(f"\nUnplanted flags in the top ten ({len(unplanted)} of {len(cards)} cards):")
    for c in unplanted:
        print(f"  {c.rank:>2}. {c.question}")

    print("\nChecks (owner's rule of 23 Oct; the top-ten rule above is reported, not asserted):")
    print(f"  at least one planted incident flagged: {_pass(outcome.recall >= 1)} ({outcome.recall})")
    print(f"  (c) no weekly-cycle-only card: {_pass(not outcome.cycle_cards)} {outcome.cycle_cards or ''}".rstrip())
    print(f"  scan finished within the time cap: {_pass(not outcome.timed_out)}")
    if not outcome.passed:
        print("\nFAILED")
        return 1
    print("\nAll plan checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

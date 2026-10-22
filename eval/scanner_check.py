"""Plan check for the anomaly scanner (build-plan tasks 19a/19b, issue #9 criterion 7).

Runs the scanner on the sample exactly as `python -m app.scanner` does, then — and only here —
reads eval/answer_key.json to report, for each planted incident, whether a card overlaps its
segment and window. Prints recall over the determinable incidents, lists the cards that match no
incident (unplanted flags), and asserts:

  (a) incident-06 (average review score, relogios_presentes, January 2018) is flagged;
  (b) incident-04 (average freight, RJ, August 2018) is flagged, as its own card or as a card whose
      top attribution names RJ;
  (c) no card is only the normal weekly cycle.

Exit code 0 when all three hold, 1 otherwise. The scanner never sees this file's inputs.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scanner.models import AnomalyCard
from app.scanner.scan import Candidate, ScanResult, build_card, scan
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


def best_candidate(result: ScanResult, target: Target) -> tuple[int, Candidate] | None:
    """Best-ranked episode anywhere in the scan (beyond the top ten too) with the incident's
    metric, segment and window; merged children count at their parent's rank."""
    for rank, cand in enumerate(result.candidates, 1):
        for c in [cand, *cand.merged]:
            s = c.series
            if (
                _metric_family(s.metric.key) in target.metrics
                and s.segment_type == target.segment_type
                and s.segment_value == target.segment_value
                and c.start <= target.end
                and c.end >= target.start
            ):
                return rank, c
    return None


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


def main() -> int:
    result = scan()
    report = result.report
    cards = report.cards
    targets = load_targets()
    print(f"Scanner: {report.series_scanned} series, {report.episodes_found} flagged episodes, "
          f"{report.queries} queries, {report.elapsed_seconds:.1f}s, timed_out={report.timed_out}")
    print(f"Thresholds: {report.thresholds}")
    print("\nCards:")
    for c in cards:
        print(f"  {c.rank:>2}. {c.metric} | {c.segment.label} | {c.period.start}..{c.period.end} | "
              f"z {c.z_score:+.1f} | {c.top_attribution or '-'}")

    print("\nPlanted incidents (card in the top ten overlapping segment and window):")
    hits_segment = hits_full = 0
    determinable = [t for t in targets if t.determinable]
    for t in targets:
        seg_cards = [c.rank for c in cards if segment_hit(c, t)]
        full_cards = [c.rank for c in cards if full_hit(c, t)]
        if t.determinable:
            hits_segment += bool(seg_cards)
            hits_full += bool(full_cards)
        best = best_candidate(result, t)
        best_txt = (f"best own episode: rank {best[0]} of {len(result.candidates)}, z {best[1].episode.z:+.1f}, "
                    f"{best[1].start}..{best[1].end}" if best else "no own episode flagged")
        tag = "" if t.determinable else " (not determinable)"
        print(f"  {t.id}{tag}: {t.segment_type}={t.segment_value} {t.start}..{t.end} -> "
              f"segment+window cards {seg_cards or '-'}, with metric {full_cards or '-'}; {best_txt}")
    print(f"\nRecall (segment+window): {hits_segment}/{len(determinable)}")
    print(f"Recall (segment+window+metric): {hits_full}/{len(determinable)}")

    unplanted = [c for c in cards if not any(segment_hit(c, t) for t in targets)]
    print(f"\nUnplanted flags ({len(unplanted)} of {len(cards)} cards):")
    for c in unplanted:
        print(f"  {c.rank:>2}. {c.question}")

    by_id = {t.id: t for t in targets}
    failures = []
    t06 = by_id["incident-06"]
    if not any(full_hit(c, t06) for c in cards):
        failures.append("(a) incident-06 watches review dip not flagged")
    t04 = by_id["incident-04"]
    if not any(
        _metric_family(c.metric) == "avg_freight"
        and segment_hit(c, t04)
        and ((c.segment.type, c.segment.value) == ("state", "RJ") or _names(c, t04, top_only=True))
        for c in cards
    ):
        failures.append("(b) incident-04 RJ freight rise not flagged (own card or top attribution RJ)")
    cycle_cards = [c.id for c in cards if weekly_cycle_only(c, result)]
    if cycle_cards:
        failures.append(f"(c) cards that are only the weekly cycle: {cycle_cards}")
    if report.timed_out:
        failures.append("scan hit the time cap")

    for label, target in (("incident-06", t06), ("incident-04", t04)):
        best = best_candidate(result, target)
        if best:
            card = build_card(best[1], best[0], load_config())
            print(f"{label} own episode: z {card.z_score:+.2f}, baseline {card.baseline:.3f}, "
                  f"observed {card.observed:.3f}, {card.period.start}..{card.period.end}")
        else:
            print(f"{label}: no own episode (|z| < threshold or below the volume floor)")

    print("\nChecks:")
    print(f"  (a) incident-06 flagged: {'PASS' if not any(f.startswith('(a)') for f in failures) else 'FAIL'}")
    print(f"  (b) incident-04 flagged: {'PASS' if not any(f.startswith('(b)') for f in failures) else 'FAIL'}")
    print(f"  (c) no weekly-cycle-only card: {'PASS' if not cycle_cards else 'FAIL'}")
    if failures:
        print("\nFAILED: " + "; ".join(failures))
        return 1
    print("\nAll plan checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

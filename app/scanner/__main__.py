"""`python -m app.scanner` — print the ranked anomaly cards (overall top ten, then the per-metric
board); `--json [PATH]` also writes them."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.scanner.models import AnomalyCard, ScanReport
from app.scanner.scan import scan
from app.scanner.settings import load_config

ROOT = Path(__file__).resolve().parents[2]


def default_json_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "logs" / f"anomalies-{stamp}.json"


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3f}"


def _table(cards: list[AnomalyCard], overall: bool = False) -> list[str]:
    header = ["#", "metric", "segment", "period", "baseline", "observed", "change", "z", "driven by"]
    if overall:
        header.insert(1, "overall")
    rows = []
    for card in cards:
        p = card.period
        period = p.start.isoformat() if p.start == p.end else f"{p.start.isoformat()}..{p.end.isoformat()}"
        pct = f"{card.change_pct:+.0%}" if card.change_pct is not None else "n/a"
        rows.append(
            [
                str(card.rank),
                card.metric,
                card.segment.label,
                period,
                _fmt(card.baseline),
                _fmt(card.observed),
                pct,
                f"{card.z_score:+.1f}",
                (card.top_attribution or "-").removeprefix("driven by "),
            ]
        )
        if overall:
            rows[-1].insert(1, str(card.overall_rank or "-"))
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)).rstrip()]
    lines.append("  ".join("-" * w for w in widths).rstrip())
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows]
    return lines


def render_table(report: ScanReport) -> str:
    lines = _table(report.cards)
    if report.cards:
        lines.append("")
        lines += [f"{c.rank}. {c.question}" for c in report.cards]
    return "\n".join(lines)


def render_boards(report: ScanReport) -> str:
    """Per-metric board: each metric's top episodes, ranked within the metric (`overall` is the
    episode's rank among all flagged episodes)."""
    lines = []
    for board in report.by_metric:
        lines.append(f"\n{board.metric} ({board.metric_label}): {board.episodes_found} flagged episodes")
        lines += ["  " + line for line in _table(board.cards, overall=True)] if board.cards else ["  (none flagged)"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.scanner", description="Anomaly scanner (sample data)")
    parser.add_argument(
        "--json",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="also write the cards as JSON (default path logs/anomalies-<timestamp>.json)",
    )
    args = parser.parse_args(argv)

    result = scan()
    report = result.report
    print(
        f"Anomaly scan ({report.data_source}): {report.series_scanned} series, "
        f"{report.episodes_found} flagged episodes, {report.queries} queries, {report.elapsed_seconds:.1f}s"
    )
    print(f"\nTop {len(report.cards)} overall:")
    print(render_table(report))
    print(f"\nPer-metric board (top {load_config().ranking.per_metric_top} flagged episodes of each metric):")
    print(render_boards(report))
    if args.json is not None:
        path = Path(args.json) if args.json else default_json_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {len(report.cards)} cards to {path}")
    if report.timed_out:
        print("WARNING: scan stopped at the time cap (SCANNER_TIMEOUT_S) or a loop cap; cards are partial.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

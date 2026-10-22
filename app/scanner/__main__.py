"""`python -m app.scanner` — print the ranked anomaly cards; `--json [PATH]` also writes them."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.scanner.models import ScanReport
from app.scanner.scan import scan

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


def render_table(report: ScanReport) -> str:
    header = ["#", "metric", "segment", "period", "baseline", "observed", "change", "z", "driven by"]
    rows = []
    for card in report.cards:
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
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True))]
    lines.append("  ".join("-" * w for w in widths))
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in rows]
    if report.cards:
        lines.append("")
        lines += [f"{c.rank}. {c.question}" for c in report.cards]
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
    print(render_table(report))
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

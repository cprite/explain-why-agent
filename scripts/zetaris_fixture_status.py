"""Where the Zetaris plan-check fixtures came from: a live Zetaris, or synthesised from DuckDB.

    python scripts/zetaris_fixture_status.py                 # list, warn if any is synthetic, exit 0
    python scripts/zetaris_fixture_status.py --require-live  # exit 1 while any fixture is synthetic

Synthetic fixtures (`scripts/zetaris_parity.py --synthetic`) replay DuckDB rows through the adapter,
so the plan check then proves the rewrite, request shape and type decoding, not that Zetaris gives
the same numbers. Only `scripts/zetaris_parity.py --record` against a live server makes them
evidence. In GitHub Actions the warning is also raised as a run annotation.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.parity import FIXTURE_DIR, load_fixtures, synthetic_fixtures

WARNING = (
    "{n} of {total} Zetaris fixtures are synthetic (DuckDB rows in REST wire format), so the plan check "
    "does not yet show that Zetaris gives the same numbers. Record them live: "
    "python scripts/zetaris_parity.py --record"
)


def main(argv: list[str] | None = None) -> int:
    """Print each fixture's provenance; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require-live", action="store_true", help="fail while any fixture is synthetic")
    parser.add_argument("--dir", type=Path, default=FIXTURE_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    fixtures = load_fixtures(args.dir)
    if not fixtures:
        print(f"no fixtures in {args.dir}", file=sys.stderr)
        return 1
    for name, record in fixtures.items():
        print(f"  {name:<32} {record['recorded_at']}  {record['recorded_with']}")
    synthetic = synthetic_fixtures(fixtures)
    if not synthetic:
        print(f"all {len(fixtures)} fixtures recorded from a live Zetaris")
        return 0
    message = WARNING.format(n=len(synthetic), total=len(fixtures))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=Zetaris fixtures are synthetic::{message}")
    print(("FAIL: " if args.require_live else "WARNING: ") + message)
    return 1 if args.require_live else 0


if __name__ == "__main__":
    sys.exit(main())

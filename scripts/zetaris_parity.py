"""Live parity check: the Day 1 question's queries through Zetaris (USL over REST) and local DuckDB.

    python scripts/zetaris_parity.py              # live: parity table and PASS/FAIL
    python scripts/zetaris_parity.py --record     # live, and rewrite tests/fixtures/zetaris/ from Zetaris
    python scripts/zetaris_parity.py --synthetic  # no Zetaris: write fixtures from DuckDB in REST wire format

Needs `ZETARIS_URL`, `ZETARIS_ORG_ID` and `ZETARIS_API_KEY` (or `ZETARIS_USERNAME` and
`ZETARIS_PASSWORD`). Without them it says so and exits with code 2. Exit 0 when every query matches,
1 otherwise. The Zetaris side runs with fallback off, so a Zetaris failure is a FAIL, never a quiet
local answer. Not run in CI (CI replays the fixtures in `tests/test_zetaris_plan_check.py`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.data.layer import QueryResult
from app.data.local import LocalDataLayer
from app.data.parity import (
    compare,
    load_queries,
    side_by_side,
    wire_body,
    write_fixture,
)
from app.data.zetaris import ZetarisClient, ZetarisDataLayer, to_usl_sql

MISSING = (
    "Zetaris credentials are not set: this check needs ZETARIS_URL, ZETARIS_ORG_ID and ZETARIS_API_KEY "
    "(or ZETARIS_USERNAME and ZETARIS_PASSWORD) and a reachable Zetaris. Nothing was run. "
    "CI runs the same queries against recorded responses: pytest -s tests/test_zetaris_plan_check.py"
)


def synthesise(local: LocalDataLayer) -> int:
    """Write every fixture from the local adapter's rows, encoded the way Zetaris REST returns them."""
    for query in load_queries():
        result = local.query(query.source, query.sql)
        if not isinstance(result, QueryResult):
            print(f"[FAIL] {query.name}: {result.code}: {result.message}")
            return 1
        zetaris_sql, _ = to_usl_sql(result.sql.strip().rstrip(";").rstrip(), query.source)
        path = write_fixture(query.name, zetaris_sql, local.max_rows + 1, wire_body(result),
                             recorded_with="synthetic (local DuckDB rows in Zetaris REST wire format)")
        print(f"wrote {path.name}: {result.row_count} rows")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the parity check; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--record", action="store_true", help="rewrite the fixtures from the live responses")
    group.add_argument("--synthetic", action="store_true", help="write fixtures from DuckDB, no Zetaris")
    args = parser.parse_args(argv)
    settings = get_settings().model_copy(update={"sample_mode": False, "record_cache": False})

    if args.synthetic:
        with LocalDataLayer(run_id="zetaris-fixtures", settings=settings) as local:
            return synthesise(local)

    has_auth = settings.zetaris_api_key or (settings.zetaris_username and settings.zetaris_password)
    if not (settings.zetaris_url and settings.zetaris_org_id and has_auth):
        print(MISSING, file=sys.stderr)
        return 2

    queries = load_queries()
    recorded: dict[str, tuple[str, int, dict]] = {}
    current: list[str] = []

    def recorder(sql: str, limit: int, body: dict) -> None:
        recorded[current[-1]] = (sql, limit, body)

    client = ZetarisClient.from_settings(settings, recorder=recorder if args.record else None)
    results = []
    with LocalDataLayer(run_id="zetaris-parity", settings=settings) as local, \
            ZetarisDataLayer(run_id="zetaris-parity", settings=settings, client=client, fallback=False) as zetaris:
        print(f"Zetaris USL parity: {len(queries)} queries, local DuckDB vs Zetaris REST (fallback off)\n")
        for query in queries:
            current.append(query.name)
            left = local.query(query.source, query.sql)
            right = zetaris.query(query.source, query.sql)
            passed, verdict = compare(left, right)
            results.append((query.name, passed, verdict, left, right))
            print(f"== {query.name}: {verdict}")
            print(side_by_side(left, right))
            print()
        print("Parity table")
        print(f"  {'query':<32} {'local rows':>10} {'zetaris rows':>12} {'zetaris ms':>10}  verdict")
        for name, _passed, verdict, left, right in results:
            lrows = left.row_count if isinstance(left, QueryResult) else "-"
            rrows = right.row_count if isinstance(right, QueryResult) else "-"
            print(f"  {name:<32} {lrows!s:>10} {rrows!s:>12} {right.duration_ms:>10.0f}  {verdict}")
        print(f"query log: {zetaris.log.path}")

    ok = all(passed for _, passed, *_ in results)
    if args.record:
        for name, (sql, limit, body) in recorded.items():
            write_fixture(name, sql, limit, body, recorded_with="zetaris (live REST response)")
        print(f"recorded {len(recorded)} fixtures in tests/fixtures/zetaris/")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

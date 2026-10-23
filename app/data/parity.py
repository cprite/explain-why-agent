"""Zetaris-versus-local parity: the query list, recorded REST fixtures, replay, comparison and printing.

Shared by the CI plan check (`tests/test_zetaris_plan_check.py`, replaying `tests/fixtures/zetaris/`)
and the live check (`scripts/zetaris_parity.py`).

Fixture files hold only what a replay needs: the statement as sent to Zetaris, the limit, and the
response body's `headers`, `data` and `total`. No URL, host, token, organisation id or request id.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.config import REPO_ROOT
from app.data.layer import QueryOutcome, QueryResult
from app.data.zetaris import RUN_SQL_PATH

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "zetaris"
QUERIES_FILE = FIXTURE_DIR / "queries.json"
BODY_KEYS = ("headers", "data", "total")


@dataclass(frozen=True)
class ParityQuery:
    """One statement checked on both adapters."""

    name: str
    source: str | None
    sql: str
    note: str = ""


def load_queries(path: Path = QUERIES_FILE) -> list[ParityQuery]:
    """The parity query list: the Day 1 question's queries plus a few type and scope checks."""
    return [ParityQuery(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def normalise_sql(sql: str) -> str:
    """Whitespace-collapsed SQL, the replay key."""
    return " ".join(sql.split())


def fixture_path(name: str, directory: Path = FIXTURE_DIR) -> Path:
    """Where the recorded response for one parity query lives."""
    return directory / f"{name}.json"


def write_fixture(
    name: str, zetaris_sql: str, limit: int, body: dict[str, Any], *, recorded_with: str,
    directory: Path = FIXTURE_DIR,
) -> Path:
    """Write one fixture, keeping only the response keys a replay needs."""
    path = fixture_path(name, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "name": name,
        "recorded_with": recorded_with,
        "recorded_at": datetime.now(UTC).date().isoformat(),
        "request": {"sql": zetaris_sql, "limit": limit},
        "response": {key: body.get(key) for key in BODY_KEYS},
    }
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_fixtures(directory: Path = FIXTURE_DIR) -> dict[str, dict[str, Any]]:
    """Recorded fixtures keyed by query name (`queries.json` excluded)."""
    out = {}
    for path in sorted(directory.glob("*.json")):
        if path.name != QUERIES_FILE.name:
            record = json.loads(path.read_text(encoding="utf-8"))
            out[record["name"]] = record
    return out


def replay_transport(fixtures: dict[str, dict[str, Any]], seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    """An httpx transport that answers `sqls/run` from recorded fixtures, matched on the SQL text.

    It insists on the headers the real server needs (bearer token, `X-Org-ID`, `X-Request-ID`), so a
    replay also checks the request shape. An unrecorded statement gets a 400, like a Zetaris error.
    """
    by_sql = {normalise_sql(f["request"]["sql"]): f["response"] for f in fixtures.values()}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if not request.url.path.endswith(RUN_SQL_PATH) or request.method != "POST":
            return httpx.Response(404, json={"msg": "not recorded"})
        if not request.headers.get("Authorization", "").startswith("Bearer ") or not request.headers.get(
            "X-Org-ID"
        ) or not request.headers.get("X-Request-ID"):
            return httpx.Response(401, json={"msg": "missing auth headers"})
        payload = json.loads(request.content)
        response = by_sql.get(normalise_sql(payload["sql"]))
        if response is None:
            return httpx.Response(400, json={"msg": "AnalysisException: no recorded response for this statement"})
        return httpx.Response(200, json={**response, "timeUsed": 1})

    return httpx.MockTransport(handler)


# --- Zetaris wire format for fixtures generated without a server -----------------------------------

_DECIMAL_PLACES = Decimal(1).scaleb(-18)


def wire_value(value: Any) -> Any:
    """A local value as Zetaris REST sends it: strings, decimals with 18 places, nulls as null."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(Decimal(repr(value)).quantize(_DECIMAL_PLACES))
    text = str(value)
    if len(text) >= 19 and text[10] == "T":
        return text.replace("T", " ", 1)
    return text


def wire_body(result: QueryResult) -> dict[str, Any]:
    """A local result as a Zetaris `sqls/run` response body."""
    return {
        "headers": list(result.columns),
        "data": [[wire_value(row.get(col)) for col in result.columns] for row in result.rows],
        "total": result.row_count,
    }


# --- comparison --------------------------------------------------------------------------------------


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def _rows_equal(left: list[dict[str, Any]], right: list[dict[str, Any]], columns: list[str]) -> bool:
    return len(left) == len(right) and all(
        _same(lr.get(c), rr.get(c)) for lr, rr in zip(left, right, strict=True) for c in columns
    )


def _sort_key(row: dict[str, Any], columns: list[str]) -> tuple:
    return tuple((v is None, round(v, 6) if isinstance(v, float) else v) for v in (row.get(c) for c in columns))


def compare(local: QueryOutcome, zetaris: QueryOutcome) -> tuple[bool, str]:
    """(passed, verdict): the same columns and the same numbers.

    Rows are compared in order first. If only the order of rows differs, or only the identifiers on
    rows that tie on every number (an `ORDER BY … LIMIT` that cuts through a tie keeps different
    sellers on different engines), the numbers are still the same and the check passes, saying so.
    """
    if not isinstance(local, QueryResult) or not isinstance(zetaris, QueryResult):
        bad = local if not isinstance(local, QueryResult) else zetaris
        return False, f"FAIL: {bad.adapter} returned {bad.code}: {bad.message}"
    if local.columns != zetaris.columns:
        return False, f"FAIL: columns differ: {local.columns} vs {zetaris.columns}"
    columns = local.columns
    if _rows_equal(local.rows, zetaris.rows, columns):
        return True, "PASS"
    key = lambda row: _sort_key(row, columns)
    if _rows_equal(sorted(local.rows, key=key), sorted(zetaris.rows, key=key), columns):
        return True, "PASS (same rows, different order)"
    numeric = [c for c in columns if any(isinstance(r.get(c), int | float) for r in local.rows)]
    nkey = lambda row: _sort_key(row, numeric)
    if numeric and _rows_equal(sorted(local.rows, key=nkey), sorted(zetaris.rows, key=nkey), numeric):
        return True, "PASS (same numbers; tied rows carry different identifiers)"
    return False, "FAIL: values differ"


def _cell(value: Any, width: int) -> str:
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".") if abs(value) < 1e12 else f"{value:.6g}"
    else:
        text = "NULL" if value is None else str(value)
    return (text if len(text) <= width else text[: width - 1] + "~").rjust(width)


def side_by_side(local: QueryOutcome, zetaris: QueryOutcome, max_rows: int = 20, width: int = 12) -> str:
    """Both result sets next to each other, one line per row: `local | zetaris`."""
    if not isinstance(local, QueryResult) or not isinstance(zetaris, QueryResult):
        return "\n".join(f"  {o.adapter}: {o.code}: {o.message}" for o in (local, zetaris)
                         if not isinstance(o, QueryResult))
    columns = local.columns
    head = " ".join(_cell(c, width) for c in columns)
    lines = [f"  {'local (DuckDB)':<{len(head)}} | zetaris (USL, REST)", f"  {head} | {head}"]
    for i in range(min(max(len(local.rows), len(zetaris.rows)), max_rows)):
        left = " ".join(_cell(local.rows[i].get(c), width) for c in columns) if i < len(local.rows) else ""
        right = " ".join(_cell(zetaris.rows[i].get(c), width) for c in columns) if i < len(zetaris.rows) else ""
        lines.append(f"  {left:<{len(head)}} | {right}")
    if max(len(local.rows), len(zetaris.rows)) > max_rows:
        lines.append(f"  … {local.row_count} local rows, {zetaris.row_count} zetaris rows")
    return "\n".join(lines)

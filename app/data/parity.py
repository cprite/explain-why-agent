"""Zetaris-versus-local parity: the query list, recorded REST fixtures, replay, comparison and printing.

Shared by the CI plan check (`tests/test_zetaris_plan_check.py`, replaying `tests/fixtures/zetaris/`)
and the live check (`scripts/zetaris_parity.py`).

Fixture files hold only what a replay needs: the statement as sent to Zetaris, the limit, and the
response body's `headers`, `data` and `total`. No URL, host, token, organisation id or request id.
"""

from __future__ import annotations

import json
import math
import re
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
LIVE = "zetaris (live REST response)"
SYNTHETIC = "synthetic (local DuckDB rows in Zetaris REST wire format)"


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


def synthetic_fixtures(fixtures: dict[str, dict[str, Any]]) -> list[str]:
    """Names of fixtures not recorded from a live Zetaris (they prove the adapter, not Zetaris's numbers)."""
    return sorted(name for name, record in fixtures.items() if record["recorded_with"] != LIVE)


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


_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*;?\s*$", re.IGNORECASE)
_FINAL_ORDER_BY = re.compile(r"\bORDER\s+BY\s+((?:(?!\bORDER\s+BY\b).)+?)\s+LIMIT\s+\d+\s*;?\s*$",
                             re.IGNORECASE | re.DOTALL)
_ORDER_MODIFIERS = re.compile(r"\s+(?:ASC|DESC)\b|\s+NULLS\s+(?:FIRST|LAST)\b", re.IGNORECASE)
_IDENTIFIER = re.compile(r'(?:\w+\.)?(?:\w+|"[^"]+")')

# Relative tolerance for numbers. Spark evaluates `x / 7.0` as a DECIMAL with scale 6 (1/7 -> 0.142857),
# DuckDB as a DOUBLE, so a ratio rounded to 4 places can read 70.0001 on Zetaris and 70 locally
# (relative difference 1.4e-6). 1e-5 absorbs that; a difference of 1e-4 or more still fails.
NUMERIC_REL_TOL = 1e-5
NUMERIC_ABS_TOL = 1e-9


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=NUMERIC_REL_TOL, abs_tol=NUMERIC_ABS_TOL)
    return a == b


def _rows_equal(left: list[dict[str, Any]], right: list[dict[str, Any]], columns: list[str]) -> bool:
    return len(left) == len(right) and all(
        _same(lr.get(c), rr.get(c)) for lr, rr in zip(left, right, strict=True) for c in columns
    )


def _sort_key(row: dict[str, Any], columns: list[str]) -> tuple:
    return tuple((v is None, round(v, 6) if isinstance(v, float) else v) for v in (row.get(c) for c in columns))


def _same_numbers(left: tuple, right: tuple) -> bool:
    return all(_same(a, b) for a, b in zip(left, right, strict=True))


def _group(rows: list[dict[str, Any]], numeric: list[str], other: list[str],
           keys: list[tuple] | None = None) -> list[tuple[tuple, list[tuple]]] | None:
    """Rows grouped by their numbers within `NUMERIC_REL_TOL`: [(numbers, sorted other-column values)].

    With `keys` (the other side's group numbers), every row must join one of those groups, in that
    order; None if a row matches none of them (that side holds numbers the other does not).
    """
    groups: list[tuple[tuple, list[tuple]]] = [(key, []) for key in keys or []]
    for row in rows:
        numbers = tuple(row.get(c) for c in numeric)
        for key, members in groups:
            if _same_numbers(key, numbers):
                members.append(tuple(_sort_key(row, other)))
                break
        else:
            if keys is not None:
                return None
            groups.append((numbers, [tuple(_sort_key(row, other))]))
    return [(key, sorted(members)) for key, members in groups]


def _format_variant(a: Any, b: Any) -> bool:
    """One value is the other with something appended (`2017-11-24` vs `2017-11-24 00:00:00`)."""
    left, right = str(a), str(b)
    return left != right and (left.startswith(right) or right.startswith(left))


def _order_columns(sql: str, columns: list[str]) -> list[str] | None:
    """The result columns of the statement's final `ORDER BY … LIMIT n`, or None if it cannot be read.

    Each item must be a plain output column (optionally qualified, `t.col`) or a 1-based position,
    with optional `ASC`/`DESC` and `NULLS FIRST`/`NULLS LAST`; an expression gives None.
    """
    match = _FINAL_ORDER_BY.search(sql.strip())
    if not match or ")" in match.group(1):
        return None
    by_name = {c.lower(): c for c in columns}
    out = []
    for item in match.group(1).split(","):
        term = _ORDER_MODIFIERS.sub("", item).strip()
        if term.isdigit() and 1 <= int(term) <= len(columns):
            out.append(columns[int(term) - 1])
        elif _IDENTIFIER.fullmatch(term) and term.rsplit(".", 1)[-1].strip('"').lower() in by_name:
            out.append(by_name[term.rsplit(".", 1)[-1].strip('"').lower()])
        else:
            return None
    return out or None


def _tie_at_cut(local: QueryResult, zetaris: QueryResult, numeric: list[str]) -> bool:
    """True if the results differ only in which tied rows an `ORDER BY … LIMIT n` kept.

    Legitimate only when the statement ends in `LIMIT n` and the limit was reached. The tie key is
    the final `ORDER BY` column(s): rows whose key equals the last row's (within `NUMERIC_REL_TOL`)
    form the group the LIMIT cut, and each engine may keep different members of it, which can differ
    in every other column. Both sides must hold the same number of them, every row above the cut must
    match (in any order, numbers within tolerance), and a label that is a reformatting of the other
    side's (a date printed as a timestamp) is a difference, not a tie. If the `ORDER BY` cannot be
    read, the tie key falls back to all numeric columns (`_tie_at_cut_by_numbers`).
    """
    match = _TRAILING_LIMIT.search(local.sql.strip())
    if not match or not local.rows or len(local.rows) != int(match.group(1)):
        return False
    if len(zetaris.rows) != len(local.rows):
        return False
    keys = _order_columns(local.sql, local.columns)
    if keys is None:
        return _tie_at_cut_by_numbers(local, zetaris, numeric)
    cut = tuple(local.rows[-1].get(c) for c in keys)

    def at_cut(row: dict[str, Any]) -> bool:
        return _same_numbers(cut, tuple(row.get(c) for c in keys))

    if not at_cut(zetaris.rows[-1]):
        return False
    columns = local.columns
    left_above = sorted((r for r in local.rows if not at_cut(r)), key=lambda row: _sort_key(row, columns))
    right_above = sorted((r for r in zetaris.rows if not at_cut(r)), key=lambda row: _sort_key(row, columns))
    if not _rows_equal(left_above, right_above, columns):
        return False
    other = [c for c in columns if c not in keys]
    lvals = [r.get(c) for r in local.rows if at_cut(r) for c in other]
    rvals = [r.get(c) for r in zetaris.rows if at_cut(r) for c in other]
    return not any(_format_variant(a, b) for a in lvals for b in rvals
                   if isinstance(a, str) and isinstance(b, str))


def _tie_at_cut_by_numbers(local: QueryResult, zetaris: QueryResult, numeric: list[str]) -> bool:
    """The tie check keyed on all numeric columns, for a statement whose `ORDER BY` cannot be read.

    The last tie group (the rows sharing the numbers of the last row, within `NUMERIC_REL_TOL`) can be
    cut at a different member on each engine. Every other group must carry the same identifiers, both
    sides must hold the same numbers with the same group sizes, and reformatted identifiers fail.
    """
    if not numeric:
        return False
    other = [c for c in local.columns if c not in numeric]
    left = _group(local.rows, numeric, other)
    right = _group(zetaris.rows, numeric, other, keys=[key for key, _ in left])
    if right is None or any(len(lm) != len(rm) for (_, lm), (_, rm) in zip(left, right, strict=True)):
        return False
    cut = tuple(local.rows[-1].get(c) for c in numeric)
    if not _same_numbers(cut, tuple(zetaris.rows[-1].get(c) for c in numeric)):
        return False
    cut_index = next(i for i, (key, _) in enumerate(left) if _same_numbers(key, cut))
    for i, ((_, lm), (_, rm)) in enumerate(zip(left, right, strict=True)):
        if i == cut_index:
            continue
        if any(not _same(a, b) for lv, rv in zip(lm, rm, strict=True)
               for (_, a), (_, b) in zip(lv, rv, strict=True)):
            return False
    lvals = [v for _, v in (cell for t in left[cut_index][1] for cell in t)]
    rvals = [v for _, v in (cell for t in right[cut_index][1] for cell in t)]
    return not any(_format_variant(a, b) for a in lvals for b in rvals if a is not None and b is not None)


def compare(local: QueryOutcome, zetaris: QueryOutcome) -> tuple[bool, str]:
    """(passed, verdict): the same columns and the same values.

    Rows are compared in order first, then as sorted rows (only the order differs). The one other
    pass is an `ORDER BY … LIMIT n` that cuts through a tie: the engines may keep different rows
    whose order key equals the cut value, so only those rows may differ in their other columns (see
    `_tie_at_cut`). Labels attached to different numbers, or dates formatted differently, fail.
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
    numeric = [c for c in columns if any(isinstance(r.get(c), int | float) and not isinstance(r.get(c), bool)
                                         for r in local.rows)]
    if _tie_at_cut(local, zetaris, numeric):
        return True, "PASS (same numbers; the LIMIT cut a tie at different rows)"
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

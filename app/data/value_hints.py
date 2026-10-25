"""Value hints: the stored values of the text columns, read from the data (Sprint 11d).

    hints = value_hints(data)   # {"orders.customers": {"customer_state": [...], "customer_city": "..."}, ...}

Agents filter on text columns (states, payment types, order status, categories, marketing origin, ...).
A name in a question is often not the stored value (a state's full name where the column holds a
two-letter code, a hyphen where the data has an underscore, title case where the data is lower case),
and a filter on it matches nothing. The hints show the agents what is actually stored:

- a column with at most `MAX_LISTED_VALUES` distinct values (ids excepted): every value, most frequent
  first;
- any other text column: a short string with the number of distinct values, the case or format
  (`lower case`, `upper case`, `mixed case`, `32-char hex id`, `free text`) and
  `MAX_EXAMPLES` examples, most frequent first.

Nothing here is written by hand: every value comes from profiling queries run through the data layer's
`profile` (local DuckDB or Zetaris; neither takes a query id from the run nor writes the run's query
log, so the investigation's prompts are the same whether or not the hints were already cached). The
result is kept per process, keyed by the adapter and the schema (tables, row counts, columns), so it
is built once. Its JSON form is capped at `MAX_HINT_CHARS`: past the cap, the longest value lists
become summaries, then the trailing columns are dropped.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any

from app.data.layer import DataLayer, QueryResult

MAX_LISTED_VALUES = 80
"""Text columns with at most this many distinct values are listed in full (ids excepted)."""
MAX_EXAMPLES = 3
"""Examples given for a text column with more distinct values."""
MAX_VALUE_CHARS = 60
"""Longest value shown; longer values are cut."""
FREE_TEXT_MIN_CHARS = 100
"""A column whose longest value is at least this long is free text (examples are still cut)."""
MAX_HINT_CHARS = 10000
"""Cap on the JSON size of all the hints together."""
PROFILE_ROW_LIMIT = MAX_LISTED_VALUES + 1

_TEXT_TYPE_RE = re.compile(r"char|string|text", re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-f]+$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

Hints = dict[str, dict[str, Any]]

_memo: dict[tuple[Any, ...], Hints] = {}
_memo_lock = threading.Lock()


def is_text(type_name: str) -> bool:
    """True for a text column type (DuckDB `VARCHAR`, USL `varchar(n)`, `string`, `text`)."""
    return bool(_TEXT_TYPE_RE.search(type_name or ""))


def _clip(value: Any) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= MAX_VALUE_CHARS else text[: MAX_VALUE_CHARS - 1] + "…"


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format(stats: dict[str, Any], examples: list[str]) -> str:
    """The case or format of a column from its profile counts and examples."""
    shortest, longest = _number(stats.get("min_len")), _number(stats.get("max_len"))
    if longest >= FREE_TEXT_MIN_CHARS:
        return "free text"
    if examples and shortest == longest and all(_HEX_RE.match(e) for e in examples):
        return f"{longest}-char hex id"
    upper, lower = _number(stats.get("with_upper")), _number(stats.get("with_lower"))
    case = ("mixed case" if upper and lower else "upper case" if upper
            else "lower case" if lower else "no letters")
    return f"{case}, {longest} chars" if shortest == longest else case


def _profile_table(data: DataLayer, fqn: str, columns: list[str]) -> dict[str, Any]:
    """Hints for the text `columns` of one table (`<source>.<table>`)."""
    # Column names are plain identifiers (checked by the caller) and stay unquoted: a double-quoted
    # name is a string literal in some SQL dialects behind the USL.
    parts = []
    for i, col in enumerate(columns):
        parts += [
            f"count(DISTINCT {col}) AS d{i}",
            f"min(length({col})) AS s{i}",
            f"max(length({col})) AS l{i}",
            f"sum(CASE WHEN {col} <> lower({col}) THEN 1 ELSE 0 END) AS u{i}",
            f"sum(CASE WHEN {col} <> upper({col}) THEN 1 ELSE 0 END) AS w{i}",
        ]
    outcome = data.profile(f"SELECT {', '.join(parts)} FROM {fqn}", 1)
    if not isinstance(outcome, QueryResult) or not outcome.rows:
        return {}
    row = outcome.rows[0]
    hints: dict[str, Any] = {}
    for i, col in enumerate(columns):
        stats = {"distinct": _number(row.get(f"d{i}")), "min_len": row.get(f"s{i}"), "max_len": row.get(f"l{i}"),
                 "with_upper": row.get(f"u{i}"), "with_lower": row.get(f"w{i}")}
        if not stats["distinct"]:
            continue
        listed = stats["distinct"] <= MAX_LISTED_VALUES
        top = data.profile(
            f"SELECT {col} AS v, count(*) AS n FROM {fqn} WHERE {col} IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {PROFILE_ROW_LIMIT if listed else MAX_EXAMPLES}",
            PROFILE_ROW_LIMIT,
        )
        if not isinstance(top, QueryResult):
            continue
        values = [_clip(r.get("v")) for r in top.rows if r.get("v") is not None]
        form = _format(stats, values)
        if listed and not form.endswith("hex id"):
            hints[col] = values
        else:
            hints[col] = _summary(stats["distinct"], form, values)
    return hints


def _summary(distinct: int, form: str, examples: list[str]) -> str:
    shown = ", ".join(f"'{e}'" for e in examples[:MAX_EXAMPLES])
    return f"{distinct} distinct, {form}, e.g. {shown}"


def _size(hints: Hints) -> int:
    return len(json.dumps(hints, ensure_ascii=False, separators=(",", ":")))


def cap(hints: Hints, max_chars: int = MAX_HINT_CHARS) -> Hints:
    """Fit the hints in `max_chars` of JSON: summarise the longest lists first, then drop trailing columns."""
    hints = {table: dict(cols) for table, cols in hints.items()}
    lists = sorted(
        ((table, col) for table, cols in hints.items() for col, v in cols.items() if isinstance(v, list)),
        key=lambda tc: (-len(json.dumps(hints[tc[0]][tc[1]], ensure_ascii=False)), tc),
    )
    for table, col in lists:
        if _size(hints) <= max_chars:
            break
        values = hints[table][col]
        hints[table][col] = _summary(len(values), "listed values", values)
    for table in reversed(list(hints)):
        for col in reversed(list(hints[table])):
            if _size(hints) <= max_chars:
                return hints
            del hints[table][col]
        if not hints[table]:
            del hints[table]
    return hints


def build_value_hints(data: DataLayer, schemas: list[dict[str, Any]]) -> Hints:
    """Profile every text column of the tables in `schemas` (the `AgentContext.source_schemas` form)."""
    hints: Hints = {}
    for source in schemas:
        for table in source["tables"]:
            fqn = table["table"]
            columns = [c.split(" ", 1)[0] for c in table["columns"]
                       if " " in c and is_text(c.split(" ", 1)[1]) and _IDENT_RE.match(c.split(" ", 1)[0])]
            if columns and all(_IDENT_RE.match(part) for part in fqn.split(".")):
                found = _profile_table(data, fqn, columns)
                if found:
                    hints[fqn] = found
    return cap(hints)


def value_hints(data: DataLayer, schemas: list[dict[str, Any]]) -> Hints:
    """The hints for `data`, built once per process for the same adapter and schema."""
    key = (getattr(data, "adapter_name", type(data).__name__),
           json.dumps(schemas, sort_keys=True, default=str))
    with _memo_lock:
        cached = _memo.get(key)
    if cached is not None:
        return cached
    built = build_value_hints(data, schemas)
    if not built:  # nothing could be profiled (e.g. the source was down): try again next time
        return built
    with _memo_lock:
        _memo.setdefault(key, built)
        return _memo[key]


def clear_cache() -> None:
    """Forget the hints built so far (tests)."""
    with _memo_lock:
        _memo.clear()

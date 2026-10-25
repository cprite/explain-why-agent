"""The data-layer interface shared by every adapter (Zetaris over REST, local DuckDB).

Agents only see this interface: they list sources, read schemas and run read-only SQL. A query
never raises to the caller; it returns either a `QueryResult` or a `QueryError`, and both carry the
query id that evidence items point to.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self


@dataclass(frozen=True)
class ColumnInfo:
    """One column of a table: name and the adapter's type name."""

    name: str
    type: str


@dataclass(frozen=True)
class TableInfo:
    """One table of a source with its columns and row count."""

    name: str
    row_count: int
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass(frozen=True)
class SourceInfo:
    """Description of one source: its tables, as returned by `DataLayer.describe`."""

    name: str
    tables: list[TableInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form, safe to serialise to JSON or pass to a prompt."""
        return asdict(self)


@dataclass(frozen=True)
class QueryResult:
    """Rows returned by an accepted query."""

    query_id: str
    source: str | None
    sql: str
    adapter: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    duration_ms: float
    ok: bool = True
    # True when sample mode served the rows recorded in the live run instead of this run's rows.
    replayed: bool = False
    # Set when the adapter could not answer and another one did (Zetaris -> local): why.
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form, safe to serialise to JSON."""
        return asdict(self)


@dataclass(frozen=True)
class QueryError:
    """A query that was rejected by the guard, timed out or failed in the engine.

    `code` is one of `rejected`, `timeout`, `unknown_source` or `failed`.
    """

    query_id: str
    source: str | None
    sql: str
    adapter: str
    code: str
    message: str
    duration_ms: float = 0.0
    ok: bool = False
    # Set when the statement failed on the fallback adapter: why the primary one was not used.
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form, safe to serialise to JSON."""
        return asdict(self)


QueryOutcome = QueryResult | QueryError


class DataLayer(ABC):
    """Read-only access to the business data sources."""

    adapter_name: str = "abstract"

    @abstractmethod
    def list_sources(self) -> list[str]:
        """Return the names of the available sources."""

    @abstractmethod
    def describe(self, source: str) -> SourceInfo:
        """Return tables, columns with types and row counts for one source.

        Raises `KeyError` for an unknown source.
        """

    @abstractmethod
    def query(
        self,
        source: str | None,
        sql: str,
        limit: int | None = None,
        timeout: float | None = None,
    ) -> QueryOutcome:
        """Run one read-only statement and return rows or a structured error.

        `source=None` allows a cross-source statement whose tables are qualified as
        `<source>.<table>`. `limit` caps the rows returned (the result says if it was truncated);
        `timeout` is in seconds. Defaults come from the adapter's settings.
        """

    def profile(self, sql: str, limit: int) -> QueryOutcome:
        """Run one read-only statement to profile the data (value hints), not as part of a run.

        Adapters override it so that profiling takes no query id from the run's sequence and writes
        nothing to the run's query log. Default: a cross-source `query`.
        """
        return self.query(None, sql, limit)

    def close(self) -> None:
        """Release the adapter's resources (database file, HTTP client). Default: nothing to release."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class QueryLog:
    """Append-only JSONL log of every query: `logs/queries-<run_id>.jsonl` (architecture §8)."""

    def __init__(self, log_dir: Path, run_id: str) -> None:
        self.path = Path(log_dir) / f"queries-{run_id}.jsonl"
        self.run_id = run_id

    def write(self, outcome: QueryOutcome, extra: dict[str, Any] | None = None) -> None:
        """Append one line for an accepted, rejected or failed query.

        `extra` adds adapter-specific fields (the Zetaris adapter adds `usl_tables` and, after a
        fallback, `fallback_reason`).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "query_id": outcome.query_id,
            "source": outcome.source,
            "sql": outcome.sql,
            "adapter": outcome.adapter,
            "duration_ms": round(outcome.duration_ms, 2),
            "row_count": outcome.row_count if isinstance(outcome, QueryResult) else 0,
            "truncated": outcome.truncated if isinstance(outcome, QueryResult) else False,
            "status": "ok" if isinstance(outcome, QueryResult) else outcome.code,
            "error": None if isinstance(outcome, QueryResult) else outcome.message,
            **(extra or {}),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    def read(self) -> list[dict[str, Any]]:
        """Read the log back (used by tests and by the result's evidence check)."""
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


def elapsed_ms(started: float) -> float:
    """Milliseconds since a `time.perf_counter()` reading."""
    return (time.perf_counter() - started) * 1000.0

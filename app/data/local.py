"""Local data adapter: the sample CSVs in one DuckDB database, one schema per source.

Used in sample mode and as the fallback for the Zetaris adapter. Tables are addressed as
`<source>.<table>` (for example `orders.orders JOIN payments.order_payments`), so a cross-source
statement runs with `source=None`.

Three layers keep it read-only:
1. `check_read_only` rejects anything but a single SELECT / WITH ... SELECT before DuckDB sees it;
2. DuckDB's own parser must classify the statement as a SELECT;
3. the database is opened `read_only` with external file access disabled, so even a statement that
   slipped past the guard can neither write nor read files outside the loaded tables (the answer
   key in `eval/` is never loaded and cannot be read with `read_json`).
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import time
import weakref
from dataclasses import replace
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

import duckdb

from app.config import Settings, get_settings, resolve_path
from app.data.layer import (
    ColumnInfo,
    DataLayer,
    QueryError,
    QueryLog,
    QueryOutcome,
    QueryResult,
    SourceInfo,
    TableInfo,
    elapsed_ms,
)

DEFAULT_SOURCES: tuple[str, ...] = ("orders", "payments", "reviews", "marketing")

FORBIDDEN_KEYWORDS: tuple[str, ...] = (
    "insert",
    "update",
    "delete",
    "merge",
    "create",
    "drop",
    "alter",
    "truncate",
    "copy",
    "attach",
    "detach",
    "pragma",
    "install",
    "load",
    "export",
    "import",
    "set",
    "reset",
    "call",
    "checkpoint",
    "vacuum",
    "begin",
    "commit",
    "rollback",
    "grant",
    "revoke",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)
_FILE_FUNCTION_RE = re.compile(
    r"\b(read_\w+|glob|parquet_\w+|sniff_csv|duckdb_\w+)\s*\(", re.IGNORECASE
)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GuardError(ValueError):
    """Raised by `check_read_only` with a message suitable for the caller."""


def _strip_literals_and_comments(sql: str) -> str:
    """Blank out string literals, quoted identifiers and comments so keywords inside them are ignored."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        elif ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # doubled quote escape
                        j += 2
                        continue
                    break
                j += 1
            out.append(" '' " if ch == "'" else ' "_" ')
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def check_read_only(sql: str) -> str:
    """Return the statement without trailing semicolons, or raise `GuardError`.

    Accepts exactly one SELECT or WITH ... SELECT statement. Rejects empty input, multiple
    statements, any write/DDL/session keyword (INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, COPY,
    ATTACH, PRAGMA, INSTALL, LOAD, SET, ...) and file-reading table functions.
    """
    if not sql or not sql.strip():
        raise GuardError("empty statement")
    body = sql.strip()
    while body.endswith(";"):
        body = body[:-1].rstrip()
    scrubbed = _strip_literals_and_comments(body)
    if ";" in scrubbed:
        raise GuardError("multiple statements are not allowed; send one SELECT")
    words = scrubbed.lstrip("( \t\r\n").split(None, 1)
    first = words[0].lower() if words else ""
    if first not in ("select", "with"):
        raise GuardError(f"only SELECT or WITH ... SELECT is allowed, got {first.upper() or 'nothing'}")
    forbidden = _FORBIDDEN_RE.search(scrubbed)
    if forbidden:
        raise GuardError(f"keyword {forbidden.group(1).upper()} is not allowed in a read-only query")
    file_fn = _FILE_FUNCTION_RE.search(scrubbed)
    if file_fn:
        raise GuardError(f"function {file_fn.group(1)} is not allowed; query the loaded tables")
    return body


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


class LocalDataLayer(DataLayer):
    """DuckDB-backed `DataLayer` over `data/sample/<source>/*.csv`."""

    adapter_name = "local"

    def __init__(
        self,
        sample_dir: Path | str | None = None,
        *,
        run_id: str = "adhoc",
        log_dir: Path | str | None = None,
        max_rows: int | None = None,
        timeout_seconds: float | None = None,
        sources: tuple[str, ...] = DEFAULT_SOURCES,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.sample_dir = Path(sample_dir) if sample_dir else resolve_path(settings.sample_data_dir)
        self.max_rows = max_rows if max_rows is not None else settings.max_query_rows
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else float(settings.query_timeout_seconds)
        )
        self.log = QueryLog(Path(log_dir) if log_dir else resolve_path(settings.log_dir), run_id)
        self._counter = 0
        self._counter_lock = threading.Lock()
        self._sample_mode = settings.sample_mode
        self._record = settings.record_cache and not settings.sample_mode
        self._query_cache = resolve_path(settings.query_cache_dir)
        self._tables: dict[str, list[str]] = {}
        self._active: set[duckdb.DuckDBPyConnection] = set()
        self._active_lock = threading.Lock()

        work_dir = resolve_path(settings.duckdb_work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(prefix="ewa-duckdb-", dir=work_dir)
        db_path = Path(self._tmp.name) / "sample.duckdb"
        self._limits = {
            "memory_limit": settings.duckdb_memory_limit,
            "threads": settings.duckdb_threads,
            "temp_directory": str(Path(self._tmp.name) / "spill"),
        }
        self._build(db_path, sources)
        self._con = duckdb.connect(
            str(db_path),
            read_only=True,
            config={"enable_external_access": False, **self._limits},
        )
        self._finalizer = weakref.finalize(self, _cleanup, self._con, self._tmp)

    def _build(self, db_path: Path, sources: tuple[str, ...]) -> None:
        """Load every CSV of every source into its schema, then close the writable connection."""
        con = duckdb.connect(str(db_path), config=self._limits)
        try:
            for source in sources:
                folder = self.sample_dir / source
                if not _IDENT_RE.match(source) or not folder.is_dir():
                    continue
                csvs = sorted(folder.glob("*.csv"))
                if not csvs:
                    continue
                con.execute(f'CREATE SCHEMA "{source}"')
                self._tables[source] = []
                for csv_path in csvs:
                    table = csv_path.stem
                    if not _IDENT_RE.match(table):
                        continue
                    con.execute(
                        f'CREATE TABLE "{source}"."{table}" AS '
                        "SELECT * FROM read_csv(?, header = true)",
                        [str(csv_path)],
                    )
                    self._tables[source].append(table)
            con.execute("CHECKPOINT")
        finally:
            con.close()

    def close(self) -> None:
        """Close the database and remove its temporary file.

        Statements still running on another thread are interrupted first (for up to
        `CLOSE_RETRY_SECONDS`), so the connection is free to close: DuckDB refuses to close a
        connection that is busy with another call.
        """
        give_up = time.monotonic() + CLOSE_RETRY_SECONDS
        while self._active and time.monotonic() < give_up:
            self.interrupt()  # again each time: an interrupt sent before a statement starts is lost
            time.sleep(0.01)
        self._finalizer()

    def interrupt(self) -> None:
        """Interrupt every statement running now (a query or a schema read); the layer stays usable."""
        with self._active_lock:
            active = list(self._active)
        for cur in active:
            try:
                cur.interrupt()
            except duckdb.Error:
                pass

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        cur = self._con.cursor()
        with self._active_lock:
            self._active.add(cur)
        return cur

    def _release(self, cur: duckdb.DuckDBPyConnection) -> None:
        with self._active_lock:
            self._active.discard(cur)
        cur.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_sources(self) -> list[str]:
        """Return the loaded sources in load order."""
        return list(self._tables)

    def describe(self, source: str) -> SourceInfo:
        """Return tables, columns with DuckDB types and exact row counts for one source."""
        if source not in self._tables:
            raise KeyError(f"unknown source {source!r}; available: {', '.join(self._tables)}")
        cur = self._cursor()
        try:
            tables = []
            for table in self._tables[source]:
                cols = cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                    [source, table],
                ).fetchall()
                (count,) = cur.execute(f'SELECT count(*) FROM "{source}"."{table}"').fetchone()
                tables.append(
                    TableInfo(
                        name=table,
                        row_count=int(count),
                        columns=[ColumnInfo(name=c, type=t) for c, t in cols],
                    )
                )
            return SourceInfo(name=source, tables=tables)
        finally:
            self._release(cur)

    def _next_query_id(self) -> str:
        # Deterministic within a run (q001, q002, ...) so the same investigation produces the same
        # prompts, which keeps the sample-mode model cache stable across runs.
        with self._counter_lock:
            self._counter += 1
            return f"q{self._counter:03d}"

    def query(
        self,
        source: str | None,
        sql: str,
        limit: int | None = None,
        timeout: float | None = None,
    ) -> QueryOutcome:
        """Run one read-only statement; see `DataLayer.query`. Every call is logged."""
        outcome = self._run(source, sql, limit, timeout)
        if isinstance(outcome, QueryResult):
            outcome = self._replay_or_record(outcome, limit)
        self.log.write(outcome)
        return outcome

    def _cache_path(self, source: str | None, sql: str, limit: int | None) -> Path:
        key = json.dumps({"source": source, "sql": " ".join(sql.split()), "limit": limit}, sort_keys=True)
        return self._query_cache / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def _replay_or_record(self, result: QueryResult, limit: int | None) -> QueryResult:
        """Record the rows in a live recording run; serve the recorded rows in sample mode.

        The query always runs for real (guard, timeout and errors apply). Only the returned rows are
        swapped, so the model sees exactly what it saw when its replies were recorded.
        """
        path = self._cache_path(result.source, result.sql, limit)
        if self._record:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "source": result.source, "sql": result.sql, "limit": limit,
                "columns": result.columns, "rows": result.rows, "truncated": result.truncated,
            }, indent=1, sort_keys=True) + "\n")
            return result
        if self._sample_mode and path.is_file():
            recorded = json.loads(path.read_text())
            return replace(
                result, columns=recorded["columns"], rows=recorded["rows"],
                row_count=len(recorded["rows"]), truncated=recorded["truncated"], replayed=True,
            )
        return result

    def _run(
        self, source: str | None, sql: str, limit: int | None, timeout: float | None
    ) -> QueryOutcome:
        query_id = self._next_query_id()
        limit = self.max_rows if limit is None else max(1, min(int(limit), self.max_rows))
        timeout = self.timeout_seconds if timeout is None else float(timeout)
        started = time.perf_counter()

        def error(code: str, message: str) -> QueryError:
            return QueryError(
                query_id=query_id,
                source=source,
                sql=sql,
                adapter=self.adapter_name,
                code=code,
                message=message,
                duration_ms=elapsed_ms(started),
            )

        if source is not None and source not in self._tables:
            return error("unknown_source", f"unknown source {source!r}; available: {', '.join(self._tables)}")
        try:
            body = check_read_only(sql)
        except GuardError as exc:
            return error("rejected", str(exc))

        cur = self._cursor()
        timed_out = threading.Event()

        def interrupt() -> None:
            timed_out.set()
            cur.interrupt()

        timer = threading.Timer(timeout, interrupt)
        try:
            statements = cur.extract_statements(body)
            if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                return error("rejected", "only a single SELECT statement is allowed")
            if source is not None:
                cur.execute(f"SET search_path = '{source}'")
            timer.start()
            relation = cur.execute(f"SELECT * FROM ({body}\n) AS _q LIMIT {limit + 1}")
            columns = [d[0] for d in relation.description or []]
            raw = relation.fetchall()
        except duckdb.InterruptException:
            if not timed_out.is_set():  # interrupted by `interrupt()` / `close()`, not by the timer
                return error("cancelled", "the query was interrupted because the run was stopped")
            return error("timeout", f"query exceeded the {timeout:g} s timeout and was interrupted")
        except duckdb.Error as exc:
            if timed_out.is_set():
                return error("timeout", f"query exceeded the {timeout:g} s timeout and was interrupted")
            return error("failed", f"{type(exc).__name__}: {exc}")
        finally:
            timer.cancel()
            self._release(cur)

        truncated = len(raw) > limit
        rows = [
            {col: _jsonable(val) for col, val in zip(columns, row, strict=False)} for row in raw[:limit]
        ]
        return QueryResult(
            query_id=query_id,
            source=source,
            sql=sql,
            adapter=self.adapter_name,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=elapsed_ms(started),
        )


CLOSE_RETRY_SECONDS = 2.0
"""How long `close` keeps retrying a connection that an interrupted statement still holds."""


def _cleanup(con: duckdb.DuckDBPyConnection, tmp: tempfile.TemporaryDirectory) -> None:
    try:
        give_up = time.monotonic() + CLOSE_RETRY_SECONDS
        while True:
            try:
                con.close()
                break
            except duckdb.Error:
                # An interrupted statement on another thread can hold the connection for a moment.
                if time.monotonic() >= give_up:
                    raise
                time.sleep(0.02)
    finally:
        tmp.cleanup()

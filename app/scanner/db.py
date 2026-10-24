"""Scanner data access: one read-only DuckDB connection over the CSVs in data/sample/.

Everything the scanner reads goes through `run_sql(sql) -> rows`, so a later sprint can point it at
the DataLayer / Zetaris adapter instead. The CSVs are loaded once into a database file under
.cache/duckdb (one table per CSV, named after the file stem), which is then reopened read-only with
external access disabled. DuckDB is held to 1GB of memory and two threads, and spills to an on-disk
temp directory under .cache/duckdb rather than /tmp (RAM-backed on the build machine).
"""

from __future__ import annotations

import atexit
import os
import threading
from pathlib import Path
from typing import Any

import duckdb

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "sample"
CACHE_DIR = ROOT / ".cache" / "duckdb"

MEMORY_LIMIT = "1GB"
THREADS = 2

Row = dict[str, Any]


class QueryTimeout(RuntimeError):
    """A query ran past its timeout and was interrupted."""


def duckdb_config(cache_dir: Path) -> dict[str, Any]:
    return {
        "memory_limit": MEMORY_LIMIT,
        "threads": THREADS,
        "temp_directory": str(cache_dir / "tmp"),
    }


class SampleDatabase:
    """Read-only DuckDB over the sample CSVs."""

    def __init__(self, data_dir: Path = DATA_DIR, cache_dir: Path = CACHE_DIR) -> None:
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.path = cache_dir / f"scanner-{os.getpid()}-{id(self)}.duckdb"
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    def _build(self) -> None:
        (self.cache_dir / "tmp").mkdir(parents=True, exist_ok=True)
        self._remove_file()
        csv_files = sorted(self.data_dir.glob("*/*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"no CSV files under {self.data_dir}")
        build = duckdb.connect(str(self.path), config=duckdb_config(self.cache_dir))
        try:
            for csv_path in csv_files:
                source = str(csv_path).replace("'", "''")
                build.execute(
                    f'CREATE TABLE "{csv_path.stem}" AS SELECT * FROM read_csv(\'{source}\', header = true)'
                )
        finally:
            build.close()

    def connection(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                self._build()
                conn = duckdb.connect(str(self.path), read_only=True, config=duckdb_config(self.cache_dir))
                # Set after connecting: with it in the connect config DuckDB refuses temp_directory.
                conn.execute("SET enable_external_access = false")
                self._conn = conn
            return self._conn

    def run_sql(self, sql: str, timeout_s: float | None = None) -> list[Row]:
        """Run one query and return its rows as dicts; interrupted after `timeout_s` seconds."""
        if timeout_s is None:
            timeout_s = float(get_settings().query_timeout_seconds)
        cursor = self.connection().cursor()
        timer = threading.Timer(max(timeout_s, 0.001), cursor.interrupt)
        timer.start()
        try:
            result = cursor.execute(sql)
            columns = [d[0] for d in result.description or []]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        except duckdb.InterruptException as exc:
            raise QueryTimeout(f"query exceeded {timeout_s:.1f}s") from exc
        finally:
            timer.cancel()
            cursor.close()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            self._remove_file()

    def _remove_file(self) -> None:
        for candidate in (self.path, self.path.with_name(self.path.name + ".wal")):
            candidate.unlink(missing_ok=True)


_default: SampleDatabase | None = None
_default_lock = threading.Lock()


def default_database() -> SampleDatabase:
    global _default
    with _default_lock:
        if _default is None:
            _default = SampleDatabase()
            atexit.register(_default.close)
        return _default


def run_sql(sql: str, timeout_s: float | None = None) -> list[Row]:
    """The scanner's single data-access function."""
    return default_database().run_sql(sql, timeout_s=timeout_s)

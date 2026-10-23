"""Tests for the local DuckDB data adapter (app/data/local.py)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from app.config import Settings
from app.data.layer import DataLayer, QueryError, QueryResult
from app.data.local import GuardError, LocalDataLayer, check_read_only

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_README = ROOT / "data" / "sample" / "README.md"

CROSS_SOURCE_SQL = (
    "SELECT strftime(o.order_purchase_timestamp, '%Y-%m') AS month, "
    "count(DISTINCT o.order_id) AS orders, sum(p.payment_value) AS payment_value "
    "FROM orders.orders o JOIN payments.order_payments p ON p.order_id = o.order_id "
    "GROUP BY 1 ORDER BY 1"
)
SLOW_SQL = "SELECT sum(a.range * b.range) AS s FROM range(200000) a, range(200000) b"


@pytest.fixture(scope="module")
def layer(tmp_path_factory: pytest.TempPathFactory) -> LocalDataLayer:
    log_dir = tmp_path_factory.mktemp("logs")
    with LocalDataLayer(run_id="test-local", log_dir=log_dir) as data_layer:
        yield data_layer


def _readme_row_counts() -> dict[tuple[str, str], int]:
    counts = {}
    for match in re.finditer(r"^\| `(\w+)/(\w+)\.csv` \| (\d+) \|$", SAMPLE_README.read_text(), re.MULTILINE):
        counts[(match.group(1), match.group(2))] = int(match.group(3))
    return counts


def test_local_layer_implements_interface(layer: LocalDataLayer) -> None:
    assert isinstance(layer, DataLayer)
    assert layer.list_sources() == ["orders", "payments", "reviews", "marketing"]


def test_describe_row_counts_match_sample_readme(layer: LocalDataLayer) -> None:
    expected = _readme_row_counts()
    assert len(expected) == 11
    actual = {}
    for source in layer.list_sources():
        info = layer.describe(source)
        assert info.name == source
        for table in info.tables:
            assert table.columns, f"{source}.{table.name} has no columns"
            assert all(col.name and col.type for col in table.columns)
            actual[(source, table.name)] = table.row_count
    assert actual == expected


def test_describe_reports_column_types(layer: LocalDataLayer) -> None:
    orders = {t.name: t for t in layer.describe("orders").tables}["orders"]
    types = {c.name: c.type for c in orders.columns}
    assert types["order_id"] == "VARCHAR"
    assert types["order_purchase_timestamp"] == "TIMESTAMP"


def test_describe_unknown_source_raises_key_error(layer: LocalDataLayer) -> None:
    with pytest.raises(KeyError):
        layer.describe("eval")


def test_cross_source_join_returns_rows(layer: LocalDataLayer) -> None:
    result = layer.query(None, CROSS_SOURCE_SQL)
    assert isinstance(result, QueryResult), result
    assert result.row_count > 10
    assert result.columns == ["month", "orders", "payment_value"]
    assert result.query_id
    assert result.adapter == "local"
    assert not result.truncated


def test_source_scoped_query_resolves_unqualified_tables(layer: LocalDataLayer) -> None:
    result = layer.query("payments", "SELECT count(*) AS n FROM order_payments")
    assert isinstance(result, QueryResult), result
    assert result.rows == [{"n": 31560}]


def test_unknown_source_is_structured_error(layer: LocalDataLayer) -> None:
    result = layer.query("eval", "SELECT 1")
    assert isinstance(result, QueryError)
    assert result.code == "unknown_source"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders.orders SELECT * FROM orders.orders",
        "UPDATE orders.orders SET order_status = 'x'",
        "DELETE FROM orders.orders",
        "CREATE TABLE t AS SELECT 1",
        "DROP TABLE orders.orders",
        "ALTER TABLE orders.orders ADD COLUMN x INT",
        "COPY orders.orders TO '/tmp/out.csv'",
        "ATTACH '/tmp/other.duckdb' AS other",
        "PRAGMA database_list",
        "INSTALL httpfs",
        "LOAD httpfs",
        "SET threads = 1",
        "SELECT 1; DELETE FROM orders.orders",
        "SELECT 1; SELECT 2",
        "WITH x AS (SELECT 1) DELETE FROM orders.orders",
        "/* hi */ DROP TABLE orders.orders",
        "",
    ],
)
def test_guard_rejects_non_select(layer: LocalDataLayer, sql: str) -> None:
    with pytest.raises(GuardError):
        check_read_only(sql)
    result = layer.query(None, sql)
    assert isinstance(result, QueryError)
    assert result.code == "rejected"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select 1;",
        "  WITH t AS (SELECT 1 AS a) SELECT a FROM t  ",
        "SELECT 'DELETE FROM x; DROP' AS label",
        "SELECT 1 -- DROP TABLE x\n",
        "SELECT count(*) AS update_count FROM orders.orders",
    ],
)
def test_guard_accepts_single_select(layer: LocalDataLayer, sql: str) -> None:
    check_read_only(sql)
    result = layer.query(None, sql)
    assert isinstance(result, QueryResult), result


def test_connection_is_read_only_even_without_guard(layer: LocalDataLayer) -> None:
    cur = layer._con.cursor()
    try:
        with pytest.raises(duckdb.Error):
            cur.execute("DELETE FROM orders.orders")
        with pytest.raises(duckdb.Error):
            cur.execute("CREATE TABLE orders.x AS SELECT 1")
    finally:
        cur.close()
    assert layer.describe("orders").tables[3].row_count == 30256


def test_row_limit_truncates(layer: LocalDataLayer) -> None:
    result = layer.query("orders", "SELECT order_id FROM orders ORDER BY order_id", limit=10)
    assert isinstance(result, QueryResult)
    assert result.row_count == 10
    assert result.truncated is True
    exact = layer.query("orders", "SELECT order_id FROM orders ORDER BY order_id LIMIT 10", limit=10)
    assert exact.row_count == 10 and exact.truncated is False


def test_row_limit_and_timeout_come_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAX_QUERY_ROWS", "3")
    monkeypatch.setenv("QUERY_TIMEOUT_SECONDS", "1")
    with LocalDataLayer(run_id="env", log_dir=tmp_path, sources=("payments",)) as small:
        assert small.max_rows == 3
        assert small.timeout_seconds == 1.0
        result = small.query("payments", "SELECT * FROM order_payments")
        assert isinstance(result, QueryResult)
        assert result.row_count == 3 and result.truncated
        # A caller cannot raise the limit above the configured cap.
        assert small.query("payments", "SELECT * FROM order_payments", limit=100).row_count == 3


def test_safe_defaults_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_QUERY_ROWS", raising=False)
    monkeypatch.delenv("QUERY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DUCKDB_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("DUCKDB_THREADS", raising=False)
    settings = Settings()
    assert settings.max_query_rows == 5000
    assert settings.query_timeout_seconds == 30
    assert settings.duckdb_memory_limit == "2GB"
    assert settings.duckdb_threads == 1


def test_duckdb_resource_caps_are_applied(layer: LocalDataLayer) -> None:
    con = layer._con
    (threads,) = con.execute("SELECT current_setting('threads')").fetchone()
    (memory,) = con.execute("SELECT current_setting('memory_limit')").fetchone()
    (temp_dir,) = con.execute("SELECT current_setting('temp_directory')").fetchone()
    assert int(threads) == 1
    assert memory.endswith("GiB") and float(memory.split()[0]) <= 2.0
    assert Path(temp_dir).is_relative_to(ROOT / ".cache" / "duckdb")


def test_duckdb_caps_come_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "256MB")
    monkeypatch.setenv("DUCKDB_THREADS", "1")
    monkeypatch.setenv("DUCKDB_WORK_DIR", str(tmp_path / "work"))
    with LocalDataLayer(run_id="caps", log_dir=tmp_path, sources=("payments",)) as small:
        (threads,) = small._con.execute("SELECT current_setting('threads')").fetchone()
        (memory,) = small._con.execute("SELECT current_setting('memory_limit')").fetchone()
        assert int(threads) == 1
        assert memory.endswith("MiB")
        assert Path(small._tmp.name).parent == tmp_path / "work"


def test_timeout_interrupts_slow_query(layer: LocalDataLayer) -> None:
    result = layer.query(None, SLOW_SQL, timeout=1)
    assert isinstance(result, QueryError), result
    assert result.code == "timeout"
    assert result.duration_ms < 10_000
    # The connection is still usable afterwards.
    assert isinstance(layer.query(None, "SELECT 1 AS one"), QueryResult)


def test_answer_key_is_not_queryable(layer: LocalDataLayer) -> None:
    every_table = layer.query(
        None, "SELECT table_schema, table_name FROM information_schema.tables"
    )
    assert isinstance(every_table, QueryResult)
    names = {(r["table_schema"], r["table_name"]) for r in every_table.rows}
    assert not any("answer" in schema or "answer" in table for schema, table in names)
    assert "eval" not in layer.list_sources()
    for sql in (
        "SELECT * FROM read_json_auto('eval/answer_key.json')",
        "SELECT * FROM 'eval/answer_key.json'",
        f"SELECT * FROM '{ROOT / 'eval' / 'answer_key.json'}'",
    ):
        result = layer.query(None, sql)
        assert isinstance(result, QueryError), sql
        assert result.code in ("rejected", "failed")


def test_query_log_records_every_query(tmp_path: Path) -> None:
    with LocalDataLayer(run_id="logcheck", log_dir=tmp_path, sources=("payments",)) as small:
        ok = small.query("payments", "SELECT count(*) AS n FROM order_payments")
        rejected = small.query(None, "DROP TABLE payments.order_payments")
        failed = small.query(None, "SELECT no_such_column FROM payments.order_payments")
        lines = small.log.read()
    assert small.log.path == tmp_path / "queries-logcheck.jsonl"
    assert [line["query_id"] for line in lines] == [ok.query_id, rejected.query_id, failed.query_id]
    assert [line["status"] for line in lines] == ["ok", "rejected", "failed"]
    for line in lines:
        for key in ("query_id", "source", "sql", "adapter", "duration_ms", "row_count", "status", "error"):
            assert key in line
        assert line["adapter"] == "local"
    assert lines[0]["row_count"] == 1 and lines[0]["error"] is None
    assert lines[1]["sql"] == "DROP TABLE payments.order_payments"
    assert "no_such_column" in lines[2]["error"]


def test_plan_check_script_prints_both_results() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.data.check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] cross-source join" in result.stdout
    assert "[PASS] write statement rejected" in result.stdout


# --- recorded query results for sample-mode replay -----------------------------------------------

TIE_SQL = "SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 ORDER BY n"


def _layer(tmp_path: Path, **overrides: object) -> LocalDataLayer:
    settings = Settings(
        log_dir=str(tmp_path / "logs"), query_cache_dir=str(tmp_path / "qcache"), **overrides
    )
    return LocalDataLayer(run_id="qcache", log_dir=tmp_path / "logs", sources=("orders",), settings=settings)


def test_recording_run_writes_query_results(tmp_path: Path) -> None:
    with _layer(tmp_path, sample_mode=False, record_cache=True) as data:
        result = data.query(None, TIE_SQL)
    assert isinstance(result, QueryResult) and result.replayed is False
    files = list((tmp_path / "qcache").glob("*.json"))
    assert len(files) == 1
    assert '"rows"' in files[0].read_text()


def test_sample_mode_serves_recorded_rows_after_running_the_query(tmp_path: Path) -> None:
    with _layer(tmp_path, sample_mode=False, record_cache=True) as data:
        data.query(None, TIE_SQL)
    [path] = list((tmp_path / "qcache").glob("*.json"))
    recorded = path.read_text().replace('"n": 1', '"n": 9')  # stand-in for another platform's tie order
    path.write_text(recorded)
    with _layer(tmp_path, sample_mode=True) as data:
        result = data.query(None, TIE_SQL)
        rejected = data.query(None, "DELETE FROM orders.orders")
    assert isinstance(result, QueryResult) and result.replayed is True
    assert [row["n"] for row in result.rows] == [9, 2, 3]
    assert isinstance(rejected, QueryError) and rejected.code == "rejected"  # the guard still applies


def test_without_a_recording_sample_mode_returns_real_rows(tmp_path: Path) -> None:
    with _layer(tmp_path, sample_mode=True) as data:
        result = data.query(None, TIE_SQL)
    assert isinstance(result, QueryResult) and result.replayed is False
    assert [row["n"] for row in result.rows] == [1, 2, 3]
    assert not (tmp_path / "qcache").exists()

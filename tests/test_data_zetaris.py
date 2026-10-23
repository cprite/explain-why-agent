"""Tests for the Zetaris adapter (app/data/zetaris.py) and the data-layer factory, with no network.

Every REST exchange goes through an `httpx.MockTransport`; nothing here can reach a Zetaris server.
"""

from __future__ import annotations

import base64
import inspect
import json
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.data.factory import make_data_layer
from app.data.layer import DataLayer, QueryError, QueryResult
from app.data.local import LocalDataLayer
from app.data.usl import USL_PATH
from app.data.zetaris import (
    FALLBACK_ADAPTER,
    ZetarisClient,
    ZetarisDataLayer,
    convert_value,
    infer_family,
    parse_rest_body,
    to_usl_sql,
    type_family,
)

ROOT = Path(__file__).resolve().parents[1]
URL = "http://zetaris.invalid:8888/api/v1.0"
KEY = "zk-test-key-0123456789abcdef"
TOKEN = "id-token-from-login-abcdef"
PASSWORD = "login-pw-Secret1!"

Handler = Callable[[httpx.Request], httpx.Response]


def ok(headers: list, data: list[list]) -> httpx.Response:
    return httpx.Response(200, json={"headers": headers, "data": data, "total": len(data), "timeUsed": 5})


def settings(tmp_path: Path, **overrides: object) -> Settings:
    base = {
        "sample_mode": False,
        "zetaris_url": URL,
        "zetaris_api_key": KEY,
        "zetaris_org_id": "1",
        "log_dir": str(tmp_path / "logs"),
        "query_cache_dir": str(tmp_path / "qcache"),
        "zetaris_retry_delay_seconds": 0.0,
    }
    base.update(overrides)
    return Settings(**base)


def layer(tmp_path: Path, handler: Handler, *, calls: list | None = None, **overrides: object) -> ZetarisDataLayer:
    """A Zetaris layer whose REST calls go to `handler`; fallback uses a small local layer."""
    cfg = settings(tmp_path, **overrides)

    def recorded(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    client = ZetarisClient.from_settings(cfg, transport=httpx.MockTransport(recorded))
    return ZetarisDataLayer(
        run_id="zt", log_dir=tmp_path / "logs", settings=cfg, client=client,
        local_factory=lambda: LocalDataLayer(run_id="zt", log_dir=tmp_path / "logs",
                                             sources=("orders", "payments"), settings=cfg),
    )


def sql_of(request: httpx.Request) -> str:
    return json.loads(request.content)["sql"]


# --- interface and selection ------------------------------------------------------------------------


def test_zetaris_layer_has_the_local_layer_signatures(tmp_path: Path) -> None:
    with layer(tmp_path, lambda r: ok(["n"], [["1"]])) as data:
        assert isinstance(data, DataLayer)
        assert data.list_sources() == ["orders", "payments", "reviews", "marketing"]
    for name in ("list_sources", "describe", "query"):
        assert inspect.signature(getattr(ZetarisDataLayer, name)) == inspect.signature(getattr(LocalDataLayer, name))


def test_factory_selects_by_data_layer_and_sample_mode(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    with make_data_layer("f", settings=settings(tmp_path, data_layer="zetaris")) as data:
        assert isinstance(data, ZetarisDataLayer)
    with make_data_layer("f", settings=settings(tmp_path, data_layer="local")) as data:
        assert isinstance(data, LocalDataLayer)
    with make_data_layer("f", settings=settings(tmp_path, data_layer="zetaris", sample_mode=True)) as data:
        assert isinstance(data, LocalDataLayer)
    with make_data_layer("f", settings=settings(tmp_path, zetaris_url="")) as data:
        assert isinstance(data, LocalDataLayer)
    assert "ZETARIS_URL is empty" in capsys.readouterr().err
    with pytest.raises(ValueError, match="DATA_LAYER"):
        make_data_layer("f", settings=settings(tmp_path, data_layer="jdbc"))
    with pytest.raises(ValueError, match="ZETARIS_ORG_ID"):
        make_data_layer("f", settings=settings(tmp_path, zetaris_org_id=""))
    with pytest.raises(ValueError, match="ZETARIS_API_KEY"):
        make_data_layer("f", settings=settings(tmp_path, zetaris_api_key=""))


def test_default_data_layer_is_zetaris(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_LAYER", raising=False)
    assert Settings().data_layer == "zetaris"


def test_zetaris_layer_refuses_sample_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample mode"):
        ZetarisDataLayer(settings=settings(tmp_path, sample_mode=True))


def test_sample_mode_run_never_touches_zetaris(tmp_path: Path) -> None:
    """With Zetaris configured but sample mode on, the Day 1 run uses local data only."""
    env = {
        "PATH": "/usr/bin:/bin", "SAMPLE_MODE": "true", "DATA_LAYER": "zetaris",
        "ZETARIS_URL": "http://127.0.0.1:9/api/v1.0", "ZETARIS_API_KEY": KEY, "ZETARIS_ORG_ID": "1",
        "LOG_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "run.py", "Why did order volume spike on 24 November 2017?", "--run-id", "zt-sample"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    lines = [json.loads(line) for line in (tmp_path / "queries-zt-sample.jsonl").read_text().splitlines()]
    assert lines and {line["adapter"] for line in lines} == {"local"}
    assert "fallback" not in result.stdout


# --- REST client --------------------------------------------------------------------------------------


def test_rest_call_sends_auth_org_request_id_and_timeout(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    with layer(tmp_path, lambda r: ok(["n"], [["30256"]]), calls=calls) as data:
        first = data.query(None, "SELECT COUNT(*) AS n FROM orders.orders")
        data.query(None, "SELECT COUNT(*) AS n FROM orders.orders", timeout=7)
    assert isinstance(first, QueryResult) and first.rows == [{"n": 30256}] and first.adapter == "zetaris"
    one, two = calls
    assert one.method == "POST" and str(one.url) == URL + "/sql-editor/sqls/run"
    assert one.headers["Authorization"] == f"Bearer {KEY}"
    assert one.headers["X-Org-ID"] == "1"
    request_ids = {uuid.UUID(c.headers["X-Request-ID"]) for c in calls}
    assert len(request_ids) == 2  # a fresh id per request
    body = json.loads(one.content)
    uuid.UUID(body["queryId"])
    assert body["sql"] == f"SELECT COUNT(*) AS n FROM {USL_PATH}.orders"
    assert body["limit"] == 5001 and body["source"] == "SqlEditor"
    assert one.extensions["timeout"]["read"] == 30.0
    assert one.extensions["timeout"]["connect"] == 10.0
    assert two.extensions["timeout"]["read"] == 7.0


def test_login_token_is_used_when_no_api_key(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            expected = base64.b64encode(f"admin@example.com:{PASSWORD}".encode()).decode()
            assert request.headers["Authorization"] == f"Basic {expected}"
            return httpx.Response(200, json={"idToken": TOKEN, "refreshToken": "r"})
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return ok(["one"], [["1"]])

    with layer(tmp_path, handler, calls=calls, zetaris_api_key="", zetaris_username="admin@example.com",
               zetaris_password=PASSWORD) as data:
        assert isinstance(data.query(None, "SELECT 1 AS one"), QueryResult)
        assert isinstance(data.query(None, "SELECT 1 AS one"), QueryResult)
    assert [c.method for c in calls] == ["GET", "POST", "POST"]  # one login, token reused


def test_refused_api_key_falls_back_to_login(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"idToken": TOKEN})
        if request.headers["Authorization"] == f"Bearer {KEY}":
            return httpx.Response(401, json={"msg": "invalid api key"})
        return ok(["one"], [["1"]])

    calls: list[httpx.Request] = []
    with layer(tmp_path, handler, calls=calls, zetaris_username="admin@example.com",
               zetaris_password=PASSWORD) as data:
        result = data.query(None, "SELECT 1 AS one")
        data.query(None, "SELECT 1 AS one")
    assert isinstance(result, QueryResult) and result.rows == [{"one": 1}] and result.adapter == "zetaris"
    # key refused once, login, resend; afterwards the session token goes first
    assert [(c.method, c.headers["Authorization"].split()[0]) for c in calls] == [
        ("POST", "Bearer"), ("GET", "Basic"), ("POST", "Bearer"), ("POST", "Bearer")]
    assert calls[-1].headers["Authorization"] == f"Bearer {TOKEN}"


def test_refused_credentials_are_reported_not_hidden_by_fallback(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    with layer(tmp_path, lambda r: httpx.Response(401, json={"msg": f"bad key {KEY}"}), calls=calls) as data:
        result = data.query(None, "SELECT 1 AS one")
    assert isinstance(result, QueryError) and result.code == "failed"
    assert "refused the credentials" in result.message and result.adapter == "zetaris"
    assert len(calls) == 1


def test_no_credential_reaches_results_or_logs(tmp_path: Path) -> None:
    """Error texts that echo a secret are scrubbed; the log never holds a key, token or password."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"idToken": TOKEN})
        if request.headers["Authorization"] == f"Bearer {KEY}":
            return httpx.Response(401, text=f"key {KEY} refused")  # so the client logs in and holds a token
        if "boom" in sql_of(request):
            return httpx.Response(503, text=f"upstream said {KEY} {TOKEN}")
        return httpx.Response(400, text=f"java.lang.RuntimeException: Exception: bad SQL near {KEY} / {TOKEN}")

    with layer(tmp_path, handler, zetaris_username="admin@example.com", zetaris_password=PASSWORD) as data:
        failed = data.query(None, "SELECT 1 AS x")
        fell_back = data.query(None, "SELECT 1 AS boom")
        text = data.log.path.read_text()
    assert isinstance(failed, QueryError) and "bad SQL near ***" in failed.message
    assert isinstance(fell_back, QueryResult) and fell_back.adapter == FALLBACK_ADAPTER
    for secret in (KEY, TOKEN, PASSWORD):
        assert secret not in text
        assert secret not in failed.message
    assert "***" in text


def test_error_message_is_the_useful_part_of_the_stack_trace(tmp_path: Path) -> None:
    trace = ("org.apache.spark.sql.AnalysisException: [UNRESOLVED_COLUMN] A column `nope` cannot be resolved\n"
             "\tat org.apache.spark.sql.catalyst...\n" * 3)
    with layer(tmp_path, lambda r: httpx.Response(400, text=trace)) as data:
        result = data.query(None, "SELECT nope FROM orders.orders")
    assert isinstance(result, QueryError) and result.code == "failed"
    assert result.message == "Zetaris: [UNRESOLVED_COLUMN] A column `nope` cannot be resolved"
    with layer(tmp_path, lambda r: httpx.Response(400, json={"msg": "Not Allowed"})) as data:
        assert data.query(None, "SELECT 1 AS one").message == "Zetaris: Not Allowed"


# --- guard, limit, rewrite --------------------------------------------------------------------------


@pytest.mark.parametrize("sql", ["DELETE FROM orders.orders", "SELECT 1; SELECT 2", "DROP TABLE orders.orders",
                                 "CREATE DATASOURCE x OPTIONS ()", ""])
def test_guard_rejects_before_any_call(tmp_path: Path, sql: str) -> None:
    calls: list[httpx.Request] = []
    with layer(tmp_path, lambda r: ok(["n"], [["1"]]), calls=calls) as data:
        result = data.query(None, sql)
    assert isinstance(result, QueryError) and result.code == "rejected"
    assert calls == []


def test_unknown_source_is_structured_error(tmp_path: Path) -> None:
    with layer(tmp_path, lambda r: ok(["n"], [["1"]])) as data:
        result = data.query("eval", "SELECT 1")
        with pytest.raises(KeyError):
            data.describe("eval")
    assert isinstance(result, QueryError) and result.code == "unknown_source"


def test_row_limit_truncates_and_is_capped(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        limit = json.loads(request.content)["limit"]
        return ok(["order_id"], [[f"id{i}"] for i in range(limit)])

    with layer(tmp_path, handler, calls=calls, max_query_rows=50) as data:
        result = data.query("orders", "SELECT order_id FROM orders", limit=10)
        capped = data.query("orders", "SELECT order_id FROM orders", limit=1000)
    assert result.row_count == 10 and result.truncated is True
    assert json.loads(calls[0].content)["limit"] == 11
    assert capped.row_count == 50 and json.loads(calls[1].content)["limit"] == 51


def test_rewrite_maps_source_tables_to_the_usl() -> None:
    sql, used = to_usl_sql(
        "SELECT o.order_id, 'orders.orders' AS label, p.payment_value -- payments.order_payments\n"
        "FROM orders.orders o JOIN payments.order_payments p ON p.order_id = o.order_id "
        "JOIN reviews.order_reviews r ON r.order_id = o.order_id"
    )
    assert f"FROM {USL_PATH}.orders o" in sql
    assert f"JOIN {USL_PATH}.order_payments p" in sql and f"JOIN {USL_PATH}.order_reviews r" in sql
    assert "'orders.orders' AS label" in sql and "-- payments.order_payments\n" in sql
    assert "o.order_id" in sql and "p.payment_value" in sql
    assert used == [f"{USL_PATH}.orders", f"{USL_PATH}.order_payments", f"{USL_PATH}.order_reviews"]


def test_rewrite_leaves_aliases_wrong_pairs_and_qualified_names_alone() -> None:
    for text in (
        "SELECT COUNT(*) AS orders FROM x",                        # alias named like a table
        "SELECT * FROM payments.orders",                           # table is not in that source
        f"SELECT * FROM {USL_PATH}.orders",                        # already a USL name
        "SELECT orders.order_id FROM t AS orders",                 # alias.column
    ):
        assert to_usl_sql(text) == (text, [])


def test_rewrite_in_source_scope_handles_unqualified_tables() -> None:
    sql, used = to_usl_sql("SELECT COUNT(*) AS orders FROM orders JOIN order_items i ON i.order_id = orders.order_id",
                           "orders")
    assert sql == (f"SELECT COUNT(*) AS orders FROM {USL_PATH}.orders JOIN {USL_PATH}.order_items i "
                   "ON i.order_id = orders.order_id")
    assert used == [f"{USL_PATH}.orders", f"{USL_PATH}.order_items"]
    assert to_usl_sql("SELECT * FROM order_payments", "orders") == ("SELECT * FROM order_payments", [])


# --- types --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "declared", "expected"),
    [
        ("30256", "int", 30256),
        ("40.0", "int", 40),
        ("10.500000000000000000", "decimal(10,2)", 10.5),
        ("0E-18", "decimal(12,2)", 0.0),
        ("-3.25", "double", -3.25),
        ("2017-11-24", "date", "2017-11-24"),
        ("2017-11-24 00:00:00", "date", "2017-11-24"),
        ("2017-11-24 10:53:01", "timestamp", "2017-11-24T10:53:01"),
        ("2017-11-24 10:53:01.0", "timestamp", "2017-11-24T10:53:01"),
        ("2017-11-24T10:53:01.250", "timestamp", "2017-11-24T10:53:01.250000"),
        ("true", "boolean", True),
        ("False", "boolean", False),
        (None, "int", None),
        ("null", "timestamp", None),
        ("", "decimal(10,2)", None),
        ("null", "varchar(20)", "null"),
        ("00123", "varchar(32)", "00123"),
        ("not a number", "int", "not a number"),
    ],
)
def test_convert_value_by_usl_type(value: object, declared: str, expected: object) -> None:
    assert convert_value(value, type_family(declared)) == expected


def test_type_family_names() -> None:
    assert [type_family(t) for t in ("INT", "bigint", "decimal(38,18)", "DOUBLE", "timestamp_ntz", "string",
                                     "varchar(32)", "date", "boolean", "map<string,int>", None)] == [
        "int", "int", "decimal", "float", "timestamp", "str", "str", "date", "bool", None, None]


def test_computed_columns_are_inferred_per_column() -> None:
    assert infer_family(["1176", "3", None]) == "int"
    assert infer_family(["136.571400000000000000", "1", "0E-18"]) == "float"
    assert infer_family(["2017-11-24 10:00:00", None]) == "timestamp"
    assert infer_family(["891071be6ba827b591264c90c2ae8a63", "123"]) == "str"
    assert infer_family([None, None]) == "str"


def test_usl_column_types_win_over_inference(tmp_path: Path) -> None:
    """An all-digit varchar id stays a string; a USL int stays int; computed columns are inferred."""
    def handler(request: httpx.Request) -> httpx.Response:
        return ok(["seller_id", "seller_zip_code_prefix", "n", "avg_price", "first_seen"],
                  [["123456", "1001", "4", "12.500000000000000000", "2017-11-24 08:00:00"],
                   ["abc", "2002", "1", "0E-18", None]])

    with layer(tmp_path, handler) as data:
        result = data.query(None, "SELECT s.seller_id, s.seller_zip_code_prefix, COUNT(*) AS n, AVG(i.price) "
                                  "AS avg_price, MIN(i.shipping_limit_date) AS first_seen FROM orders.sellers s "
                                  "JOIN orders.order_items i ON i.seller_id = s.seller_id GROUP BY 1, 2")
    assert result.rows == [
        {"seller_id": "123456", "seller_zip_code_prefix": 1001, "n": 4, "avg_price": 12.5,
         "first_seen": "2017-11-24T08:00:00"},
        {"seller_id": "abc", "seller_zip_code_prefix": 2002, "n": 1, "avg_price": 0.0, "first_seen": None},
    ]


def test_header_objects_with_types_are_used(tmp_path: Path) -> None:
    body = {"headers": [{"name": "day", "type": "date"}, {"name": "code", "dataType": "string"}],
            "data": [["2018-01-02 00:00:00", "0042"]], "total": 1}
    rest = parse_rest_body(body)
    assert rest.headers == ["day", "code"] and rest.header_types == ["date", "string"]
    with layer(tmp_path, lambda r: httpx.Response(200, json=body)) as data:
        assert data.query(None, "SELECT 1").rows == [{"day": "2018-01-02", "code": "0042"}]


# --- fallback -----------------------------------------------------------------------------------------


def _fails(kind: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if kind == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(503, text="Service Unavailable")

    return handler


@pytest.mark.parametrize(("kind", "reason"), [("connect", "connection error (ConnectError)"),
                                              ("timeout", "timeout after 30 s (ReadTimeout)"),
                                              ("5xx", "HTTP 503: Service Unavailable")])
def test_outage_retries_once_then_falls_back_to_local(tmp_path: Path, kind: str, reason: str) -> None:
    calls: list[httpx.Request] = []
    sql = "SELECT COUNT(*) AS n FROM payments.order_payments"
    with layer(tmp_path, _fails(kind), calls=calls) as data:
        result = data.query(None, sql)
        [line] = data.log.read()
    assert len(calls) == 2  # the call and one retry
    assert isinstance(result, QueryResult), result
    assert result.adapter == FALLBACK_ADAPTER == "local (fallback from zetaris)"
    assert result.rows == [{"n": 31560}] and result.query_id == "q001" and result.sql == sql
    assert line["adapter"] == FALLBACK_ADAPTER and line["status"] == "ok" and line["query_id"] == "q001"
    assert line["fallback_reason"] == f"Zetaris unavailable after one retry: {reason}"
    assert line["usl_tables"] == [f"{USL_PATH}.order_payments"]


def test_one_failure_then_success_stays_on_zetaris(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502) if len(calls) == 1 else ok(["n"], [["7"]])

    with layer(tmp_path, handler, calls=calls) as data:
        result = data.query(None, "SELECT COUNT(*) AS n FROM orders.orders")
    assert len(calls) == 2 and result.adapter == "zetaris" and result.rows == [{"n": 7}]


def test_sql_error_is_not_an_outage(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    with layer(tmp_path, lambda r: httpx.Response(400, json={"msg": "ParseException: syntax error"}),
               calls=calls) as data:
        result = data.query(None, "SELECT strftime(x) FROM orders.orders")
    assert len(calls) == 1
    assert isinstance(result, QueryError) and result.adapter == "zetaris" and result.code == "failed"


def test_fallback_off_reports_the_outage(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    client = ZetarisClient.from_settings(cfg, transport=httpx.MockTransport(_fails("timeout")))
    with ZetarisDataLayer(settings=cfg, client=client, fallback=False, log_dir=tmp_path) as data:
        result = data.query(None, "SELECT 1 AS one")
    assert isinstance(result, QueryError) and result.code == "timeout" and result.adapter == "zetaris"


def test_fallback_result_matches_a_local_query_and_errors_are_marked(tmp_path: Path) -> None:
    with layer(tmp_path, _fails("connect")) as data:
        bad = data.query(None, "SELECT no_such_column FROM orders.orders")
    assert isinstance(bad, QueryError) and bad.adapter == FALLBACK_ADAPTER and bad.code == "failed"


# --- query log ----------------------------------------------------------------------------------------


def test_query_log_entries_carry_adapter_usl_tables_sql_duration_rows(tmp_path: Path) -> None:
    sql = ("SELECT o.order_status, COUNT(*) AS n FROM orders.orders o "
           "JOIN payments.order_payments p ON p.order_id = o.order_id GROUP BY 1")
    with layer(tmp_path, lambda r: ok(["order_status", "n"], [["delivered", "10"], ["canceled", "2"]])) as data:
        result = data.query(None, sql)
        rejected = data.query(None, "DROP TABLE orders.orders")
        lines = data.log.read()
    assert data.log.path == tmp_path / "logs" / "queries-zt.jsonl"
    first, second = lines
    assert first["query_id"] == result.query_id == "q001"
    assert first["adapter"] == "zetaris" and first["status"] == "ok"
    assert first["usl_tables"] == [f"{USL_PATH}.orders", f"{USL_PATH}.order_payments"]
    assert first["sql"] == sql
    assert first["zetaris_sql"].startswith(f"SELECT o.order_status, COUNT(*) AS n FROM {USL_PATH}.orders o")
    assert first["row_count"] == 2 and isinstance(first["duration_ms"], float)
    assert second["query_id"] == rejected.query_id == "q002" and second["status"] == "rejected"
    assert second["usl_tables"] == []


# --- describe -----------------------------------------------------------------------------------------


def test_describe_reads_usl_types_and_counts_through_zetaris(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return ok(["table_name", "row_count"], [["order_payments", "31560"]])

    with layer(tmp_path, handler, calls=calls) as data:
        info = data.describe("payments")
        again = data.describe("payments")
    assert again is info and len(calls) == 1
    assert f"FROM {USL_PATH}.order_payments" in sql_of(calls[0])
    [table] = info.tables
    assert table.name == "order_payments" and table.row_count == 31560
    assert {c.name: c.type for c in table.columns}["payment_value"] == "decimal(12,2)"


def test_describe_falls_back_to_local_when_zetaris_is_down(tmp_path: Path) -> None:
    with layer(tmp_path, _fails("connect")) as data:
        info = data.describe("payments")
    assert info.tables[0].row_count == 31560
    assert {c.name: c.type for c in info.tables[0].columns}["payment_value"] == "DOUBLE"


def test_describe_reports_a_usl_problem(tmp_path: Path) -> None:
    with layer(tmp_path, lambda r: httpx.Response(400, json={"msg": "table is not activated"})) as data, \
            pytest.raises(RuntimeError, match="not activated"):
        data.describe("reviews")

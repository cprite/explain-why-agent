"""Tests for scripts/zetaris_setup.py and the USL model, against a fake Zetaris (no network, no docker).

`FakeZetaris` keeps the server state the setup changes (data sources, namespaces, the USL, activation,
DQ rules) and enforces the rules we learned on the real one: one statement per request (a `;` is only
allowed inside `COMPILE USL`), the parent namespace first, activation before DQ, no duplicate rule,
description text limited to letters, digits, spaces and `_ . - ,`.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.data.usl import (
    DQ_RULES,
    OLIST_USL,
    SOURCES,
    USL_PATH,
    activate_sql,
    compile_usl_sql,
    foreign_keys,
    postgres_init_sql,
    tables_of,
)
from app.data.zetaris import ZetarisClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import zetaris_setup

PG_PASSWORD = "pg-Secret-42"


def _err(msg: str) -> httpx.Response:
    return httpx.Response(400, text=f"java.lang.RuntimeException\nException: {msg}\n\tat com.zetaris...")


def _ok(headers: list[str], data: list[list]) -> httpx.Response:
    return httpx.Response(200, json={"headers": headers, "data": data, "total": len(data), "timeUsed": 3})


class FakeZetaris:
    """Enough of Zetaris 2.4.3 for the setup script."""

    def __init__(self, *, registered: bool = True) -> None:
        self.datasources: dict[str, list[str]] = (
            {f"olist_{s}": [t.name for t in tables_of(s)] for s in SOURCES} if registered else {}
        )
        self.namespaces: set[str] = set()
        self.usl: str | None = None
        self.activated: dict[str, int] = {}
        self.rules: dict[str, str] = {}
        self.descriptions: dict[str, str] = {}
        self.sent: list[str] = []

    def state(self) -> dict:
        return copy.deepcopy({k: v for k, v in vars(self).items() if k not in ("sent", "activated")}) | {
            "activated": sorted(self.activated)}

    def handle(self, request: httpx.Request) -> httpx.Response:
        sql = json.loads(request.content)["sql"].strip()
        self.sent.append(sql)
        upper = sql.upper()
        if ";" in sql and not upper.startswith("COMPILE USL"):
            return _err("mismatched input ';' expecting <EOF>")
        if m := re.fullmatch(r"SHOW TABLES IN (\w+)", sql):
            if m.group(1) not in self.datasources:
                return _err(f"Datasource {m.group(1)} not found")
            return _ok(["namespace", "tableName", "isTemporary"],
                       [[m.group(1), t, "false"] for t in self.datasources[m.group(1)]])
        if m := re.match(r"CREATE DATASOURCE (\w+) DESCRIBE BY \"([^\"]*)\" OPTIONS", sql):
            assert ":" not in m.group(2) and 'jdbcdriver "org.postgresql.Driver"' in sql
            self.datasources[m.group(1)] = []
            return _ok(["result"], [["ok"]])
        if m := re.fullmatch(r"REGISTER DATASOURCE TABLES FROM (\w+)", sql):
            self.datasources[m.group(1)] = [t.name for t in tables_of(m.group(1).removeprefix("olist_"))]
            return _ok(["result"], [["ok"]])
        if m := re.fullmatch(r"CREATE NAMESPACE IF NOT EXISTS ([\w.]+)", sql):
            parent = m.group(1).rsplit(".", 1)[0]
            if m.group(1) != "lightning.metastore" and parent not in self.namespaces:
                return _err(f"namespace {parent} does not exist")
            self.namespaces.add(m.group(1))
            return _ok(["result"], [["ok"]])
        if m := re.fullmatch(r"SHOW NAMESPACES OR TABLES IN ([\w.]+)", sql):
            if m.group(1) not in self.namespaces:
                return _err(f"namespace {m.group(1)} not found")
            children = [n.rsplit(".", 1)[1] for n in self.namespaces if n.rsplit(".", 1)[0] == m.group(1)]
            if self.usl and USL_PATH.rsplit(".", 1)[0] == m.group(1):
                children.append(self.usl)
            return _ok(["name", "type"], [[c, "namespace"] for c in children])
        if upper.startswith("COMPILE USL"):
            if "lightning.metastore.explain_why" not in self.namespaces:
                return _err("namespace does not exist")
            if self.usl:
                return _err("USL olist_usl already exists")  # stricter than IF NOT EXISTS: never resend
            assert len(re.findall(r"^CREATE TABLE ", sql, re.MULTILINE)) == len(OLIST_USL)
            self.usl = "olist_usl"
            return _ok(["result"], [["compiled"]])
        if m := re.match(r"ACTIVATE USL TABLE ([\w.]+) AS\nSELECT ", sql):
            if not self.usl:
                return _err("USL not found")
            table = m.group(1).rsplit(".", 1)[1]
            source = next(t.datasource for t in OLIST_USL if t.name == table)
            if not sql.endswith(f"FROM {source}.{table}") or table not in self.datasources.get(source, []):
                return _err(f"table {source}.{table} not found")
            self.activated[table] = self.activated.get(table, 0) + 1
            return _ok(["result"], [["activated"]])
        if m := re.fullmatch(r"UPDATE USL ([\w.]+) SET TABLE DESCRIPTION (.+)", sql):
            if not re.fullmatch(r"[A-Za-z0-9 _.,-]+", m.group(2)):
                return _err("invalid description")
            self.descriptions[m.group(1)] = m.group(2)
            return _ok(["result"], [["ok"]])
        if re.fullmatch(rf"LIST DQ USL {re.escape(USL_PATH)}", sql):
            return _ok(["table", "rule", "expression"], [[t, r, e] for r, (t, e) in self.rules.items()])
        if m := re.fullmatch(r"REGISTER DQ (\w+) TABLE ([\w.]+) AS (.+)", sql):
            table = m.group(2).rsplit(".", 1)[1]
            if table not in self.activated:
                return _err("table is not activated")
            if m.group(1) in self.rules:
                return _err(f"rule {m.group(1)} already exists")
            self.rules[m.group(1)] = (table, m.group(3))
            return _ok(["result"], [["registered"]])
        if m := re.fullmatch(r"RUN DQ (\w+) TABLE ([\w.]+)", sql):
            if m.group(1) not in self.rules:
                return _err("rule not found")
            return _ok(["total_records", "valid_records", "invalid_records"], [["31560", "31558", "2"]])
        if m := re.fullmatch(r"SHOW DQ INVALID RECORD (\w+) TABLE ([\w.]+)", sql):
            rows = [["a", "-1.000000000000000000"], ["b", "-2.000000000000000000"]] \
                if m.group(1) == "payment_value_not_negative" else []
            return _ok(["order_id", "payment_value"], rows)
        if "AS table_name, COUNT(*) AS row_count" in sql:
            names = re.findall(r"SELECT '(\w+)' AS table_name", sql)
            return _ok(["table_name", "row_count"], [[n, str(zetaris_setup.sample_row_count(n))] for n in names])
        if upper.startswith("WITH PAY AS"):
            return _ok(["month", "orders", "payment_value", "avg_review_score"],
                       [["2017-11", "7544", "1180000.000000000000000000", "3.990000000000000000"]])
        return _err(f"fake does not know: {sql[:60]}")


def run_setup(fake: FakeZetaris, *args: str, compose: object = None, pg_password: str = "",
              monkeypatch: pytest.MonkeyPatch | None = None) -> tuple[int, str]:
    lines: list[str] = []
    client = ZetarisClient("http://fake/api/v1.0", org_id="1", api_key="setup-key",
                           transport=httpx.MockTransport(fake.handle))
    setup = zetaris_setup.Setup(client, out=lines.append, start_sources="--start-sources" in args,
                                pg_password=pg_password, compose=compose or _no_docker)
    code = setup.run()
    return code, "\n".join(lines)


def _no_docker(*args: object, **kwargs: object) -> None:
    raise AssertionError("docker must not run for registered sources")


# --- the USL model -----------------------------------------------------------------------------------


def test_usl_covers_every_sample_table_once() -> None:
    files = sorted((p.parent.name, p.stem) for p in (ROOT / "data" / "sample").glob("*/*.csv"))
    assert sorted((t.source, t.name) for t in OLIST_USL) == files
    assert {t.source for t in OLIST_USL} == set(SOURCES)


def test_usl_columns_match_the_csv_headers() -> None:
    for table in OLIST_USL:
        header = (ROOT / "data" / "sample" / table.source / f"{table.name}.csv").open().readline().strip()
        assert [c.name for c in table.columns] == header.split(","), table.name


def test_foreign_keys_point_at_primary_keys_defined_earlier_and_cross_sources() -> None:
    order = [t.name for t in OLIST_USL]
    by_name = {t.name: t for t in OLIST_USL}
    for column, target, _kind in foreign_keys():
        table, target_col = target.split(".")
        assert by_name[table].column(target_col).primary_key, target
        assert order.index(table) < order.index(column.split(".")[0]), column
    kinds = [k for *_, k in foreign_keys()]
    assert kinds.count("cross-source") == 3 and len(kinds) == 9


def test_compile_usl_is_one_statement_with_every_table_and_key() -> None:
    sql = compile_usl_sql()
    assert sql.startswith("COMPILE USL IF NOT EXISTS olist_usl DEPLOY NAMESPACE lightning.metastore.explain_why DDL\n")
    assert len(re.findall(r"^CREATE TABLE \w+ \($", sql, re.MULTILINE)) == 11
    assert sql.count(";") == 10 and not sql.rstrip().endswith(";")
    assert "order_id varchar(32) FOREIGN KEY REFERENCES orders(order_id)" in sql
    assert "payment_value decimal(12,2)" in sql and "order_purchase_timestamp timestamp" in sql
    assert "order_id varchar(32) NOT NULL PRIMARY KEY" in sql


def test_activation_casts_types_and_coalesces_primary_keys() -> None:
    sql = activate_sql(next(t for t in OLIST_USL if t.name == "order_payments"))
    assert sql.startswith(f"ACTIVATE USL TABLE {USL_PATH}.order_payments AS\nSELECT ")
    assert "CAST(payment_value AS DECIMAL(12,2)) AS payment_value" in sql
    assert sql.endswith("FROM olist_payments.order_payments")
    orders = activate_sql(next(t for t in OLIST_USL if t.name == "orders"))
    assert "COALESCE(order_id, '') AS order_id" in orders
    assert "CAST(order_purchase_timestamp AS TIMESTAMP) AS order_purchase_timestamp" in orders


def test_committed_postgres_init_scripts_are_current() -> None:
    for source in SOURCES:
        path = ROOT / "scripts" / "zetaris_sources" / f"{source}.sql"
        assert path.read_text() == postgres_init_sql(source), "run: python scripts/zetaris_setup.py --write-init-sql"
    assert "COPY order_reviews FROM '/data/order_reviews.csv' WITH (FORMAT csv, HEADER true);" in \
        postgres_init_sql("reviews")


def test_compose_file_puts_four_postgres_sources_on_the_zetaris_network() -> None:
    text = (ROOT / "docker-compose.zetaris-sources.yml").read_text()
    for source in SOURCES:
        assert f"container_name: olist-{source}" in text
        assert f"./scripts/zetaris_sources/{source}.sql:/docker-entrypoint-initdb.d/01-load.sql:ro" in text
    assert "name: zetaris_default" in text and "external: true" in text
    assert "${OLIST_PG_PASSWORD:?" in text and "ports:" not in text


# --- the setup script --------------------------------------------------------------------------------


def test_setup_on_registered_sources_builds_the_usl_and_runs_dq() -> None:
    fake = FakeZetaris(registered=True)
    code, out = run_setup(fake)
    assert code == 0, out
    assert fake.usl == "olist_usl" and set(fake.activated) == {t.name for t in OLIST_USL}
    assert set(fake.rules) == {r.name for r in DQ_RULES}
    assert fake.namespaces == {"lightning.metastore", "lightning.metastore.explain_why"}
    assert fake.sent.index("CREATE NAMESPACE IF NOT EXISTS lightning.metastore") < \
        fake.sent.index("CREATE NAMESPACE IF NOT EXISTS lightning.metastore.explain_why")
    assert not any(s.startswith("CREATE DATASOURCE") for s in fake.sent)
    assert "rule payment_value_not_negative on order_payments (payment_value >= 0): invalid records: 2" in out
    assert "rule purchase_timestamp_present on orders (order_purchase_timestamp IS NOT NULL): invalid records: 0" \
        in out
    assert "invalid_records=2" in out
    assert f"{USL_PATH}.order_reviews: 30185 (sample 30185) ok" in out
    assert "2017-11" in out and "7544" in out  # the cross-source join through the USL
    assert f"USL ready: {USL_PATH} (11 tables, 9 foreign keys)" in out
    assert "order_payments.order_id -> orders.order_id (cross-source)" in out


def test_setup_twice_changes_nothing_and_does_not_fail() -> None:
    fake = FakeZetaris(registered=True)
    assert run_setup(fake)[0] == 0
    before = fake.state()
    first_run = list(fake.sent)
    fake.sent.clear()
    code, out = run_setup(fake)
    assert code == 0, out
    assert fake.state() == before
    creating = ("CREATE ", "COMPILE ", "REGISTER ")
    assert [s for s in fake.sent if s.startswith(creating)] == []
    assert len([s for s in fake.sent if s.startswith("ACTIVATE USL TABLE")]) == 11  # re-activated every run
    assert all(n == 2 for n in fake.activated.values())
    assert "created: nothing (everything was already there)" in out
    assert len([s for s in first_run if s.startswith("COMPILE USL")]) == 1


def test_every_request_is_one_whole_statement() -> None:
    fake = FakeZetaris(registered=True)
    run_setup(fake)
    [compile_sql] = [s for s in fake.sent if s.startswith("COMPILE USL")]
    assert compile_sql == compile_usl_sql()  # never split on ';'
    assert all(";" not in s for s in fake.sent if not s.startswith("COMPILE USL"))


def test_missing_source_without_start_sources_stops_with_instructions() -> None:
    fake = FakeZetaris(registered=False)
    code, out = run_setup(fake)
    assert code == 1
    assert "data source olist_orders is not registered" in out and "--start-sources" in out
    assert not any(s.startswith("CREATE") for s in fake.sent)


def test_missing_sources_are_started_registered_and_the_password_never_printed() -> None:
    fake = FakeZetaris(registered=False)
    started: list[list[str]] = []

    def compose(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        started.append(cmd)
        assert kwargs["timeout"] == zetaris_setup.COMPOSE_TIMEOUT_SECONDS
        return SimpleNamespace(returncode=0, stderr="")

    code, out = run_setup(fake, "--start-sources", compose=compose, pg_password=PG_PASSWORD)
    assert code == 0, out
    assert [c[-1] for c in started] == [f"olist-{s}" for s in SOURCES]
    assert started[0][:4] == ["docker", "compose", "-f", str(ROOT / "docker-compose.zetaris-sources.yml")]
    creates = [s for s in fake.sent if s.startswith("CREATE DATASOURCE")]
    assert len(creates) == 4 and all(PG_PASSWORD in s for s in creates)
    assert 'jdbcurl "jdbc:postgresql://olist-payments:5432/olist"' in creates[1]
    assert PG_PASSWORD not in out and "> CREATE DATASOURCE olist_orders DESCRIBE BY" in out
    assert set(fake.datasources) == {f"olist_{s}" for s in SOURCES}


def test_missing_password_is_reported() -> None:
    code, out = run_setup(FakeZetaris(registered=False), "--start-sources")
    assert code == 1 and "OLIST_PG_PASSWORD is needed" in out


def test_a_zetaris_error_stops_the_setup_with_its_message() -> None:
    fake = FakeZetaris(registered=True)
    original = fake.handle

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["sql"].startswith("ACTIVATE USL TABLE"):
            return _err("Column order_id is nullable but declared NOT NULL")
        return original(request)

    fake.handle = handler
    code, out = run_setup(fake)
    assert code == 1 and "FAILED: Zetaris: Column order_id is nullable but declared NOT NULL" in out


def test_cli_without_settings_exits_2_and_dry_run_sends_nothing() -> None:
    env = {"PATH": "/usr/bin:/bin"}
    missing = subprocess.run([sys.executable, "scripts/zetaris_setup.py"], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=60, check=False)
    assert missing.returncode == 2 and "Zetaris settings are missing" in missing.stderr
    dry = subprocess.run([sys.executable, "scripts/zetaris_setup.py", "--dry-run"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60, check=False)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert compile_usl_sql().splitlines()[0] in dry.stdout
    assert "REGISTER DQ payment_value_not_negative TABLE" in dry.stdout
    assert "dry run: nothing was sent" in dry.stdout

"""Plan check (build-plan task 10): the Day 1 queries through the Zetaris adapter equal local DuckDB.

The Zetaris side replays the REST responses in `tests/fixtures/zetaris/` through the real adapter
(rewrite to USL names, request headers, string-to-type conversion); the local side runs the same
statements on the sample. Both result sets are printed side by side; run with `-s` to see them
(CI does: `pytest -s -q tests/test_zetaris_plan_check.py`).

The live version of this check is `scripts/zetaris_parity.py`, which can also re-record the fixtures
from a real server (`--record`).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.data.layer import QueryResult
from app.data.local import LocalDataLayer
from app.data.parity import (
    BODY_KEYS,
    FIXTURE_DIR,
    compare,
    load_fixtures,
    load_queries,
    replay_transport,
    side_by_side,
)
from app.data.zetaris import ZetarisClient, ZetarisDataLayer, to_usl_sql

QUERIES = load_queries()
FIXTURES = load_fixtures()


@pytest.fixture(scope="module")
def adapters(tmp_path_factory: pytest.TempPathFactory) -> tuple[LocalDataLayer, ZetarisDataLayer, list]:
    logs = tmp_path_factory.mktemp("logs")
    cfg = Settings(sample_mode=False, record_cache=False, log_dir=str(logs), zetaris_url="http://replay/api/v1.0",
                   zetaris_api_key="replay", zetaris_org_id="1")
    seen: list = []
    client = ZetarisClient.from_settings(cfg, transport=replay_transport(FIXTURES, seen))
    local = LocalDataLayer(run_id="plan-check-local", log_dir=logs, settings=cfg)
    zetaris = ZetarisDataLayer(run_id="plan-check-zetaris", log_dir=logs, settings=cfg, client=client,
                               fallback=False)
    yield local, zetaris, seen
    zetaris.close()
    local.close()


def test_every_query_has_a_fixture_recorded_for_its_usl_statement() -> None:
    assert [q.name for q in QUERIES][:6] == [
        "orders_row_count", "day1_orders_vs_baseline", "day1_seller_spike", "day1_category_mix",
        "day1_duplicate_rows", "day1_price_and_installments"]
    assert set(FIXTURES) == {q.name for q in QUERIES}
    for query in QUERIES:
        expected, _ = to_usl_sql(query.sql.strip().rstrip(";").rstrip(), query.source)
        assert FIXTURES[query.name]["request"]["sql"] == expected, query.name


def test_fixtures_hold_no_hosts_tokens_or_org_secrets() -> None:
    secret_like = re.compile(
        r"https?://|127\.0\.0\.1|localhost|amazonaws|\b\d{1,3}(\.\d{1,3}){3}\b|bearer|apikey|api_key|idtoken|"
        r"refreshtoken|password|x-org-id|x-request-id|queryid", re.IGNORECASE)
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert not secret_like.search(text), f"{path.name}: {secret_like.search(text).group(0)}"
        record = json.loads(text)
        if path.name != "queries.json":
            assert set(record) == {"name", "recorded_with", "recorded_at", "request", "response"}
            assert set(record["request"]) == {"sql", "limit"}
            assert set(record["response"]) == set(BODY_KEYS)


def test_fixtures_are_in_zetaris_wire_format() -> None:
    """Every value is a string or null, as REST returns them (decimals with 18 places, `0E-18`)."""
    values = [v for f in FIXTURES.values() for row in f["response"]["data"] for v in row]
    assert values and all(v is None or isinstance(v, str) for v in values)
    assert any(v == "0E-18" for v in values)
    assert any(v and re.fullmatch(r"\d+\.\d{18}", v) for v in values)
    assert any(v and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", v) for v in values)


@pytest.mark.parametrize("query", QUERIES, ids=[q.name for q in QUERIES])
def test_plan_check_zetaris_replay_equals_local(adapters: tuple, query, capsys: pytest.CaptureFixture) -> None:
    local, zetaris, _ = adapters
    left = local.query(query.source, query.sql)
    right = zetaris.query(query.source, query.sql)
    passed, verdict = compare(left, right)
    with capsys.disabled():
        print(f"\n== plan check {query.name} [{FIXTURES[query.name]['recorded_with']}]: {verdict}")
        print(side_by_side(left, right))
    assert isinstance(right, QueryResult) and right.adapter == "zetaris"
    assert passed, verdict


def test_plan_check_requests_carry_auth_and_usl_names(adapters: tuple) -> None:
    *_, seen = adapters
    assert seen, "run after the replay tests"
    for request in seen:
        assert request.headers["Authorization"] == "Bearer replay" and request.headers["X-Org-ID"] == "1"
        assert "lightning.metastore.explain_why.olist_usl." in json.loads(request.content)["sql"]


def test_day1_headline_numbers_through_zetaris(adapters: tuple) -> None:
    """The numbers the Day 1 answer rests on, read through the USL path."""
    _, zetaris, _ = adapters
    by_name = {q.name: q for q in QUERIES}
    count = zetaris.query(None, by_name["orders_row_count"].sql)
    day = zetaris.query(None, by_name["day1_orders_vs_baseline"].sql)
    assert count.rows == [{"n": 30256}]  # as the session's live REST probe returned on 23 Oct
    assert day.rows == [{"value": 1176, "baseline": 136.5714}]  # 1,176: the 14 Oct live Zetaris figure


def test_parity_script_without_credentials_exits_2() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {"PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, "scripts/zetaris_parity.py"], cwd=root, env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Zetaris credentials are not set" in result.stderr
    assert "Nothing was run" in result.stderr


def _result(rows: list[dict], adapter: str = "zetaris") -> QueryResult:
    columns = list(rows[0]) if rows else []
    return QueryResult(query_id="q", source=None, sql="", adapter=adapter, columns=columns, rows=rows,
                       row_count=len(rows), truncated=False, duration_ms=0.0)


def test_compare_passes_ties_with_other_ids_and_fails_on_other_numbers() -> None:
    local = _result([{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 2}], "local")
    assert compare(local, _result([{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 2.0}])) == (True, "PASS")
    assert compare(local, _result([{"seller_id": "b", "n": 2}, {"seller_id": "a", "n": 3}]))[1] == \
        "PASS (same rows, different order)"
    assert compare(local, _result([{"seller_id": "a", "n": 3}, {"seller_id": "z", "n": 2}]))[1] == \
        "PASS (same numbers; tied rows carry different identifiers)"
    assert compare(local, _result([{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 5}]))[0] is False
    assert compare(local, _result([{"seller_id": "a", "orders": 3}]))[0] is False

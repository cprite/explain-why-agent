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
import os
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
    LIVE,
    NUMERIC_REL_TOL,
    SYNTHETIC,
    compare,
    load_fixtures,
    load_queries,
    replay_transport,
    side_by_side,
    synthetic_fixtures,
    write_fixture,
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


def _result(rows: list[dict], adapter: str = "zetaris", sql: str = "") -> QueryResult:
    columns = list(rows[0]) if rows else []
    return QueryResult(query_id="q", source=None, sql=sql, adapter=adapter, columns=columns, rows=rows,
                       row_count=len(rows), truncated=False, duration_ms=0.0)


TOP2 = "SELECT seller_id, COUNT(*) AS n FROM orders.order_items GROUP BY 1 ORDER BY n DESC LIMIT 2"


def test_compare_passes_same_rows_and_a_tie_cut_by_limit() -> None:
    local = _result([{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 2}], "local", TOP2)
    assert compare(local, _result([{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 2.0}])) == (True, "PASS")
    assert compare(local, _result([{"seller_id": "b", "n": 2}, {"seller_id": "a", "n": 3}]))[1] == \
        "PASS (same rows, different order)"
    # b and z both have 2 orders; LIMIT 2 keeps one of them, and the engines may pick differently.
    assert compare(local, _result([{"seller_id": "a", "n": 3}, {"seller_id": "z", "n": 2}]))[1] == \
        "PASS (same numbers; the LIMIT cut a tie at different rows)"
    assert compare(local, _result([{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 5}]))[0] is False
    assert compare(local, _result([{"seller_id": "a", "orders": 3}]))[0] is False


def test_compare_fails_other_identifiers_without_a_limit_cut() -> None:
    rows = [{"seller_id": "a", "n": 3}, {"seller_id": "b", "n": 2}]
    other = [{"seller_id": "a", "n": 3}, {"seller_id": "z", "n": 2}]
    no_limit = TOP2.removesuffix(" LIMIT 2")
    assert compare(_result(rows, "local", no_limit), _result(other)) == (False, "FAIL: values differ")
    # LIMIT 5 was not reached, so nothing was cut.
    assert compare(_result(rows, "local", TOP2.replace("LIMIT 2", "LIMIT 5")), _result(other))[0] is False
    # The differing row is not the last tie group.
    ahead = [{"seller_id": "z", "n": 3}, {"seller_id": "b", "n": 2}]
    assert compare(_result(rows, "local", TOP2), _result(ahead))[0] is False


def test_compare_fails_swapped_labels() -> None:
    local = [{"cat": "beleza", "n": 100}, {"cat": "esporte", "n": 50}]
    swapped = [{"cat": "beleza", "n": 50}, {"cat": "esporte", "n": 100}]
    sql = "SELECT cat, COUNT(*) AS n FROM t GROUP BY cat ORDER BY cat"
    for statement in (sql, sql + " LIMIT 2"):
        assert compare(_result(local, "local", statement), _result(swapped)) == (False, "FAIL: values differ")


def test_compare_fails_differently_formatted_date_labels() -> None:
    local = [{"day": "2017-11-24", "n": 1176}]
    shifted = [{"day": "2017-11-24 00:00:00", "n": 1176}]
    sql = "SELECT day, COUNT(*) AS n FROM t GROUP BY day ORDER BY n DESC"
    for statement in (sql, sql + " LIMIT 1"):
        assert compare(_result(local, "local", statement), _result(shifted)) == (False, "FAIL: values differ")
    other_day = [{"day": "2017-11-25", "n": 1176}]
    assert compare(_result(local, "local", sql), _result(other_day))[0] is False


SPIKE = ("SELECT seller_id, window_orders, baseline_avg_daily_orders, spike_ratio FROM t "
         "ORDER BY spike_ratio DESC NULLS LAST LIMIT 3")


def _spike(seller: str, window: int, baseline: float, ratio: float) -> dict:
    return {"seller_id": seller, "window_orders": window, "baseline_avg_daily_orders": baseline,
            "spike_ratio": ratio}


def test_compare_tolerates_spark_decimal_division_with_a_tie_cut() -> None:
    # Live run, 23 Oct, day1_seller_spike: Spark computes 1/7.0 as DECIMAL 0.142857, so
    # ROUND(10 / 0.142857, 4) = 70.0001 where DuckDB's double gives 70; LIMIT cut the spike_ratio 21
    # tie at a different seller.
    local = _result([_spike("s1", 10, 0.1429, 70.0), _spike("s2", 3, 0.1429, 21.0),
                     _spike("s3", 3, 0.1429, 21.0)], "local", SPIKE)
    zetaris = _result([_spike("s1", 10, 0.1429, 70.0001), _spike("s2", 3, 0.1429, 21.0),
                       _spike("s9", 3, 0.1429, 21.0)])
    assert compare(local, zetaris) == (True, "PASS (same numbers; the LIMIT cut a tie at different rows)")
    assert NUMERIC_REL_TOL == 1e-5


def test_compare_fails_a_relative_difference_of_1e_3() -> None:
    local = _result([_spike("s1", 10, 0.1429, 70.0), _spike("s2", 3, 0.1429, 21.0)], "local",
                    SPIKE.replace("LIMIT 3", "LIMIT 2"))
    off = _result([_spike("s1", 10, 0.1429, 70.07), _spike("s2", 3, 0.1429, 21.0)])
    assert compare(local, off) == (False, "FAIL: values differ")
    # The same difference inside the tie group at the cut also fails.
    tie_off = _result([_spike("s1", 10, 0.1429, 70.0), _spike("s9", 3, 0.1429, 21.021)])
    assert compare(local, tie_off) == (False, "FAIL: values differ")


def test_fixture_provenance_is_known_and_not_mixed() -> None:
    """Each fixture is either live or synthetic, and a partial `--record` run is not committed."""
    labels = {f["recorded_with"] for f in FIXTURES.values()}
    assert labels <= {LIVE, SYNTHETIC}, labels
    assert len(labels) == 1, f"mixed provenance, re-run the recording: {synthetic_fixtures(FIXTURES)} synthetic"


def test_fixtures_are_live_zetaris_responses() -> None:
    """Acceptance criterion 7 needs real Zetaris responses; synthetic ones only prove the adapter.

    Skipped (with the reason in the CI log) while the fixtures are synthetic; with
    ZETARIS_REQUIRE_LIVE_FIXTURES=1 it fails instead, which is how to check before merging.
    """
    synthetic = synthetic_fixtures(FIXTURES)
    if synthetic and os.environ.get("ZETARIS_REQUIRE_LIVE_FIXTURES") != "1":
        pytest.skip(f"{len(synthetic)} of {len(FIXTURES)} Zetaris fixtures are SYNTHETIC: the plan check does not "
                    "yet prove Zetaris gives the same numbers; record live with scripts/zetaris_parity.py --record")
    assert not synthetic, f"synthetic fixtures: {synthetic}"


def _status(directory: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    return subprocess.run([sys.executable, "scripts/zetaris_fixture_status.py", "--dir", str(directory), *args],
                          capture_output=True, text=True, timeout=60, env=env, check=False)


@pytest.mark.parametrize("label", [SYNTHETIC, LIVE])
def test_fixture_status_script_flags_synthetic_fixtures(tmp_path: Path, label: str) -> None:
    body = {"headers": ["n"], "data": [["1"]], "total": 1}
    write_fixture("a", "SELECT 1", 1001, body, recorded_with=LIVE, directory=tmp_path)
    write_fixture("b", "SELECT 2", 1001, body, recorded_with=label, directory=tmp_path)
    warn, strict = _status(tmp_path), _status(tmp_path, "--require-live")
    assert warn.returncode == 0
    if label == SYNTHETIC:
        assert "WARNING: 1 of 2 Zetaris fixtures are synthetic" in warn.stdout
        assert strict.returncode == 1 and "FAIL: 1 of 2" in strict.stdout
    else:
        assert "all 2 fixtures recorded from a live Zetaris" in warn.stdout and strict.returncode == 0

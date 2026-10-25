"""Sprint 11d: filter values grounded in the data, and empty results (issue #36).

Real Nightshift runs on 25 Oct filtered on values that are not stored ('Minas Gerais' where the column
holds 'MG', 'Rio de Janeiro' where cities are lower case and the question is about the state,
'paid-search' on the wrong column where the channel is `origin` = 'paid_search'). The query matched
nothing and the Critic called it a small sample. These tests reproduce the four cases with a scripted
generator over the real sample data: wrong value -> empty -> stored-values check -> corrected query ->
numbers. No network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.agents.base import AgentContext, Budget, parse_input
from app.agents.investigator import NO_RECORDS_FINDING, investigate, matched_nothing
from app.agents.prompts import load_prompt
from app.config import Settings
from app.data import value_hints as vh
from app.data.layer import DataLayer, QueryOutcome, QueryResult, SourceInfo
from app.data.local import LocalDataLayer
from app.engines.markovian.config import MarkovianConfig
from app.engines.markovian.orchestrator import run_markovian
from app.llm.generator import GenerationResult
from app.llm.stub import ScriptedModel
from app.schemas import CritiqueDraft, Hypothesis, ObservationDraft, Plan, Result, SqlProposal
from app.trace import TraceWriter

DAY1 = "Why did order volume spike on 24 November 2017?"
WRONG_STATUS = "o.order_status = 'Delivered' AND "  # stored values are lower case


def settings_for(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {"sample_mode": False, "log_dir": str(tmp_path / "logs"),
                              "llm_cache_dir": str(tmp_path / "cache"), "max_tool_calls": 30,
                              "meterless_runtime_token": "", "nvidia_api_key": ""}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="module")
def sample_layer(tmp_path_factory: pytest.TempPathFactory) -> Any:
    logs = tmp_path_factory.mktemp("hints") / "logs"
    with LocalDataLayer(run_id="hints", log_dir=logs, settings=settings_for(logs.parent)) as data:
        yield data


def schemas_of(data: DataLayer) -> list[dict[str, Any]]:
    return AgentContext(run_id="s", generate=None, data=data, trace=None, budget=None).source_schemas()  # type: ignore[arg-type]


# --- value hints -------------------------------------------------------------------------------------


def test_value_hints_list_the_stored_values_on_the_sample_data(sample_layer: LocalDataLayer) -> None:
    hints = vh.build_value_hints(sample_layer, schemas_of(sample_layer))
    assert "MG" in hints["orders.customers"]["customer_state"]
    assert "paid_search" in hints["marketing.marketing_qualified_leads"]["origin"]
    assert "boleto" in hints["payments.order_payments"]["payment_type"]
    assert "delivered" in hints["orders.orders"]["order_status"]
    assert set(hints["marketing.closed_deals"]["business_segment"]).isdisjoint({"paid_search", "paid-search"})
    # High-cardinality text: count, case and examples, not the whole list.
    city = hints["orders.customers"]["customer_city"]
    assert isinstance(city, str) and "lower case" in city and "'rio de janeiro'" in city
    assert "32-char hex id" in hints["orders.orders"]["order_id"]
    assert "free text" in hints["reviews.order_reviews"]["review_comment_message"]
    assert vh._size(hints) <= vh.MAX_HINT_CHARS


def test_value_hints_take_no_query_id_and_write_no_query_log(tmp_path: Path) -> None:
    with LocalDataLayer(run_id="p", log_dir=tmp_path / "logs", settings=settings_for(tmp_path),
                        sources=("payments",)) as data:
        hints = vh.build_value_hints(data, schemas_of(data))
        assert hints["payments.order_payments"]["payment_type"]
        assert data.log.read() == []
        assert data.query(None, "SELECT 1 AS x").query_id == "q001"


class CountingLayer(DataLayer):
    """A local layer that counts profile calls."""

    adapter_name = "counting"

    def __init__(self, inner: LocalDataLayer) -> None:
        self.inner = inner
        self.profiles = 0

    def list_sources(self) -> list[str]:
        return self.inner.list_sources()

    def describe(self, source: str) -> SourceInfo:
        return self.inner.describe(source)

    def query(self, source: str | None, sql: str, limit: int | None = None,
              timeout: float | None = None) -> QueryOutcome:
        return self.inner.query(source, sql, limit, timeout)

    def profile(self, sql: str, limit: int) -> QueryOutcome:
        self.profiles += 1
        return self.inner.profile(sql, limit)


def test_value_hints_are_built_once_per_schema(tmp_path: Path) -> None:
    vh.clear_cache()
    with LocalDataLayer(run_id="c", log_dir=tmp_path / "logs", settings=settings_for(tmp_path),
                        sources=("payments",)) as inner:
        layer = CountingLayer(inner)
        schemas = schemas_of(layer)
        first = vh.value_hints(layer, schemas)
        calls = layer.profiles
        assert calls > 0
        assert vh.value_hints(layer, schemas) == first
        assert layer.profiles == calls
    vh.clear_cache()


def test_cap_summarises_long_lists_then_drops_trailing_columns() -> None:
    hints = {"a.t": {"short": ["x", "y"], "long": [f"value_{i:03d}" for i in range(60)]},
             "b.t": {"other": "5 distinct, lower case, e.g. 'p', 'q', 'r'"}}
    capped = vh.cap(hints, 200)
    assert capped["a.t"]["short"] == ["x", "y"]
    assert isinstance(capped["a.t"]["long"], str) and capped["a.t"]["long"].startswith("60 distinct")
    assert vh._size(capped) <= 200
    tiny = vh.cap(hints, 40)
    assert vh._size(tiny) <= 40 and "b.t" not in tiny
    assert hints["a.t"]["long"][0] == "value_000"  # the input is not changed


def test_source_schemas_carry_values_only_with_ground_filters(sample_layer: LocalDataLayer, tmp_path: Path) -> None:
    def ctx(ground: bool) -> AgentContext:
        return AgentContext(run_id="s", generate=None, data=sample_layer, trace=None, budget=None,  # type: ignore[arg-type]
                            ground_filters=ground)

    plain = {t["table"]: t for s in ctx(False).source_schemas() for t in s["tables"]}
    grounded = {t["table"]: t for s in ctx(True).source_schemas() for t in s["tables"]}
    assert all("values" not in t for t in plain.values())
    assert "MG" in grounded["orders.customers"]["values"]["customer_state"]
    assert {k: v for k, v in grounded["orders.customers"].items() if k != "values"} == plain["orders.customers"]


# --- what counts as "matched no records" -----------------------------------------------------------


def _result(rows: list[dict[str, Any]], columns: list[str] | None = None) -> QueryResult:
    return QueryResult(query_id="q1", source=None, sql="SELECT", adapter="local",
                       columns=columns if columns is not None else list(rows[0]) if rows else ["value"],
                       rows=rows, row_count=len(rows), truncated=False, duration_ms=0.0)


@pytest.mark.parametrize(("rows", "empty"), [
    ([], True),
    ([{"value": None, "baseline": None}], True),
    ([{"value": None, "baseline": 0.0}], True),  # the late-June revenue run: baseline 0.0, observed null
    ([{"value": None, "baseline": None, "spread": None, "n": 0}], True),
    ([{"value": 0, "baseline": 0}], False),  # zero in both windows is a measurement
    ([{"value": None, "baseline": 512.3}], False),  # a drop to nothing is a real change
    ([{"value": 3.1, "baseline": None}], False),
    ([{"cohort": "2018-03", "revenue": None}], False),  # no value column: cannot tell
])
def test_matched_nothing(rows: list[dict[str, Any]], empty: bool) -> None:
    assert (matched_nothing(_result(rows)) is not None) is empty


# --- the four real-run cases, one investigation each ------------------------------------------------

MG_SHARE = (
    "SELECT round(avg(CASE WHEN p.payment_type = 'boleto' THEN 1.0 ELSE 0.0 END) "
    "FILTER (WHERE o.order_purchase_timestamp >= DATE '2018-03-01'), 4) AS value, "
    "round(avg(CASE WHEN p.payment_type = 'boleto' THEN 1.0 ELSE 0.0 END) "
    "FILTER (WHERE o.order_purchase_timestamp < DATE '2018-03-01'), 4) AS baseline "
    "FROM orders.orders o JOIN orders.customers c ON c.customer_id = o.customer_id "
    "JOIN payments.order_payments p ON p.order_id = o.order_id "
    "WHERE {where} AND o.order_purchase_timestamp >= DATE '2018-02-01' "
    "AND o.order_purchase_timestamp < DATE '2018-04-01'"
)
FREIGHT = (
    "SELECT round(avg(i.freight_value) FILTER (WHERE o.order_purchase_timestamp >= DATE '2018-08-01'), 4) AS value, "
    "round(avg(i.freight_value) FILTER (WHERE o.order_purchase_timestamp < DATE '2018-08-01'), 4) AS baseline "
    "FROM orders.orders o JOIN orders.customers c ON c.customer_id = o.customer_id "
    "JOIN orders.order_items i ON i.order_id = o.order_id "
    "WHERE {where} AND o.order_purchase_timestamp >= DATE '2018-07-01' "
    "AND o.order_purchase_timestamp < DATE '2018-09-01'"
)
LATE_JUNE_REVENUE = (
    "SELECT round(sum(p.payment_value) FILTER (WHERE o.order_purchase_timestamp >= DATE '2018-06-12') / 19, 2) "
    "AS value, round(coalesce(sum(p.payment_value) FILTER (WHERE o.order_purchase_timestamp < DATE '2018-06-12'), "
    "0) / 11, 2) AS baseline "
    "FROM orders.orders o JOIN orders.customers c ON c.customer_id = o.customer_id "
    "JOIN payments.order_payments p ON p.order_id = o.order_id "
    "WHERE {where} AND o.order_purchase_timestamp >= DATE '2018-06-01' "
    "AND o.order_purchase_timestamp < DATE '2018-07-01'"
)
COHORT = (
    "SELECT date_trunc('month', d.won_date) AS cohort, count(DISTINCT d.seller_id) AS sellers, "
    "round(sum(i.price), 2) AS revenue FROM marketing.closed_deals d {join}"
    "JOIN orders.order_items i ON i.seller_id = d.seller_id "
    "WHERE {where} AND d.won_date >= DATE '2018-01-01' AND d.won_date < DATE '2018-04-01' GROUP BY 1 ORDER BY 1"
)
DISTINCT_STATES = "SELECT DISTINCT customer_state FROM orders.customers ORDER BY 1 LIMIT 50"


@dataclass(frozen=True)
class RealRunCase:
    name: str
    question: str
    window: tuple[str, str]
    baseline: tuple[str, str]
    wrong_sql: str
    check_sql: str
    fixed_sql: str
    stored: str  # the stored value the check shows and the corrected query uses


CASES = [
    RealRunCase(
        "boleto_share_state_full_name",
        "Why did the share of boleto payments fall in Minas Gerais in March 2018?",
        ("2018-03-01", "2018-04-01"), ("2018-02-01", "2018-03-01"),
        MG_SHARE.format(where="c.customer_state = 'Minas Gerais'"), DISTINCT_STATES,
        MG_SHARE.format(where="c.customer_state = 'MG'"), "MG",
    ),
    RealRunCase(
        "freight_state_question_on_city_column",
        "Why did average freight cost for Rio de Janeiro orders rise in August 2018?",
        ("2018-08-01", "2018-09-01"), ("2018-07-01", "2018-08-01"),
        FREIGHT.format(where="c.customer_city = 'Rio de Janeiro'"), DISTINCT_STATES,
        FREIGHT.format(where="c.customer_state = 'RJ'"), "RJ",
    ),
    RealRunCase(
        "late_june_revenue_city_filter",
        "Why did Rio de Janeiro's total revenue drop in late June 2018 (12-30 Jun, vs 1-11 Jun)?",
        ("2018-06-12", "2018-07-01"), ("2018-06-01", "2018-06-12"),
        LATE_JUNE_REVENUE.format(where="c.customer_city = 'Rio de Janeiro'"), DISTINCT_STATES,
        LATE_JUNE_REVENUE.format(where="c.customer_state = 'RJ'"), "RJ",
    ),
    RealRunCase(
        "paid_search_cohort_on_business_segment",
        "Why didn't the March 2018 paid-search seller cohort's revenue ramp up the way earlier cohorts did?",
        ("2018-03-01", "2018-04-01"), ("2018-01-01", "2018-03-01"),
        COHORT.format(join="", where="d.business_segment = 'paid-search'"),
        "SELECT DISTINCT origin FROM marketing.marketing_qualified_leads ORDER BY 1 LIMIT 50",
        COHORT.format(join="JOIN marketing.marketing_qualified_leads m ON m.mql_id = d.mql_id ",
                      where="m.origin = 'paid_search'"),
        "paid_search",
    ),
]


def plan_for(case: RealRunCase) -> Plan:
    hypothesis = Hypothesis(id="H1", family="mix_shift", statement="The mix changed.", priority=1,
                            test={"description": "the measure in the segment", "sources": ["orders"]})
    return Plan(question=case.question, metric="the measure", segment="the segment in the question",
                window={"start": case.window[0], "end": case.window[1]},
                baseline_window={"start": case.baseline[0], "end": case.baseline[1]},
                change_check={"description": "the measure in the window against the baseline"},
                hypotheses=[hypothesis, hypothesis.model_copy(update={"id": "H2", "priority": 2})])


class InvestigatorScript:
    """Scripted Investigator replies: the wrong query first, then the stored-values check, then the
    corrected query (`fixed`), recording what each request carried."""

    def __init__(self, wrong: str, check: str, fixed: str) -> None:
        self.wrong, self.check, self.fixed = wrong, check, fixed
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, messages: Any, *, schema: Any = None, role: str = "default",
                 run_id: Any = None) -> GenerationResult:
        data = parse_input(messages)
        self.requests.append((schema.__name__, messages[0]["content"], data))
        if schema is SqlProposal:
            sql = self.fixed if "value_check" in data else self.check if "previous_result" in data else self.wrong
            reply: dict[str, Any] = {"sql": sql, "sources": [], "rationale": "scripted"}
        else:
            assert schema is ObservationDraft
            row = data["rows"][-1]
            value = row.get("value", row.get("revenue"))
            reply = {"finding": f"Rows: {json.dumps(data['rows'][:3])}", "value": value,
                     "baseline": row.get("baseline"), "supports": True}
        return GenerationResult(ok=True, content=json.dumps(reply), parsed=reply, provider="stub")


def context_for(tmp_path: Path, data: DataLayer, generate: Callable[..., GenerationResult], *,
                max_tool_calls: int = 10, ground: bool = True) -> AgentContext:
    return AgentContext(run_id="g", generate=generate, data=data, trace=TraceWriter(tmp_path / "logs", "g"),
                        budget=Budget(8, max_tool_calls), ground_filters=ground)


def actions(tmp_path: Path) -> list[str]:
    return [line["action"] for line in TraceWriter(tmp_path / "logs", "g").read()]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_real_run_case_wrong_value_is_checked_and_corrected(case: RealRunCase, sample_layer: LocalDataLayer,
                                                            tmp_path: Path) -> None:
    script = InvestigatorScript(case.wrong_sql, case.check_sql, case.fixed_sql)
    ctx = context_for(tmp_path, sample_layer, script)
    outcome = investigate(ctx, plan_for(case), plan_for(case).hypotheses[0], "obs-1", context="Goal: explain.")

    # wrong value -> empty -> stored-values check -> corrected query -> numbers
    assert actions(tmp_path) == ["write_sql", "run_query", "empty_result", "check_values", "run_query",
                                 "rewrite_sql", "run_query", "grounded", "observe"]
    assert len(outcome.query_ids) == 3 and ctx.budget.tool_calls_used == 3
    obs = outcome.observation
    assert obs is not None and not outcome.no_records
    assert obs.sql == case.fixed_sql and obs.value is not None
    assert obs.query_id == outcome.query_ids[-1]

    # The first request already listed the stored value next to the schema, with the mapping note.
    first_kind, first_prompt, first = script.requests[0]
    assert first_kind == "SqlProposal" and load_prompt("value_hints_note") in first_prompt
    assert case.stored in json.dumps(first["sources"])
    # The check had its own prompt; the rewrite saw the stored value in the check's rows.
    assert script.requests[1][1] == load_prompt("investigator_check_values")
    rewrite = script.requests[2][2]
    assert rewrite["previous_sql"] == case.wrong_sql and rewrite["previous_result"].startswith("no records")
    assert any(case.stored in row.values() for row in rewrite["value_check"]["rows"])
    assert load_prompt("investigator_rewrite_note") in script.requests[2][1]


def test_still_empty_after_the_check_is_recorded_as_no_records(sample_layer: LocalDataLayer, tmp_path: Path) -> None:
    case = CASES[0]
    script = InvestigatorScript(case.wrong_sql, case.check_sql, case.wrong_sql)  # the rewrite keeps the wrong value
    ctx = context_for(tmp_path, sample_layer, script)
    outcome = investigate(ctx, plan_for(case), plan_for(case).hypotheses[0], "obs-1")
    obs = outcome.observation
    assert outcome.no_records and obs is not None
    assert obs.finding.startswith(NO_RECORDS_FINDING) and "not a small sample" in obs.finding
    assert obs.value is None and obs.baseline is None and obs.supports is None
    assert actions(tmp_path)[-2:] == ["grounded", "observe"]
    assert [r[0] for r in script.requests] == ["SqlProposal"] * 3  # no observe call on an empty result
    assert ctx.budget.tool_calls_used == 3  # one retry per measurement, no more


def test_the_retry_respects_the_tool_call_cap(sample_layer: LocalDataLayer, tmp_path: Path) -> None:
    case = CASES[0]
    ctx = context_for(tmp_path, sample_layer, InvestigatorScript(case.wrong_sql, case.check_sql, case.fixed_sql),
                      max_tool_calls=1)
    outcome = investigate(ctx, plan_for(case), plan_for(case).hypotheses[0], "obs-1")
    assert outcome.tool_cap_reached and outcome.no_records
    assert ctx.budget.tool_calls_used == 1
    assert "cap_reached" in [line["status"] for line in TraceWriter(tmp_path / "logs", "g").read()]


def test_without_ground_filters_an_empty_result_is_read_as_before(sample_layer: LocalDataLayer,
                                                                  tmp_path: Path) -> None:
    case = CASES[0]
    script = InvestigatorScript(case.wrong_sql, case.check_sql, case.fixed_sql)
    ctx = context_for(tmp_path, sample_layer, script, ground=False)
    outcome = investigate(ctx, plan_for(case), plan_for(case).hypotheses[0], "obs-1")
    assert actions(tmp_path) == ["write_sql", "run_query", "observe"]
    assert not outcome.no_records and outcome.observation is not None
    assert "values" not in json.dumps(script.requests[0][2]["sources"])
    assert load_prompt("value_hints_note") not in script.requests[0][1]


# --- the orchestrator -----------------------------------------------------------------------------


def config() -> MarkovianConfig:
    return MarkovianConfig(max_chunks=8, chunk_budget_chars=12000, carryover_budget_chars=1200,
                           chunk_timeout_seconds=60.0, compression_timeout_seconds=5.0, run_timeout_s=120.0)


def zero_sample_critique(hypothesis_id: str, attempt: int) -> dict[str, Any]:
    """The real-run Critic reply: the sample is 0 records, below the minimum."""
    checks = [{"name": n, "outcome": "failed" if n == "sample_size" else "not_checked", "detail": "0 records"}
              for n in ("alternative_cause", "concentration", "sample_size", "date_basis", "data_artefact")]
    return {"checks": checks, "scores": {"supported_by_data": 0, "explains_size_and_timing": 0,
                                         "alternatives_excluded": 0},
            "contradicted": False, "reason": "There are no records behind the change.", "follow_up_tests": [],
            "observation_ids": [], "sample_size": 0}


class WrongFilter(ScriptedModel):
    """The scripted stub, but the first query for `targets` filters on a value that is not stored
    (title case). With `fix`, the rewrite after the stored-values check drops the wrong filter. The
    Critic, if `zero_sample`, reports a sample of 0 records."""

    def __init__(self, targets: set[str], *, fix: bool, zero_sample: bool = False) -> None:
        super().__init__()
        self.targets, self.fix, self.zero_sample = targets, fix, zero_sample
        self.value_checks: list[dict[str, Any]] = []

    def __call__(self, messages: Any, *, schema: Any = None, role: str = "default", run_id: Any = None) -> Any:
        if schema is CritiqueDraft and self.zero_sample:
            body = parse_input(messages)
            reply = zero_sample_critique(body["hypothesis"]["id"], body["attempt"])
            return GenerationResult(ok=True, content=json.dumps(reply), provider="stub",
                                    parsed=CritiqueDraft.model_validate(reply).model_dump(mode="json"))
        return super().__call__(messages, schema=schema, role=role, run_id=run_id)

    def _reply_SqlProposal(self, data: dict[str, Any]) -> dict[str, Any] | None:
        target = data.get("task", {}).get("id") or "change_check"
        if target in self.targets and "previous_result" not in data:
            reply = super()._reply_SqlProposal(data)
            assert reply is not None and " WHERE o.order_purchase_timestamp" in reply["sql"]
            return {**reply, "sql": reply["sql"].replace(" WHERE o.order_purchase_timestamp",
                                                         f" WHERE {WRONG_STATUS}o.order_purchase_timestamp", 1)}
        if target in self.targets and "value_check" in data:
            self.value_checks.append(data["value_check"])
            if self.fix:
                return {"sql": data["previous_sql"].replace(WRONG_STATUS, ""),
                        "sources": ["orders"], "rationale": "Filter on stored values only."}
        return super()._reply_SqlProposal(data)


def orchestrate(tmp_path: Path, generate: Any, **kwargs: Any) -> tuple[Result, list[dict[str, Any]]]:
    settings = settings_for(tmp_path)
    with LocalDataLayer(run_id="o", log_dir=tmp_path / "logs", settings=settings) as data:
        result = run_markovian(DAY1, run_id="o", generate=generate, data=data, settings=settings, config=config(),
                               log_dir=tmp_path / "logs", **kwargs)
    Result.model_validate(result.model_dump())
    return result, TraceWriter(tmp_path / "logs", "o").read()


def test_orchestrated_change_check_with_a_wrong_value_is_corrected(tmp_path: Path) -> None:
    script = WrongFilter({"change_check"}, fix=True)
    result, lines = orchestrate(tmp_path, script)
    assert result.status == "success", result.error
    assert result.change is not None and result.change.observed is not None and result.change.baseline is not None
    assert result.change.significant is True
    assert any("delivered" in row.values() for row in script.value_checks[0]["rows"])
    steps = [line["action"] for line in lines if line["agent"] == "Investigator"][:8]
    assert steps == ["write_sql", "run_query", "empty_result", "check_values", "run_query", "rewrite_sql",
                     "run_query", "grounded"]
    assert not any(line["action"] == "ignore_sample_flag" for line in lines)


def test_orchestrated_no_records_is_not_reported_as_a_small_sample(tmp_path: Path) -> None:
    script = WrongFilter({"change_check", "H1"}, fix=False, zero_sample=True)
    result, lines = orchestrate(tmp_path, script)
    assert result.status == "success", result.error
    assert result.determinable is False and result.causes == []
    assert "sample" not in (result.summary or "").lower()
    assert not any(item.startswith("Sample too small") for item in result.limitations)
    assert any(item.startswith("Change check not measured: Filter matched no records") for item in result.limitations)
    assert any(item.startswith("Not measured: H1") for item in result.limitations)
    ignored = [line for line in lines if line["action"] == "ignore_sample_flag"]
    assert ignored and all(line["sample_size"] == 0 for line in ignored)
    critiques = [line for line in lines if line["agent"] == "Critic" and line["action"] == "critique"]
    assert critiques and all(line["sample_too_small"] is False for line in critiques)
    assert all(json.loads(line["output_summary"])["reason"].startswith("Filter matched no records")
               for line in critiques)
    # Every hypothesis was still tested: the run did not stop at a sample flag.
    assert {line["hypothesis_id"] for line in critiques} == {"H1", "H2", "H3", "H4"}
    skipped = [line for line in lines if line["action"] == "skip_revision" and line["hypothesis_id"] == "H1"]
    assert skipped and "filter matched no records" in skipped[0]["output_summary"]
    branch = [line for line in lines if line["action"] == "branch"][-1]
    assert branch["branch"] == "cannot_be_determined" and branch["numbers"]["sample_size"] is None


def test_a_real_zero_sample_still_flags_when_the_filter_matched_records(tmp_path: Path) -> None:
    """The sample flag is only set aside for an observation that matched no records."""
    result, lines = orchestrate(tmp_path, WrongFilter(set(), fix=False, zero_sample=True))
    assert not any(line["action"] == "ignore_sample_flag" for line in lines)
    assert any(item.startswith("Sample too small") for item in result.limitations)

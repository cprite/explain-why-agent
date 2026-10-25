"""A deterministic, scripted stand-in for the model, used to record the sample-mode cache without a
model key and as the stubbed generator in tests.

It answers the four agent reply schemas for two generic question shapes:

- "why did order volume change on <date>?": the day against the seven days before it, testing a
  broad rise across sellers, a price drop, a single seller and duplicate records;
- "why did delivery lateness change for deliveries completed <date> / the week of <date>?" (any
  question naming lateness or late deliveries): the share of deliveries completed after their
  estimated date, in that day or week against the four weeks before, testing longer carrier transit,
  more deliveries than usual, a single seller and invalid delivery dates.

Since Sprint 9 it also answers three more generic shapes and the Critic:

- "why did review scores (for <category> | for seller <id>) fall in <month> / early <month>?": the
  average review score by order purchase date, in that month (or its first half) against the periods
  before, testing longer deliveries, products rated lower even when delivered on time, one seller (or,
  for a seller, a jump in its order volume) and duplicate or missing reviews;
- "why has average order value been declining since <month>?": payments per order two months later
  against that month and the next, testing lower item prices, fewer items per order, one seller and
  orders with missing payments;
- the Critic (`CritiqueDraft`): a fixed rule on the Investigator's reading. A refuting reading is
  contradicted; an effect of 30 % or more is supported (8 of 9); a smaller effect is insufficient
  (5 of 9) with one timing follow-up test (the same measure on the second half of the window), and
  supported on the second critique only if that follow-up shows 30 % or more. Fewer records behind
  the change than `min_sample_size` (the change check's `n` column) fails the sample-size check.

Since Sprint 11d it answers the empty-result retry generically: the stored-values check lists the
values of the first column the query compared with a literal, and the rewrite returns the query
unchanged, so a filter that matched nothing ends as "Filter matched no records".

Every change check also returns `spread` (the standard deviation of the measure across baseline
periods as long as the window) and `n` (records in the window).

It reads the date from the question (any "<day> <Month> <year>", ISO date, "<Month> <year>" or
"YYYY-MM"). It knows nothing about the planted incidents. Its replies are what a model would return; the agents, queries and loop around it run
for real. Cache entries recorded with it are marked `"recorded_with": "stub"` and are replaced by a
real recording through Meterless (`RECORD_CACHE=true`).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.base import parse_input
from app.llm.generator import GenerationResult, Message

STUB_MODEL = "scripted-stub"
MONTHS = {
    name: number
    for number, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august", "september",
         "october", "november", "december"],
        start=1,
    )
}


def question_date(question: str) -> date | None:
    """The first date in a question, written as an ISO date or as '<day> <Month> <year>'."""
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", question)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    spoken = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", question)
    if spoken and spoken.group(2).lower() in MONTHS:
        return date(int(spoken.group(3)), MONTHS[spoken.group(2).lower()], int(spoken.group(1)))
    return None


def question_month(question: str) -> date | None:
    """The first month in a question, written as 'YYYY-MM' or '<Month> <year>' (its first day)."""
    iso = re.search(r"\b(\d{4})-(\d{2})\b(?!-\d)", question)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), 1)
    for match in re.finditer(r"\b([A-Za-z]+)\s+(\d{4})\b", question):
        if match.group(1).lower() in MONTHS:
            return date(int(match.group(2)), MONTHS[match.group(1).lower()], 1)
    return None


def add_months(day: date, months: int) -> date:
    """The first day of the month `months` after (or before) `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _daily(expr: str, joins: str) -> str:
    """SQL: a per-day measure, averaged over the window and over the baseline."""
    return (
        f"WITH d AS (SELECT CAST(o.order_purchase_timestamp AS DATE) AS day, {expr} AS m "
        f"FROM orders.orders o {joins} "
        "WHERE o.order_purchase_timestamp >= DATE '{b0}' AND o.order_purchase_timestamp < DATE '{w1}' "
        "GROUP BY 1) "
        "SELECT round(avg(m) FILTER (WHERE day >= DATE '{w0}'), 4) AS value, "
        "round(avg(m) FILTER (WHERE day < DATE '{w0}'), 4) AS baseline FROM d"
    )


SQL_TEMPLATES: dict[str, str] = {
    "change_check": _daily("count(DISTINCT o.order_id)", "").replace(
        " AS baseline FROM d",
        " AS baseline, round(stddev_samp(m) FILTER (WHERE day < DATE '{w0}'), 4) AS spread, "
        "sum(m) FILTER (WHERE day >= DATE '{w0}') AS n FROM d",
    ),
    "volume": _daily("count(DISTINCT i.seller_id)", "JOIN orders.order_items i ON i.order_id = o.order_id"),
    "price_discount": (
        "SELECT round(avg(i.price) FILTER (WHERE o.order_purchase_timestamp >= DATE '{w0}'), 4) AS value, "
        "round(avg(i.price) FILTER (WHERE o.order_purchase_timestamp < DATE '{w0}'), 4) AS baseline "
        "FROM orders.orders o JOIN orders.order_items i ON i.order_id = o.order_id "
        "WHERE o.order_purchase_timestamp >= DATE '{b0}' AND o.order_purchase_timestamp < DATE '{w1}'"
    ),
    "single_seller": (
        "WITH s AS (SELECT o.order_purchase_timestamp >= DATE '{w0}' AS in_window, i.seller_id, "
        "count(DISTINCT o.order_id) AS n FROM orders.orders o "
        "JOIN orders.order_items i ON i.order_id = o.order_id "
        "WHERE o.order_purchase_timestamp >= DATE '{b0}' AND o.order_purchase_timestamp < DATE '{w1}' "
        "GROUP BY 1, 2) "
        "SELECT round(max(n) FILTER (WHERE in_window) / sum(n) FILTER (WHERE in_window), 4) AS value, "
        "round(max(n) FILTER (WHERE NOT in_window) / sum(n) FILTER (WHERE NOT in_window), 4) AS baseline FROM s"
    ),
    "data_artefact": (
        "SELECT count(*) FILTER (WHERE order_purchase_timestamp >= DATE '{w0}') "
        "- count(DISTINCT order_id) FILTER (WHERE order_purchase_timestamp >= DATE '{w0}') AS value, "
        "count(*) FILTER (WHERE order_purchase_timestamp < DATE '{w0}') "
        "- count(DISTINCT order_id) FILTER (WHERE order_purchase_timestamp < DATE '{w0}') AS baseline "
        "FROM orders.orders "
        "WHERE order_purchase_timestamp >= DATE '{b0}' AND order_purchase_timestamp < DATE '{w1}'"
    ),
}

UNTESTED_NOTE = (
    "Only order, seller and price measures were tested; promotions and campaigns are not recorded in the data."
)

LATENESS_FILTER = (
    "o.order_status = 'delivered' AND o.order_delivered_customer_date >= DATE '{b0}' "
    "AND o.order_delivered_customer_date < DATE '{w1}'"
)
LATE = "CAST(o.order_delivered_customer_date AS DATE) > CAST(o.order_estimated_delivery_date AS DATE)"
IN_WINDOW = "o.order_delivered_customer_date >= DATE '{w0}'"


def _window_avg(expr: str, joins: str = "", where: str = "") -> str:
    """SQL: the average of a per-delivery measure in the window and in the baseline."""
    return (
        f"SELECT round(avg({expr}) FILTER (WHERE {IN_WINDOW}), 4) AS value, "
        f"round(avg({expr}) FILTER (WHERE NOT ({IN_WINDOW})), 4) AS baseline "
        f"FROM orders.orders o {joins}WHERE {LATENESS_FILTER}{where}"
    )


LATENESS_SQL_TEMPLATES: dict[str, str] = {
    "change_check": _window_avg(f"CASE WHEN {LATE} THEN 1.0 ELSE 0.0 END").replace(
        " AS baseline FROM orders.orders o ",
        f" AS baseline, (SELECT round(stddev_samp(m), 4) FROM (SELECT avg(CASE WHEN {LATE} THEN 1.0 ELSE 0.0 END) "
        f"AS m FROM orders.orders o WHERE {LATENESS_FILTER} AND NOT ({IN_WINDOW}) GROUP BY "
        "floor(date_diff('day', DATE '{b0}', CAST(o.order_delivered_customer_date AS DATE)) / {wd}))) AS spread, "
        f"count(*) FILTER (WHERE {IN_WINDOW}) AS n FROM orders.orders o ",
    ),
    "logistics_delay": _window_avg(
        "date_diff('hour', o.order_delivered_carrier_date, o.order_delivered_customer_date) / 24.0",
        where=" AND o.order_delivered_carrier_date IS NOT NULL",
    ),
    "volume": (
        f"SELECT round(count(*) FILTER (WHERE {IN_WINDOW}) / {{wd}}, 4) AS value, "
        f"round(count(*) FILTER (WHERE NOT ({IN_WINDOW})) / {{bd}}, 4) AS baseline "
        f"FROM orders.orders o WHERE {LATENESS_FILTER}"
    ),
    "single_seller": (
        f"WITH s AS (SELECT {IN_WINDOW} AS in_window, i.seller_id, count(DISTINCT o.order_id) AS n "
        "FROM orders.orders o JOIN orders.order_items i ON i.order_id = o.order_id "
        f"WHERE {LATENESS_FILTER} AND {LATE} GROUP BY 1, 2) "
        "SELECT round(max(n) FILTER (WHERE in_window) / sum(n) FILTER (WHERE in_window), 4) AS value, "
        "round(max(n) FILTER (WHERE NOT in_window) / sum(n) FILTER (WHERE NOT in_window), 4) AS baseline FROM s"
    ),
    "data_artefact": (
        "SELECT count(*) FILTER (WHERE {invalid} AND " + IN_WINDOW + ") AS value, "
        "count(*) FILTER (WHERE {invalid} AND NOT (" + IN_WINDOW + ")) AS baseline "
        "FROM orders.orders o WHERE " + LATENESS_FILTER
    ).replace(
        "{invalid}",
        "(o.order_estimated_delivery_date IS NULL OR o.order_delivered_customer_date < o.order_purchase_timestamp)",
    ),
}

LATENESS_UNTESTED_NOTE = (
    "Only delivery timing, delivery volume, seller and date-quality measures were tested; carrier "
    "capacity, strikes and weather are not recorded in the data."
)

LATENESS_LABELS = {
    "change_check": "Share of deliveries completed late",
    "logistics_delay": "Average days from carrier hand-off to delivery",
    "volume": "Deliveries completed per day",
    "single_seller": "Largest single seller's share of late deliveries",
    "data_artefact": "Deliveries with a missing or impossible date",
}


def is_lateness(text: str) -> bool:
    """True for a question (or a plan metric) about late deliveries."""
    return re.search(r"\blate(?:ness)?\b|\bdelivered after\b", text, re.IGNORECASE) is not None


LABELS = {
    "change_check": "Orders per day",
    "volume": "Distinct sellers with orders per day",
    "price_discount": "Average item price",
    "single_seller": "Largest single seller's share of orders",
    "data_artefact": "Duplicate order rows",
}


def _supports_lateness(kind: str, value: float | None, effect: float | None) -> bool | None:
    if value is None:
        return None
    if kind == "change_check":
        return effect is not None and effect > 0.5
    if kind in ("logistics_delay", "volume"):
        return effect is not None and effect > 0.2
    if kind == "single_seller":
        return value > 0.5
    if kind == "data_artefact":
        return value > 0
    return None


def _supports(kind: str, value: float | None, baseline: float | None, effect: float | None) -> bool | None:
    if value is None:
        return None
    if kind in ("change_check", "volume"):
        return effect is not None and effect > 0.5
    if kind == "price_discount":
        return effect is not None and effect < -0.03
    if kind == "single_seller":
        return value > 0.5
    if kind == "data_artefact":
        return value > 0
    return None


# --- Review scores (Sprint 9) --------------------------------------------------------------------

REVIEWS = (
    "WITH r AS (SELECT o.order_id, CAST(o.order_purchase_timestamp AS DATE) AS day, "
    "o.order_purchase_timestamp AS ts, o.order_delivered_customer_date AS delivered, "
    "o.order_estimated_delivery_date AS estimated, avg(rv.review_score) AS score, count(*) AS reviews "
    "FROM orders.orders o JOIN reviews.order_reviews rv ON rv.order_id = o.order_id "
    "WHERE {seg} AND o.order_purchase_timestamp >= DATE '{b0}' AND o.order_purchase_timestamp < DATE '{w1}' "
    "GROUP BY 1, 2, 3, 4, 5) "
)
R_WIN = "day >= DATE '{w0}'"


def _r_avg(expr: str, where: str = "") -> str:
    """SQL: the average of a per-order measure over reviewed orders, in the window and in the baseline."""
    extra = f" AND {where}" if where else ""
    return (
        REVIEWS + f"SELECT round(avg({expr}) FILTER (WHERE {R_WIN}{extra}), 4) AS value, "
        f"round(avg({expr}) FILTER (WHERE NOT ({R_WIN}){extra}), 4) AS baseline FROM r"
    )


def _spread(cte_rows: str, expr: str, day: str = "day") -> str:
    """SQL: the standard deviation of a measure across baseline periods as long as the window."""
    return (
        f"(SELECT round(stddev_samp(m), 4) FROM (SELECT avg({expr}) AS m FROM {cte_rows} WHERE {day} < DATE '{{w0}}' "
        f"GROUP BY floor(date_diff('day', DATE '{{b0}}', {day}) / {{wd}}))) AS spread"
    )


REVIEW_SQL_TEMPLATES: dict[str, str] = {
    "change_check": (
        REVIEWS + f"SELECT round(avg(score) FILTER (WHERE {R_WIN}), 4) AS value, "
        f"round(avg(score) FILTER (WHERE NOT ({R_WIN})), 4) AS baseline, {_spread('r', 'score')}, "
        f"count(*) FILTER (WHERE {R_WIN}) AS n FROM r"
    ),
    "logistics_delay": _r_avg("date_diff('hour', ts, delivered) / 24.0", "delivered IS NOT NULL"),
    "product_quality": _r_avg("score", "CAST(delivered AS DATE) <= CAST(estimated AS DATE)"),
    "single_seller": (
        "WITH low AS (SELECT o.order_purchase_timestamp >= DATE '{w0}' AS in_window, i.seller_id, "
        "count(DISTINCT o.order_id) AS n FROM orders.orders o "
        "JOIN reviews.order_reviews rv ON rv.order_id = o.order_id "
        "JOIN orders.order_items i ON i.order_id = o.order_id "
        "WHERE {seg} AND rv.review_score <= 2 AND o.order_purchase_timestamp >= DATE '{b0}' "
        "AND o.order_purchase_timestamp < DATE '{w1}' GROUP BY 1, 2) "
        "SELECT round(max(n) FILTER (WHERE in_window) / sum(n) FILTER (WHERE in_window), 4) AS value, "
        "round(max(n) FILTER (WHERE NOT in_window) / sum(n) FILTER (WHERE NOT in_window), 4) AS baseline FROM low"
    ),
    "volume": (
        REVIEWS + f"SELECT round(count(*) FILTER (WHERE {R_WIN}) / {{wd}}, 4) AS value, "
        f"round(count(*) FILTER (WHERE NOT ({R_WIN})) / {{bd}}, 4) AS baseline FROM r"
    ),
    "data_artefact": _r_avg("CASE WHEN reviews > 1 OR score IS NULL THEN 1.0 ELSE 0.0 END"),
}

REVIEW_LABELS = {
    "change_check": "Average review score",
    "logistics_delay": "Average days from purchase to delivery of reviewed orders",
    "product_quality": "Average review score of orders delivered on time",
    "single_seller": "Largest single seller's share of low-score (1-2) reviews",
    "volume": "Reviewed orders per day",
    "data_artefact": "Share of orders with duplicate or missing review scores",
}

REVIEW_UNTESTED_NOTE = (
    "Only delivery timing, on-time review scores, seller concentration and review-record quality were "
    "tested; review comment text and product details were not read."
)


def is_review_score(text: str) -> bool:
    """True for a question (or a plan metric) about review scores."""
    return re.search(r"\breview scores?\b", text, re.IGNORECASE) is not None


def segment_filter(segment: str) -> str:
    """SQL condition on `o` (orders) for a plan segment: 'seller <id>', 'category <name>' or 'all'."""
    seller = re.fullmatch(r"seller ([0-9a-f]+)", segment)
    if seller:
        return f"o.order_id IN (SELECT order_id FROM orders.order_items WHERE seller_id = '{seller.group(1)}')"
    category = re.fullmatch(r"category ([a-z_]+)", segment)
    if category:
        return ("o.order_id IN (SELECT i.order_id FROM orders.order_items i JOIN orders.products p "
                f"ON p.product_id = i.product_id WHERE p.product_category_name = '{category.group(1)}')")
    return "TRUE"


# --- Average order value (Sprint 9) ----------------------------------------------------------------

ORDER_VALUES = (
    "WITH pay AS (SELECT order_id, sum(payment_value) AS v FROM payments.order_payments GROUP BY 1), "
    "items AS (SELECT order_id, count(*) AS k, avg(price) AS price FROM orders.order_items GROUP BY 1), "
    "a AS (SELECT o.order_id, CAST(o.order_purchase_timestamp AS DATE) AS day, pay.v, items.k, items.price "
    "FROM orders.orders o LEFT JOIN pay ON pay.order_id = o.order_id "
    "LEFT JOIN items ON items.order_id = o.order_id "
    "WHERE o.order_purchase_timestamp >= DATE '{b0}' AND o.order_purchase_timestamp < DATE '{w1}') "
)
A_WIN = "day >= DATE '{w0}'"


def _a_avg(expr: str) -> str:
    return (
        ORDER_VALUES + f"SELECT round(avg({expr}) FILTER (WHERE {A_WIN}), 4) AS value, "
        f"round(avg({expr}) FILTER (WHERE NOT ({A_WIN})), 4) AS baseline FROM a"
    )


ORDER_VALUE_SQL_TEMPLATES: dict[str, str] = {
    "change_check": (
        ORDER_VALUES + f"SELECT round(avg(v) FILTER (WHERE {A_WIN}), 4) AS value, "
        f"round(avg(v) FILTER (WHERE NOT ({A_WIN})), 4) AS baseline, {_spread('a', 'v')}, "
        f"count(v) FILTER (WHERE {A_WIN}) AS n FROM a"
    ),
    "price_discount": _a_avg("price"),
    "mix_shift": _a_avg("k"),
    "single_seller": (
        "WITH s AS (SELECT o.order_purchase_timestamp >= DATE '{w0}' AS in_window, i.seller_id, "
        "sum(i.price) AS revenue FROM orders.orders o JOIN orders.order_items i ON i.order_id = o.order_id "
        "WHERE o.order_purchase_timestamp >= DATE '{b0}' AND o.order_purchase_timestamp < DATE '{w1}' "
        "GROUP BY 1, 2) "
        "SELECT round(max(revenue) FILTER (WHERE in_window) / sum(revenue) FILTER (WHERE in_window), 4) AS value, "
        "round(max(revenue) FILTER (WHERE NOT in_window) / sum(revenue) FILTER (WHERE NOT in_window), 4) "
        "AS baseline FROM s"
    ),
    "data_artefact": _a_avg("CASE WHEN v IS NULL OR v <= 0 OR k IS NULL THEN 1.0 ELSE 0.0 END"),
}

ORDER_VALUE_LABELS = {
    "change_check": "Average payments per order",
    "price_discount": "Average item price per order",
    "mix_shift": "Items per order",
    "single_seller": "Largest single seller's share of item revenue",
    "data_artefact": "Share of orders with missing or zero payments or no items",
}

ORDER_VALUE_UNTESTED_NOTE = (
    "Only item prices, items per order, seller concentration and payment-record quality were tested; "
    "causes outside the data (prices in the wider market, the economy) cannot be measured here."
)


def is_order_value(text: str) -> bool:
    """True for a question (or a plan metric) about average order value."""
    return re.search(r"\baverage order value\b", text, re.IGNORECASE) is not None


def _supports_reviews(kind: str, value: float | None, effect: float | None) -> bool | None:
    if value is None:
        return None
    if kind == "change_check":
        return effect is not None and abs(effect) > 0.1
    if kind in ("logistics_delay", "volume"):
        return effect is not None and effect > 0.2
    if kind == "product_quality":
        return effect is not None and effect < -0.1
    if kind == "single_seller":
        return value > 0.5
    if kind == "data_artefact":
        return value > 0.02 and (effect is None or effect > 0.5)
    return None


def _supports_order_value(kind: str, value: float | None, effect: float | None) -> bool | None:
    if value is None:
        return None
    if kind == "change_check":
        return effect is not None and abs(effect) > 0.05
    if kind in ("price_discount", "mix_shift"):
        return effect is not None and effect < -0.03
    if kind == "single_seller":
        return value > 0.5
    if kind == "data_artefact":
        return value > 0.02 and (effect is None or effect > 0.5)
    return None


SUPPORTED_EFFECT = 0.3
"""The scripted Critic supports a hypothesis whose measure moved by at least this much."""
TIMING_FOLLOW_UP = "Timing check: repeat the {family} measure on the second half of the window only, against the baseline."
SPLIT_FOLLOW_UP = "Split the {family} measure by state, category and seller to see whether one segment carries it."


def _shape(metric: str) -> str:
    """Which question shape a plan metric belongs to."""
    if is_lateness(metric):
        return "lateness"
    if is_review_score(metric):
        return "reviews"
    if is_order_value(metric):
        return "order_value"
    return "orders"


def _is_follow_up(task: dict[str, Any]) -> bool:
    """A revision task: the Critic's follow-up test (the orchestrator leads its description with it)."""
    return task.get("kind") == "hypothesis" and str((task.get("test") or {}).get("description", "")).startswith(
        "Follow-up requested by the Critic")


class ScriptedModel:
    """Callable with the `GenerateFn` signature; returns scripted replies."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        messages: list[Message],
        *,
        schema: type[BaseModel] | None = None,
        role: str = "default",
        run_id: str | None = None,
    ) -> GenerationResult:
        name = schema.__name__ if schema else None
        self.calls.append({"role": role, "schema": name, "messages": messages})
        handler = getattr(self, f"_reply_{name}", None) if name else None
        if handler is None:
            return GenerationResult(ok=False, provider="stub",
                                    error={"code": "stub_unscripted", "message": f"no script for {name}"})
        reply = handler(parse_input(messages))
        if reply is None:
            return GenerationResult(ok=False, provider="stub",
                                    error={"code": "stub_unscripted", "message": "the stub cannot answer this input"})
        content = json.dumps(reply)
        try:
            parsed = schema.model_validate(reply).model_dump(mode="json")
        except ValidationError as exc:  # a bug in the script, surfaced like a model error
            return GenerationResult(ok=False, provider="stub", content=content,
                                    error={"code": "invalid_json", "message": str(exc)})
        return GenerationResult(ok=True, content=content, parsed=parsed, provider="stub",
                                model_requested=role, model_routed=STUB_MODEL)

    # --- one handler per reply schema -------------------------------------------------------

    def _reply_Plan(self, data: dict[str, Any]) -> dict[str, Any] | None:
        question = str(data.get("question", ""))
        if is_review_score(question):
            return self._review_plan(question)
        if is_order_value(question):
            return self._order_value_plan(question)
        day = question_date(str(data.get("question", "")))
        if day is None:
            return None
        if is_lateness(str(data.get("question", ""))):
            return self._lateness_plan(str(data.get("question", "")), day)
        window = {"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()}
        baseline = {"start": (day - timedelta(days=7)).isoformat(), "end": day.isoformat()}
        test = {"sources": ["orders"]}
        return {
            "question": data.get("question", ""),
            "metric": "daily order count (distinct orders by purchase date)",
            "segment": "all",
            "window": window,
            "baseline_window": baseline,
            "change_check": {"description": "Orders per day in the window against the baseline average.", **test},
            "hypotheses": [
                {"id": "H1", "family": "volume", "priority": 1,
                 "statement": "The rise is broad: many more sellers than usual received orders.",
                 "test": {"description": "Distinct sellers with orders per day, window against baseline.", **test}},
                {"id": "H2", "family": "price_discount", "priority": 2,
                 "statement": "Average item prices fell in the window, consistent with a promotion.",
                 "test": {"description": "Average item price, window against baseline.", **test}},
                {"id": "H3", "family": "single_seller", "priority": 3,
                 "statement": "One seller accounts for most of the extra orders.",
                 "test": {"description": "Largest seller's share of orders, window against baseline.", **test}},
                {"id": "H4", "family": "data_artefact", "priority": 4,
                 "statement": "Duplicated order records inflate the count.",
                 "test": {"description": "Rows minus distinct order ids, window against baseline.", **test}},
            ],
        }

    @staticmethod
    def _lateness_plan(question: str, day: date) -> dict[str, Any]:
        days = 7 if re.search(r"\bweek\b", question, re.IGNORECASE) else 1
        window = {"start": day.isoformat(), "end": (day + timedelta(days=days)).isoformat()}
        baseline = {"start": (day - timedelta(days=28)).isoformat(), "end": day.isoformat()}
        test = {"sources": ["orders"]}
        return {
            "question": question,
            "metric": "share of deliveries completed late (delivered after the estimated delivery date)",
            "segment": "all",
            "window": window,
            "baseline_window": baseline,
            "change_check": {"description": "Late share of deliveries completed in the window against the baseline.",
                             **test},
            "hypotheses": [
                {"id": "H1", "family": "logistics_delay", "priority": 1,
                 "statement": "Deliveries took longer after hand-off to the carrier: transit time rose in the window.",
                 "test": {"description": "Average days from carrier hand-off to delivery, window against baseline.",
                          **test}},
                {"id": "H2", "family": "volume", "priority": 2,
                 "statement": "More deliveries than usual were completed in the window, straining delivery capacity.",
                 "test": {"description": "Deliveries completed per day, window against baseline.", **test}},
                {"id": "H3", "family": "single_seller", "priority": 3,
                 "statement": "One seller accounts for most of the late deliveries.",
                 "test": {"description": "Largest seller's share of late deliveries, window against baseline.",
                          **test}},
                {"id": "H4", "family": "data_artefact", "priority": 4,
                 "statement": "Missing or impossible delivery dates inflate the late count.",
                 "test": {"description": "Deliveries with a missing estimate or delivered before purchase.", **test}},
            ],
        }

    @staticmethod
    def _review_plan(question: str) -> dict[str, Any] | None:
        month = question_month(question)
        if month is None:
            return None
        seller = re.search(r"\bseller\s+([0-9a-f]{32})\b", question)
        category = re.search(r"\(([a-z][a-z_]*)\)", question)
        segment = (f"seller {seller.group(1)}" if seller else f"category {category.group(1)}" if category else "all")
        if re.search(r"\bearly\s+[A-Za-z]+\s+\d{4}\b", question, re.IGNORECASE):
            start, end = month, month + timedelta(days=15)
            baseline = (start - timedelta(days=30), start)
        else:
            start, end = month, add_months(month, 1)
            baseline = (add_months(month, -3), start)
        test = {"sources": ["orders", "reviews"]}
        third = (
            {"id": "H3", "family": "volume", "priority": 3,
             "statement": "The segment's order volume jumped, straining fulfilment and lowering scores.",
             "test": {"description": "Reviewed orders per day, window against baseline.", **test}}
            if seller else
            {"id": "H3", "family": "single_seller", "priority": 3,
             "statement": "One seller accounts for most of the low-score reviews.",
             "test": {"description": "Largest seller's share of 1-2 star reviews, window against baseline.", **test}}
        )
        return {
            "question": question,
            "metric": "average review score of reviewed orders, by order purchase date",
            "segment": segment,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "baseline_window": {"start": baseline[0].isoformat(), "end": baseline[1].isoformat()},
            "change_check": {"description": "Average review score in the window against the baseline periods.",
                             **test},
            "hypotheses": [
                {"id": "H1", "family": "logistics_delay", "priority": 1,
                 "statement": "Deliveries took longer than usual, and late deliveries pulled the scores down.",
                 "test": {"description": "Average days from purchase to delivery, window against baseline.", **test}},
                {"id": "H2", "family": "product_quality", "priority": 2,
                 "statement": "Customers rated the products lower: scores fell even on orders delivered on time.",
                 "test": {"description": "Average score of orders delivered on time, window against baseline.",
                          **test}},
                third,
                {"id": "H4", "family": "data_artefact", "priority": 4,
                 "statement": "Duplicate or missing review records distort the average.",
                 "test": {"description": "Share of orders with duplicate or missing scores, window against baseline.",
                          **test}},
            ],
        }

    @staticmethod
    def _order_value_plan(question: str) -> dict[str, Any] | None:
        month = question_month(question)
        if month is None:
            return None
        test = {"sources": ["orders", "payments"]}
        return {
            "question": question,
            "metric": "average order value (payments per order, by order purchase date)",
            "segment": "all",
            "window": {"start": add_months(month, 2).isoformat(), "end": add_months(month, 3).isoformat()},
            "baseline_window": {"start": month.isoformat(), "end": add_months(month, 2).isoformat()},
            "change_check": {"description": "Payments per order in the latest month against the months before.",
                             **test},
            "hypotheses": [
                {"id": "H1", "family": "price_discount", "priority": 1,
                 "statement": "Item prices fell: the average item price per order is lower than in the baseline.",
                 "test": {"description": "Average item price per order, window against baseline.", **test}},
                {"id": "H2", "family": "mix_shift", "priority": 2,
                 "statement": "Customers buy fewer items per order.",
                 "test": {"description": "Items per order, window against baseline.", **test}},
                {"id": "H3", "family": "single_seller", "priority": 3,
                 "statement": "One seller's lower-priced orders account for the decline.",
                 "test": {"description": "Largest seller's share of item revenue, window against baseline.", **test}},
                {"id": "H4", "family": "data_artefact", "priority": 4,
                 "statement": "Orders with missing or zero payment records pull the average down.",
                 "test": {"description": "Share of orders with missing payments or items, window against baseline.",
                          **test}},
            ],
        }

    def _reply_SqlProposal(self, data: dict[str, Any]) -> dict[str, Any] | None:
        if "previous_result" in data:  # the empty-result retry (Sprint 11d)
            return self._empty_result_reply(data)
        task, plan = data.get("task", {}), data.get("plan", {})
        kind = "change_check" if task.get("kind") == "change_check" else task.get("family")
        shape = _shape(str(plan.get("metric", "")))
        templates, labels = {
            "lateness": (LATENESS_SQL_TEMPLATES, LATENESS_LABELS),
            "reviews": (REVIEW_SQL_TEMPLATES, REVIEW_LABELS),
            "order_value": (ORDER_VALUE_SQL_TEMPLATES, ORDER_VALUE_LABELS),
            "orders": (SQL_TEMPLATES, LABELS),
        }[shape]
        if kind not in templates:
            return None
        w0, w1, b0 = plan["window"]["start"], plan["window"]["end"], plan["baseline_window"]["start"]
        rationale = f"{labels[kind]}, window against baseline."
        if _is_follow_up(task):  # the timing check: the second half of the window against everything before it
            start, end = date.fromisoformat(w0), date.fromisoformat(w1)
            w0 = (start + timedelta(days=max(1, (end - start).days // 2))).isoformat()
            rationale = f"{labels[kind]}, second half of the window against everything before it."
        wd = (date.fromisoformat(w1) - date.fromisoformat(w0)).days
        bd = (date.fromisoformat(w0) - date.fromisoformat(b0)).days
        sql = templates[kind].format(w0=w0, w1=w1, b0=b0, wd=max(1, wd), bd=max(1, bd),
                                     seg=segment_filter(str(plan.get("segment", ""))))
        sources = ["orders", "reviews"] if shape == "reviews" else ["orders", "payments"] if shape == "order_value" \
            else ["orders"]
        return {"sql": sql, "sources": sources, "rationale": rationale}

    @staticmethod
    def _empty_result_reply(data: dict[str, Any]) -> dict[str, Any]:
        """The stored-values check lists the values of the first column the query compared with a
        literal; the rewrite sends the query back unchanged (the stub cannot map names to values)."""
        previous = str(data.get("previous_sql", ""))
        if "value_check" in data:
            return {"sql": previous, "sources": [], "rationale": "The stored values do not change the query."}
        owners: dict[str, str] = {}  # column -> the first table that has it
        for source in data.get("sources", []):
            for table in source.get("tables", []):
                for column in table.get("columns", []):
                    owners.setdefault(column.split(" ", 1)[0], table["table"])
        for match in re.finditer(r"(?:\b\w+\.)?\b(\w+)\s*=\s*'", previous):
            column = match.group(1)
            if column in owners:
                sql = f"SELECT DISTINCT {column} AS stored_value FROM {owners[column]} ORDER BY 1 LIMIT 50"
                return {"sql": sql, "sources": [owners[column].split(".")[0]],
                        "rationale": f"The values stored in {column}."}
        return {"sql": "SELECT 'no literal filter' AS note", "sources": [], "rationale": "Nothing to check."}

    def _reply_ObservationDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        task = data.get("task", {})
        kind = "change_check" if task.get("kind") == "change_check" else task.get("family")
        rows = data.get("rows") or [{}]
        value, baseline = rows[0].get("value"), rows[0].get("baseline")
        effect = round(value / baseline - 1, 4) if value is not None and baseline else None
        change = f" ({effect:+.1%})" if effect is not None else ""
        shape = _shape(str(data.get("plan", {}).get("metric", "")))
        labels = {"lateness": LATENESS_LABELS, "reviews": REVIEW_LABELS, "order_value": ORDER_VALUE_LABELS,
                  "orders": LABELS}[shape]
        label = labels.get(kind, "Measure")
        if _is_follow_up(task):
            label = f"Second half of the window, {label[0].lower()}{label[1:]}"
        finding = f"{label}: {value} in the window against {baseline} in the baseline{change}."
        supports = {
            "lateness": lambda: _supports_lateness(kind, value, effect),
            "reviews": lambda: _supports_reviews(kind, value, effect),
            "order_value": lambda: _supports_order_value(kind, value, effect),
            "orders": lambda: _supports(kind, value, baseline, effect),
        }[shape]()
        return {"finding": finding, "value": value, "baseline": baseline, "effect": effect, "supports": supports}

    def _reply_CritiqueDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        hypothesis = data.get("hypothesis") or {}
        family = str(hypothesis.get("family", "the"))
        obs = data.get("observation")
        follow_up = (data.get("follow_up") or {}).get("results") or []
        row = (data.get("change") or {}).get("row") or {}
        n = row.get("n") if isinstance(row.get("n"), (int, float)) and not isinstance(row.get("n"), bool) else None
        n = int(n) if n is not None else None
        minimum = int(data.get("min_sample_size") or 0)
        ids = ([obs["id"]] if obs else []) + [f["id"] for f in follow_up]
        effect = abs(obs.get("effect") or 0.0) if obs else 0.0
        if n is None:
            sample = ("not_checked", "The change check reports no record count.")
        elif n < minimum:
            sample = ("failed", f"{n} records behind the change in the window, fewer than {minimum}.")
        else:
            sample = ("passed", f"{n} records behind the change in the window (minimum {minimum}).")
        reading = obs.get("finding", "") if obs else "no observation"
        follow_ups: list[str] = []
        contradicted = False
        if sample[0] == "failed":
            scores = (1, 1, 0)
            reason = f"Too few records to tell a cause from noise: {sample[1]}"
        elif not obs or obs.get("supports") is None:
            scores = (1, 0, 0)
            reason = f"The test gave no reading: {reading}"
            follow_ups = [f"Repeat the test: {hypothesis.get('test', {}).get('description', family)}"]
        elif obs.get("supports") is False:
            scores, contradicted = (0, 1, 1), True
            reason = f"The measure did not move as the explanation predicts: {reading}"
        elif effect >= SUPPORTED_EFFECT:
            scores = (3, 3, 2)
            reason = f"The measure moved by {effect:.0%}, enough to account for the change: {reading}"
        elif any(f.get("supports") and abs(f.get("effect") or 0.0) >= SUPPORTED_EFFECT for f in follow_up):
            scores = (3, 2, 2)
            reason = f"The follow-up confirms the effect in the later part of the window: {follow_up[-1]['finding']}"
        else:
            scores = (2, 1, 2)
            reason = f"The effect ({effect:.0%}) is too small to explain the change on its own: {reading}"
            follow_ups = [TIMING_FOLLOW_UP.format(family=family) if not follow_up else SPLIT_FOLLOW_UP.format(family=family)]
        verdict_line = "contradicts it" if contradicted else "is consistent with it"
        checks = [
            {"name": "alternative_cause", "outcome": "passed" if not contradicted else "failed",
             "detail": f"The {family} measure {verdict_line}; other explanations are judged in their own rounds."},
            {"name": "concentration", "outcome": "not_checked",
             "detail": "The measure was not split by seller, state or product."},
            {"name": "sample_size", "outcome": sample[0], "detail": sample[1]},
            {"name": "date_basis", "outcome": "not_checked", "detail": "Only one date column was measured."},
            {"name": "data_artefact", "outcome": "not_checked",
             "detail": "Duplicates and missing rows are tested by their own hypothesis."},
        ]
        return {
            "checks": checks,
            "scores": dict(zip(("supported_by_data", "explains_size_and_timing", "alternatives_excluded"), scores,
                               strict=True)),
            "contradicted": contradicted,
            "reason": reason,
            "follow_up_tests": follow_ups,
            "sample_size": n,
            "observation_ids": ids,
        }

    def _reply_ReportDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        plan = data.get("plan", {})
        families = {h["id"]: h for h in plan.get("hypotheses", [])}
        observations = [o for o in data.get("observations", []) if o.get("hypothesis_id") in families]
        change_obs = [o for o in data.get("observations", []) if o.get("hypothesis_id") is None]
        supported = sorted(
            (o for o in observations if o.get("supports")), key=lambda o: -abs(o.get("effect") or 0)
        )
        refuted = [o for o in observations if o.get("supports") is False]
        shape = _shape(str(plan.get("metric", "")))
        next_check = {
            "lateness": "Check carrier and regional disruptions reported for the window.",
            "reviews": "Read the review comments for the window and check the products behind them.",
            "order_value": "Check prices in the wider market for the same months.",
            "orders": "Check whether a promotion or campaign ran in the window.",
        }[shape]
        untested = {"lateness": LATENESS_UNTESTED_NOTE, "reviews": REVIEW_UNTESTED_NOTE,
                    "order_value": ORDER_VALUE_UNTESTED_NOTE, "orders": UNTESTED_NOTE}[shape]
        if plan.get("change_is_real") is False or not supported:
            return {"complete": True, "determinable": False, "causes": [], "ruled_out": [],
                    "limitations": ["No tested explanation is supported by the data."], "follow_up": []}
        causes = []
        for rank, obs in enumerate(supported, start=1):
            hyp = families[obs["hypothesis_id"]]
            ids = [obs["id"]] + [c["id"] for c in change_obs]
            causes.append({
                "hypothesis_id": hyp["id"], "type": hyp["family"], "summary": hyp["statement"],
                "confidence": round(max(0.3, 0.75 - 0.15 * (rank - 1)), 2),
                "statements": [
                    {"text": obs["finding"], "kind": "measured", "observation_ids": [obs["id"]]},
                    *({"text": c["finding"], "kind": "measured", "observation_ids": [c["id"]]} for c in change_obs),
                    {"text": f"The measurements are consistent with: {hyp['statement']}", "kind": "inferred",
                     "observation_ids": ids},
                ],
                "observation_ids": ids,
                "next_checks": [next_check],
            })
        ruled_out = [
            {"hypothesis_id": o["hypothesis_id"], "type": families[o["hypothesis_id"]]["family"],
             "why": f"Refuted by the data: {o['finding']}", "observation_ids": [o["id"]]}
            for o in refuted
        ]
        return {"complete": True, "determinable": True, "causes": causes, "ruled_out": ruled_out,
                "limitations": [untested],
                "follow_up": []}

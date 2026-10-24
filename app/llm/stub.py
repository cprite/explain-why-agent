"""A deterministic, scripted stand-in for the model, used to record the sample-mode cache without a
model key and as the stubbed generator in tests.

It answers the four agent reply schemas for two generic question shapes:

- "why did order volume change on <date>?": the day against the seven days before it, testing a
  broad rise across sellers, a price drop, a single seller and duplicate records;
- "why did delivery lateness change for deliveries completed <date> / the week of <date>?" (any
  question naming lateness or late deliveries): the share of deliveries completed after their
  estimated date, in that day or week against the four weeks before, testing longer carrier transit,
  more deliveries than usual, a single seller and invalid delivery dates.

It reads the date from the question (any "<day> <Month> <year>" or ISO date). It knows nothing about
the planted incidents. Its replies are what a model would return; the agents, queries and loop around it run
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
    "change_check": _daily("count(DISTINCT o.order_id)", ""),
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
    "change_check": _window_avg(f"CASE WHEN {LATE} THEN 1.0 ELSE 0.0 END"),
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

    def _reply_SqlProposal(self, data: dict[str, Any]) -> dict[str, Any] | None:
        task, plan = data.get("task", {}), data.get("plan", {})
        kind = "change_check" if task.get("kind") == "change_check" else task.get("family")
        if is_lateness(str(plan.get("metric", ""))):
            if kind not in LATENESS_SQL_TEMPLATES:
                return None
            w0, w1, b0 = plan["window"]["start"], plan["window"]["end"], plan["baseline_window"]["start"]
            wd = (date.fromisoformat(w1) - date.fromisoformat(w0)).days
            bd = (date.fromisoformat(w0) - date.fromisoformat(b0)).days
            sql = LATENESS_SQL_TEMPLATES[kind].format(w0=w0, w1=w1, b0=b0, wd=max(1, wd), bd=max(1, bd))
            return {"sql": sql, "sources": ["orders"], "rationale": f"{LATENESS_LABELS[kind]}, window against baseline."}
        if kind not in SQL_TEMPLATES:
            return None
        sql = SQL_TEMPLATES[kind].format(
            w0=plan["window"]["start"], w1=plan["window"]["end"], b0=plan["baseline_window"]["start"]
        )
        return {"sql": sql, "sources": ["orders"], "rationale": f"{LABELS[kind]}, window against baseline."}

    def _reply_ObservationDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        task = data.get("task", {})
        kind = "change_check" if task.get("kind") == "change_check" else task.get("family")
        rows = data.get("rows") or [{}]
        value, baseline = rows[0].get("value"), rows[0].get("baseline")
        effect = round(value / baseline - 1, 4) if value is not None and baseline else None
        change = f" ({effect:+.1%})" if effect is not None else ""
        lateness = is_lateness(str(data.get("plan", {}).get("metric", "")))
        label = (LATENESS_LABELS if lateness else LABELS).get(kind, "Measure")
        finding = f"{label}: {value} in the window against {baseline} in the baseline{change}."
        supports = _supports_lateness(kind, value, effect) if lateness else _supports(kind, value, baseline, effect)
        return {"finding": finding, "value": value, "baseline": baseline, "effect": effect, "supports": supports}

    def _reply_ReportDraft(self, data: dict[str, Any]) -> dict[str, Any] | None:
        plan = data.get("plan", {})
        families = {h["id"]: h for h in plan.get("hypotheses", [])}
        observations = [o for o in data.get("observations", []) if o.get("hypothesis_id") in families]
        change_obs = [o for o in data.get("observations", []) if o.get("hypothesis_id") is None]
        supported = sorted(
            (o for o in observations if o.get("supports")), key=lambda o: -abs(o.get("effect") or 0)
        )
        refuted = [o for o in observations if o.get("supports") is False]
        lateness = is_lateness(str(plan.get("metric", "")))
        next_check = (
            "Check carrier and regional disruptions reported for the window." if lateness
            else "Check whether a promotion or campaign ran in the window."
        )
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
                "limitations": [LATENESS_UNTESTED_NOTE if lateness else UNTESTED_NOTE],
                "follow_up": []}

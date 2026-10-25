"""Planner: question + source schemas -> investigation plan (architecture §4).

The model proposes metric, segment, window, baseline window, the change check and 2-4 hypotheses
from the families in architecture §4, guided by `HYPOTHESIS_CHECKLIST` (the standard families for each
kind of metric, with the breadth test for `volume`); the code renumbers hypotheses by priority so ids
are stable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import AgentContext, build_messages
from app.agents.prompts import load_prompt
from app.schemas import HYPOTHESIS_FAMILIES, Plan

AGENT = "Planner"
ROLE = "planner"

HYPOTHESIS_CHECKLIST: tuple[dict[str, str], ...] = (
    {
        "metric_kind": "count or revenue (orders, items, sales, payments, revenue)",
        "standard_families": "volume, single_seller, price_discount, data_artefact",
        "volume_test": "Breadth: distinct sellers, categories and customer states active per day in the window "
        "against the baseline, and the share of them whose count rose (or fell) the same way. A broad change "
        "moves most segments together; one segment carrying it points to single_seller or mix_shift instead.",
    },
    {
        "metric_kind": "share or rate (late share, share of a payment type, conversion)",
        "standard_families": "logistics_delay or mix_shift (what moves the numerator), volume (the denominator), "
        "single_seller, data_artefact",
        "volume_test": "The denominator per day (deliveries, orders) in the window against the baseline, and "
        "the number of segments whose share rose.",
    },
    {
        "metric_kind": "average per record (order value, price, freight, review score)",
        "standard_families": "price_discount, mix_shift, single_seller, logistics_delay or product_quality, "
        "data_artefact",
        "volume_test": "Records per day and the number of segments active, to see whether the average moved "
        "everywhere or only where the mix changed.",
    },
)
"""Standard hypothesis families per kind of metric (architecture §4), sent to the Planner with each plan."""


@dataclass
class PlanOutcome:
    """The plan, or the error code and message when no plan could be made."""

    plan: Plan | None
    error: dict[str, str] | None = None


def make_plan(ctx: AgentContext, question: str) -> PlanOutcome:
    """Ask the model for a plan for `question` over the sources in `ctx.data`."""
    payload = {
        "question": question,
        "sources": ctx.source_schemas(),
        "hypothesis_families": list(HYPOTHESIS_FAMILIES),
        "hypothesis_checklist": list(HYPOTHESIS_CHECKLIST),
    }
    reply = ctx.generate(
        build_messages(load_prompt("planner"), payload), schema=Plan, role=ROLE, run_id=ctx.run_id
    )
    if not reply.ok or reply.parsed is None:
        error = reply.error or {"code": "planner_failed", "message": "no plan returned"}
        ctx.trace.write(
            agent=AGENT, action="plan", input_summary=question, output_summary=error,
            status="error", retry_count=int(reply.repaired),
        )
        return PlanOutcome(None, error)

    plan = Plan.model_validate(reply.parsed)
    ordered = sorted(plan.hypotheses, key=lambda h: h.priority)
    hypotheses = [h.model_copy(update={"id": f"H{i}", "priority": i}) for i, h in enumerate(ordered, 1)]
    plan = plan.model_copy(update={"question": question, "change_is_real": None, "hypotheses": hypotheses})
    ctx.trace.write(
        agent=AGENT,
        action="plan",
        target="Investigator",
        input_summary=question,
        output_summary={
            "metric": plan.metric,
            "segment": plan.segment,
            "window": plan.window.model_dump(),
            "baseline_window": plan.baseline_window.model_dump(),
            "hypotheses": [f"{h.id} {h.family}: {h.statement}" for h in plan.hypotheses],
        },
        retry_count=int(reply.repaired),
    )
    return PlanOutcome(plan)

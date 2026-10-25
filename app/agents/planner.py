"""Planner: question + source schemas -> investigation plan (architecture §4).

The model proposes metric, segment, window, baseline window, the change check and 2-4 hypotheses
from the families in architecture §4; the code renumbers hypotheses by priority so ids are stable.
With `ctx.ground_filters` the sources carry the stored text values and the prompt has the value note
(`prompts/value_hints_note.md`, Sprint 11d).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import AgentContext, build_messages
from app.agents.prompts import load_prompt
from app.schemas import HYPOTHESIS_FAMILIES, Plan

AGENT = "Planner"
ROLE = "planner"


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
    }
    prompt = load_prompt("planner")
    if ctx.ground_filters:
        prompt = f"{prompt}\n\n{load_prompt('value_hints_note')}"
    reply = ctx.generate(build_messages(prompt, payload), schema=Plan, role=ROLE, run_id=ctx.run_id)
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

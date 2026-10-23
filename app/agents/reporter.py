"""Reporter: plan + observations -> ranked causes, ruled-out list and limitations (architecture §4, §7).

The model drafts causes that point at observation ids; the code turns those ids into evidence items
with the real query ids and sources. A cause whose ids do not resolve to an observation is dropped
(principle 1: a cause without a query and a number behind it is not reported).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.base import AgentContext, build_messages
from app.agents.prompts import load_prompt
from app.schemas import (
    Cause,
    Evidence,
    Hypothesis,
    Observation,
    Plan,
    ReportDraft,
    RuledOut,
    Statement,
)

AGENT = "Reporter"
ROLE = "reporter"


@dataclass
class ReportOutcome:
    """What the Reporter concluded, or why it could not."""

    complete: bool = False
    determinable: bool = False
    causes: list[Cause] = field(default_factory=list)
    ruled_out: list[RuledOut] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    follow_up: list[Hypothesis] = field(default_factory=list)
    error: dict[str, str] | None = None


def _observation_payload(obs: Observation) -> dict[str, object]:
    return {
        "id": obs.id,
        "hypothesis_id": obs.hypothesis_id,
        "source": obs.source,
        "finding": obs.finding,
        "value": obs.value,
        "baseline": obs.baseline,
        "effect": obs.effect,
        "supports": obs.supports,
    }


def report(
    ctx: AgentContext, plan: Plan, observations: list[Observation], notes: list[str]
) -> ReportOutcome:
    """Draft the answer from `observations`; `notes` are failures and caps met during the run."""
    payload = {
        "question": plan.question,
        "plan": {
            "metric": plan.metric,
            "segment": plan.segment,
            "window": plan.window.model_dump(),
            "baseline_window": plan.baseline_window.model_dump(),
            "change_is_real": plan.change_is_real,
            "hypotheses": [
                {"id": h.id, "family": h.family, "statement": h.statement} for h in plan.hypotheses
            ],
        },
        "observations": [_observation_payload(o) for o in observations],
        "notes": notes,
    }
    reply = ctx.generate(
        build_messages(load_prompt("reporter"), payload), schema=ReportDraft, role=ROLE, run_id=ctx.run_id
    )
    if not reply.ok or reply.parsed is None:
        error = reply.error or {"code": "reporter_failed", "message": "no report returned"}
        ctx.trace.write(
            agent=AGENT, action="report", input_summary=f"{len(observations)} observations",
            output_summary=error, status="error", retry_count=int(reply.repaired),
        )
        return ReportOutcome(error=error)

    draft = ReportDraft.model_validate(reply.parsed)
    by_id = {o.id: o for o in observations}
    limitations = list(draft.limitations)

    causes: list[Cause] = []
    if draft.determinable:
        for cause in draft.causes:
            evidence = [
                Evidence(observation_id=oid, source=by_id[oid].source, query_id=by_id[oid].query_id,
                         finding=by_id[oid].finding)
                for oid in cause.observation_ids
                if oid in by_id
            ]
            if not evidence:
                limitations.append(
                    f"Dropped a {cause.type} explanation: it named no observation from this run."
                )
                continue
            statements = []
            for st in cause.statements:
                query_ids = [by_id[oid].query_id for oid in st.observation_ids if oid in by_id]
                if st.kind == "measured" and not query_ids:
                    continue
                statements.append(Statement(text=st.text, kind=st.kind, query_ids=query_ids))
            causes.append(
                Cause(
                    rank=len(causes) + 1,
                    type=cause.type,
                    summary=cause.summary,
                    confidence=cause.confidence,
                    statements=statements,
                    evidence=evidence,
                    next_checks=cause.next_checks,
                )
            )
    determinable = draft.determinable and bool(causes)
    if draft.determinable and not causes:
        limitations.append("No explanation is backed by an observation from this run.")

    ruled_out = [
        RuledOut(
            type=item.type,
            why=item.why,
            evidence=[by_id[oid].query_id for oid in item.observation_ids if oid in by_id],
        )
        for item in draft.ruled_out
    ]
    ctx.trace.write(
        agent=AGENT,
        action="report",
        input_summary=f"{len(observations)} observations",
        output_summary={
            "complete": draft.complete,
            "determinable": determinable,
            "causes": [f"{c.rank}. {c.type}: {c.summary}" for c in causes],
            "ruled_out": [r.type for r in ruled_out],
            "follow_up": [h.statement for h in draft.follow_up],
        },
        retry_count=int(reply.repaired),
    )
    return ReportOutcome(
        complete=draft.complete,
        determinable=determinable,
        causes=causes,
        ruled_out=ruled_out,
        limitations=limitations,
        follow_up=draft.follow_up,
    )

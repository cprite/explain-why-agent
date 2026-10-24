"""Investigator: one hypothesis (or the change check) -> SQL -> query -> observation (architecture §4).

The model writes the SQL and reads the rows; provenance (query id, sources, SQL) is taken from the
data layer, never from the model. A failed statement is repaired once from the error message, and
the repair is visible in the trace (`repair_sql`, retry_count 1).

The Markovian orchestrator passes `context`, the chunk input its chunk manager built (goal, carryover
state, World Model evidence): it goes into the SQL request as `chunk` with a short note appended to
the system prompt. Without it the request is exactly the simple loop's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, build_messages
from app.agents.prompts import load_prompt
from app.data.layer import QueryError, QueryOutcome, QueryResult
from app.schemas import Hypothesis, Observation, ObservationDraft, Plan, SqlProposal

AGENT = "Investigator"
ROLE = "investigator"
MAX_SQL_REPAIRS = 1
MAX_ROWS_IN_PROMPT = 50


@dataclass
class InvestigationOutcome:
    """Result of one investigation: an observation, or why there is none."""

    observation: Observation | None
    query_ids: list[str] = field(default_factory=list)
    error: str | None = None
    tool_cap_reached: bool = False


def _task(plan: Plan, hypothesis: Hypothesis | None) -> dict[str, Any]:
    if hypothesis is None:
        return {
            "kind": "change_check",
            "id": None,
            "statement": f"The {plan.metric} for {plan.segment} changed in the window against the baseline.",
            "test": plan.change_check.model_dump(),
        }
    return {
        "kind": "hypothesis",
        "id": hypothesis.id,
        "family": hypothesis.family,
        "statement": hypothesis.statement,
        "test": hypothesis.test.model_dump(),
    }


def _plan_summary(plan: Plan) -> dict[str, Any]:
    return {
        "question": plan.question,
        "metric": plan.metric,
        "segment": plan.segment,
        "window": plan.window.model_dump(),
        "baseline_window": plan.baseline_window.model_dump(),
    }


def _sources_in(sql: str, sources: list[str]) -> str:
    found = [s for s in sources if re.search(rf"\b{re.escape(s)}\s*\.", sql, re.IGNORECASE)]
    return "+".join(found) if found else "unknown"


def investigate(
    ctx: AgentContext,
    plan: Plan,
    hypothesis: Hypothesis | None,
    observation_id: str,
    *,
    context: str | None = None,
) -> InvestigationOutcome:
    """Test `hypothesis` (or the plan's change check when None) and return one observation.

    `context` is the Markovian chunk input (see the module docstring); None for the simple loop.
    """
    task = _task(plan, hypothesis)
    target = task["id"] or "change_check"
    base_payload = {"plan": _plan_summary(plan), "task": task, "sources": ctx.source_schemas()}
    sql_prompt = load_prompt("investigator_sql")
    if context is not None:
        base_payload["chunk"] = context
        sql_prompt = f"{sql_prompt}\n\n{load_prompt('chunk_note')}"
    query_ids: list[str] = []

    previous: tuple[str, QueryError] | None = None
    outcome: QueryOutcome | None = None
    sql = ""
    for attempt in range(MAX_SQL_REPAIRS + 1):
        payload = dict(base_payload)
        if previous is not None:
            payload["previous_sql"] = previous[0]
            payload["previous_error"] = previous[1].message
        reply = ctx.generate(
            build_messages(sql_prompt, payload),
            schema=SqlProposal,
            role=ROLE,
            run_id=ctx.run_id,
        )
        action = "repair_sql" if attempt else "write_sql"
        if not reply.ok or reply.parsed is None:
            ctx.trace.write(
                agent=AGENT, action=action, input_summary=target, output_summary=reply.error,
                status="error", retry_count=attempt,
            )
            # Fixed wording (details stay in the trace) so later prompts, and so the sample-mode
            # cache keys, do not depend on which transient error happened in a live run.
            return InvestigationOutcome(None, query_ids, f"{target}: model call failed")
        sql = SqlProposal.model_validate(reply.parsed).sql
        ctx.trace.write(
            agent=AGENT, action=action, input_summary=target, output_summary=sql, retry_count=attempt,
            **({"previous_error": previous[1].message} if previous else {}),
        )
        if not ctx.budget.take_tool_call():
            ctx.trace.write(
                agent=AGENT, action="run_query", input_summary=target, output_summary="tool-call cap reached",
                status="cap_reached", retry_count=attempt,
            )
            return InvestigationOutcome(None, query_ids, f"{target}: tool-call cap reached", tool_cap_reached=True)
        outcome = ctx.data.query(None, sql)
        query_ids.append(outcome.query_id)
        ctx.trace.write(
            agent=AGENT,
            action="run_query",
            target="DataLayer",
            input_summary=sql,
            output_summary=(
                f"{outcome.row_count} rows" + (" (truncated)" if outcome.truncated else "")
                if isinstance(outcome, QueryResult)
                else f"{outcome.code}: {outcome.message}"
            ),
            status="ok" if isinstance(outcome, QueryResult) else outcome.code,
            retry_count=attempt,
            query_id=outcome.query_id,
        )
        if isinstance(outcome, QueryResult):
            break
        previous = (sql, outcome)

    if not isinstance(outcome, QueryResult):
        message = outcome.message if isinstance(outcome, QueryError) else "no query ran"
        return InvestigationOutcome(None, query_ids, f"{target}: query failed after repair: {message}")

    observe_payload = {
        "plan": base_payload["plan"],
        "task": task,
        "sql": sql,
        "columns": outcome.columns,
        "rows": outcome.rows[:MAX_ROWS_IN_PROMPT],
        "rows_returned": outcome.row_count,
        "truncated": outcome.truncated or outcome.row_count > MAX_ROWS_IN_PROMPT,
    }
    reply = ctx.generate(
        build_messages(load_prompt("investigator_observe"), observe_payload),
        schema=ObservationDraft,
        role=ROLE,
        run_id=ctx.run_id,
    )
    if not reply.ok or reply.parsed is None:
        ctx.trace.write(
            agent=AGENT, action="observe", input_summary=target, output_summary=reply.error, status="error",
            retry_count=int(reply.repaired), query_id=outcome.query_id,
        )
        return InvestigationOutcome(None, query_ids, f"{target}: model call failed")

    draft = ObservationDraft.model_validate(reply.parsed)
    observation = Observation(
        id=observation_id,
        hypothesis_id=task["id"],
        query_id=outcome.query_id,
        source=_sources_in(sql, ctx.data.list_sources()),
        sql=sql,
        finding=draft.finding,
        value=draft.value,
        baseline=draft.baseline,
        effect=draft.effect,
        supports=draft.supports,
    )
    ctx.trace.write(
        agent=AGENT,
        action="observe",
        target="Reporter",
        input_summary=target,
        output_summary=observation.finding,
        retry_count=int(reply.repaired),
        query_id=outcome.query_id,
        observation_id=observation.id,
        supports=observation.supports,
    )
    return InvestigationOutcome(observation, query_ids)

"""Investigator: one hypothesis (or the change check) -> SQL -> query -> observation (architecture §4).

The model writes the SQL and reads the rows; provenance (query id, sources, SQL) is taken from the
data layer, never from the model. A failed statement is repaired once from the error message, and
the repair is visible in the trace (`repair_sql`, retry_count 1).

The Markovian orchestrator passes `context`, the chunk input its chunk manager built (goal, carryover
state, World Model evidence): it goes into the SQL request as `chunk` with a short note appended to
the system prompt. For the change check it also asks for `spread` and `n` columns
(`prompts/change_check_note.md`), which the orchestrator's no-significant-change branch and the
Critic's sample-size check read. Without `context` the request is exactly the simple loop's.

With `ctx.ground_filters` (the Markovian orchestrator, Sprint 11d) the SQL request carries the stored
text values (`values` in `sources`) and the value note, and a measurement that matched no records
(`matched_nothing`: no rows, or `value` / `baseline` NULL) is retried once: the model writes a query
of the stored values of the filtered columns (`check_values`), sees its rows and rewrites the query
(`rewrite_sql`). If that still matches nothing, the observation says "Filter matched no records"
with no value (`InvestigationOutcome.no_records`) instead of being read as a measurement. Each step
is a trace line (`empty_result`, `check_values`, `rewrite_sql`, `grounded`) and costs tool calls
within the run's cap.
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
CHECK_VALUES_LIMIT = 50
"""Rows of the stored-values check passed back to the model (Sprint 11d)."""
NO_RECORDS_FINDING = "Filter matched no records"
"""Leads the finding of a measurement whose filter matched nothing, even after the value check."""


@dataclass
class InvestigationOutcome:
    """Result of one investigation: an observation, or why there is none."""

    observation: Observation | None
    query_ids: list[str] = field(default_factory=list)
    error: str | None = None
    tool_cap_reached: bool = False
    # Sprint 11d: the observation records that the filter matched no records (nothing measured).
    no_records: bool = False


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


def matched_nothing(result: QueryResult) -> str | None:
    """Why a measurement result holds no records, or None when it does (or cannot tell).

    No rows at all; or rows with a `value` column (and a `baseline` column, if any) where each is
    NULL or 0 and at least one is NULL. A measure that is 0 in both windows is a measurement, and a
    window that drops to NULL against a non-zero baseline is a real drop, not an empty filter.
    """
    if result.row_count == 0:
        return "0 rows"
    if "value" not in result.columns:
        return None
    keys = [k for k in ("value", "baseline") if k in result.columns]
    cells = [row.get(k) for row in result.rows for k in keys]
    if all(c is None or (isinstance(c, (int, float)) and not isinstance(c, bool) and c == 0) for c in cells) \
            and any(c is None for c in cells):
        return f"{' and '.join(keys)} NULL or 0 in every row ({result.row_count} rows)"
    return None


def _ask_sql(
    ctx: AgentContext, prompt: str, payload: dict[str, Any], target: str, action: str, attempt: int,
    **trace_fields: Any,
) -> str | None:
    """One SqlProposal call; its trace line. None when the call failed."""
    reply = ctx.generate(build_messages(prompt, payload), schema=SqlProposal, role=ROLE, run_id=ctx.run_id)
    if not reply.ok or reply.parsed is None:
        ctx.trace.write(
            agent=AGENT, action=action, input_summary=target, output_summary=reply.error,
            status="error", retry_count=attempt,
        )
        return None
    sql = SqlProposal.model_validate(reply.parsed).sql
    ctx.trace.write(
        agent=AGENT, action=action, input_summary=target, output_summary=sql, retry_count=attempt, **trace_fields,
    )
    return sql


def _run_sql(
    ctx: AgentContext, target: str, sql: str, attempt: int, query_ids: list[str], limit: int | None = None,
) -> QueryOutcome | None:
    """Run one statement within the tool-call cap; its trace line. None when the cap is reached."""
    if not ctx.budget.take_tool_call():
        ctx.trace.write(
            agent=AGENT, action="run_query", input_summary=target, output_summary="tool-call cap reached",
            status="cap_reached", retry_count=attempt,
        )
        return None
    outcome = ctx.data.query(None, sql, limit)
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
    return outcome


@dataclass
class _Grounded:
    """What the empty-result retry left: the statement and result to read, or why it stopped."""

    sql: str
    outcome: QueryResult
    empty: str | None
    tool_cap_reached: bool = False


def _ground_empty(
    ctx: AgentContext,
    base_payload: dict[str, Any],
    sql_prompt: str,
    target: str,
    sql: str,
    outcome: QueryResult,
    empty: str,
    query_ids: list[str],
) -> _Grounded:
    """The empty-result retry (Sprint 11d), once per measurement: check the stored values of the
    filtered columns, then rewrite the query with them. Every step is a trace line."""
    ctx.trace.write(
        agent=AGENT, action="empty_result", input_summary=target, output_summary=f"no records: {empty}",
        status="empty", query_id=outcome.query_id,
    )
    payload = {**base_payload, "previous_sql": sql, "previous_result": f"no records: {empty}"}
    check_sql = _ask_sql(ctx, load_prompt("investigator_check_values"), payload, target, "check_values", 1)
    if check_sql is None:
        return _Grounded(sql, outcome, empty)
    checked = _run_sql(ctx, target, check_sql, 1, query_ids, limit=CHECK_VALUES_LIMIT)
    if checked is None:
        return _Grounded(sql, outcome, empty, tool_cap_reached=True)
    payload["value_check"] = (
        {"sql": check_sql, "columns": checked.columns, "rows": checked.rows[:CHECK_VALUES_LIMIT]}
        if isinstance(checked, QueryResult)
        else {"sql": check_sql, "error": checked.message}
    )
    rewrite_prompt = f"{sql_prompt}\n\n{load_prompt('investigator_rewrite_note')}"
    new_sql = _ask_sql(ctx, rewrite_prompt, payload, target, "rewrite_sql", 1)
    if new_sql is None:
        return _Grounded(sql, outcome, empty)
    rewritten = _run_sql(ctx, target, new_sql, 1, query_ids)
    if rewritten is None:
        return _Grounded(sql, outcome, empty, tool_cap_reached=True)
    if not isinstance(rewritten, QueryResult):  # no second repair: the original stays the reading
        return _Grounded(sql, outcome, empty)
    still = matched_nothing(rewritten)
    ctx.trace.write(
        agent=AGENT, action="grounded", input_summary=target,
        output_summary=f"still no records: {still}" if still else f"{rewritten.row_count} rows after the rewrite",
        status="empty" if still else "ok", query_id=rewritten.query_id,
    )
    return _Grounded(new_sql, rewritten, still)


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
    if ctx.ground_filters:
        sql_prompt = f"{sql_prompt}\n\n{load_prompt('value_hints_note')}"
    if context is not None:
        base_payload["chunk"] = context
        sql_prompt = f"{sql_prompt}\n\n{load_prompt('chunk_note')}"
        if hypothesis is None:  # the orchestrator compares the change with its spread (Sprint 9)
            sql_prompt = f"{sql_prompt}\n\n{load_prompt('change_check_note')}"
    query_ids: list[str] = []

    previous: tuple[str, QueryError] | None = None
    outcome: QueryOutcome | None = None
    sql = ""
    for attempt in range(MAX_SQL_REPAIRS + 1):
        payload = dict(base_payload)
        if previous is not None:
            payload["previous_sql"] = previous[0]
            payload["previous_error"] = previous[1].message
        action = "repair_sql" if attempt else "write_sql"
        written = _ask_sql(ctx, sql_prompt, payload, target, action, attempt,
                           **({"previous_error": previous[1].message} if previous else {}))
        if written is None:
            # Fixed wording (details stay in the trace) so later prompts, and so the sample-mode
            # cache keys, do not depend on which transient error happened in a live run.
            return InvestigationOutcome(None, query_ids, f"{target}: model call failed")
        sql = written
        outcome = _run_sql(ctx, target, sql, attempt, query_ids)
        if outcome is None:
            return InvestigationOutcome(None, query_ids, f"{target}: tool-call cap reached", tool_cap_reached=True)
        if isinstance(outcome, QueryResult):
            break
        previous = (sql, outcome)

    if not isinstance(outcome, QueryResult):
        message = outcome.message if isinstance(outcome, QueryError) else "no query ran"
        return InvestigationOutcome(None, query_ids, f"{target}: query failed after repair: {message}")

    empty = matched_nothing(outcome) if ctx.ground_filters else None
    if empty is not None:
        grounded = _ground_empty(ctx, base_payload, sql_prompt, target, sql, outcome, empty, query_ids)
        sql, outcome = grounded.sql, grounded.outcome
        if grounded.empty is not None:
            observation = Observation(
                id=observation_id,
                hypothesis_id=task["id"],
                query_id=outcome.query_id,
                source=_sources_in(sql, ctx.data.list_sources()),
                sql=sql,
                finding=(f"{NO_RECORDS_FINDING} ({grounded.empty}), also after checking the stored values "
                         "of the filtered columns; nothing was measured, so this is not a small sample."),
            )
            ctx.trace.write(
                agent=AGENT, action="observe", target="Reporter", input_summary=target,
                output_summary=observation.finding, status="no_records", query_id=outcome.query_id,
                observation_id=observation.id, supports=None,
            )
            return InvestigationOutcome(observation, query_ids, no_records=True,
                                        tool_cap_reached=grounded.tool_cap_reached)

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

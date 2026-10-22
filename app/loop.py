"""The simple investigation loop: Planner -> Investigator over hypotheses -> Reporter.

Deliberately shallow; the Markovian orchestrator replaces it in build-plan task 12 and the Critic
slots in between Investigator and Reporter. Caps come from the environment: `MAX_AGENT_ROUNDS`
(one round = one agent turn: the plan with its change check, one hypothesis, or one report) and
`MAX_TOOL_CALLS` (queries). A Reporter that keeps asking for more investigation stops at the round
cap with a structured error result.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.agents.base import AgentContext, Budget
from app.agents.investigator import investigate
from app.agents.planner import make_plan
from app.agents.reporter import report
from app.config import REPO_ROOT, Settings, get_settings, resolve_path
from app.data.layer import DataLayer
from app.llm.generator import GenerateFn
from app.schemas import AgentInfo, Change, Hypothesis, Observation, Result, ResultError
from app.trace import TraceWriter

AGENTS = [
    AgentInfo(name="Planner", role="Turns the question into metric, window, baseline and hypotheses; checks the change is real"),
    AgentInfo(name="Investigator", role="Tests one hypothesis at a time with SQL against the data layer"),
    AgentInfo(name="Reporter", role="Ranks the supported causes with their evidence and lists what was ruled out"),
]
SAMPLE_MODE_NOTE = (
    "Sample mode: model replies come from the recorded per-call cache and data from the local DuckDB "
    "sample; agents, queries and the loop run for real."
)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run_investigation(
    question: str,
    *,
    run_id: str,
    generate: GenerateFn,
    data: DataLayer,
    settings: Settings | None = None,
    log_dir: Path | str | None = None,
    sample_mode: bool | None = None,
) -> Result:
    """Investigate `question` and return a `Result` (status `success` or `error`); never raises."""
    settings = settings or get_settings()
    sample_mode = settings.sample_mode if sample_mode is None else sample_mode
    started = time.perf_counter()
    trace = TraceWriter(Path(log_dir) if log_dir else resolve_path(settings.log_dir), run_id)
    budget = Budget(settings.max_agent_rounds, settings.max_tool_calls)
    ctx = AgentContext(run_id=run_id, generate=generate, data=data, trace=trace, budget=budget)
    query_log = getattr(getattr(data, "log", None), "path", None)
    observations: list[Observation] = []
    notes: list[str] = []
    change: Change | None = None

    def result(**fields: object) -> Result:
        limitations = list(fields.pop("limitations", []))
        for note in notes:
            if note not in limitations:
                limitations.append(note)
        if sample_mode:
            limitations.append(SAMPLE_MODE_NOTE)
        built = Result(
            run_id=run_id,
            question=question,
            change=change,
            agents=AGENTS,
            trace_id=run_id,
            log_file=_display_path(trace.path),
            query_log=_display_path(query_log) if query_log else None,
            execution_time_seconds=round(time.perf_counter() - started, 3),
            sample_mode=sample_mode,
            limitations=limitations,
            **fields,
        )
        trace.write(
            agent="Loop", action="finish", status=built.status,
            output_summary={"status": built.status, "causes": len(built.causes),
                            "error": built.error.model_dump() if built.error else None},
            rounds_used=budget.rounds_used, tool_calls_used=budget.tool_calls_used,
        )
        return built

    def failure(code: str, message: str) -> Result:
        return result(status="error", determinable=False, error=ResultError(code=code, message=message))

    try:
        trace.write(
            agent="Loop", action="start", target="Planner", input_summary=question, sample_mode=sample_mode,
            max_agent_rounds=budget.max_rounds, max_tool_calls=budget.max_tool_calls,
        )

        # Round 1: plan, and confirm the change is real.
        budget.take_round()
        planned = make_plan(ctx, question)
        if planned.plan is None:
            error = planned.error or {}
            return failure(error.get("code", "planner_failed"), error.get("message", "no plan"))
        plan = planned.plan
        trace.write(agent="Planner", action="delegate", target="Investigator", input_summary="change_check")
        checked = investigate(ctx, plan, None, "obs-0")
        if checked.observation is not None:
            observations.append(checked.observation)
            plan = plan.model_copy(update={"change_is_real": checked.observation.supports})
            obs = checked.observation
            change = Change(
                metric=plan.metric, segment=plan.segment,
                window=f"{plan.window.start} to {plan.window.end}",
                baseline=obs.baseline, observed=obs.value, significant=obs.supports,
            )
        elif checked.error:
            notes.append(f"Change check failed: {checked.error}")

        hypotheses: list[Hypothesis] = list(plan.hypotheses)
        queue = list(hypotheses) if plan.change_is_real is not False else []
        if plan.change_is_real is False:
            trace.write(agent="Planner", action="branch", output_summary="no significant change: hypotheses skipped")

        while True:
            while queue:
                if budget.rounds_left <= 1:  # keep one round for the Reporter
                    notes.append(f"Round cap reached: {len(queue)} hypotheses left untested.")
                    trace.write(agent="Loop", action="cap_reached", status="cap_reached",
                                output_summary=f"MAX_AGENT_ROUNDS={budget.max_rounds}")
                    break
                if budget.tool_calls_used >= budget.max_tool_calls:
                    notes.append(f"Tool-call cap reached: {len(queue)} hypotheses left untested.")
                    trace.write(agent="Loop", action="cap_reached", status="cap_reached",
                                output_summary=f"MAX_TOOL_CALLS={budget.max_tool_calls}")
                    break
                hypothesis = queue.pop(0)
                budget.take_round()
                trace.write(agent="Planner", action="delegate", target="Investigator",
                            input_summary=f"{hypothesis.id} {hypothesis.family}: {hypothesis.statement}")
                outcome = investigate(ctx, plan, hypothesis, f"obs-{len(observations)}")
                if outcome.observation is not None:
                    observations.append(outcome.observation)
                elif outcome.error:
                    notes.append(f"Not tested: {outcome.error}")

            if not budget.take_round():
                return failure("max_agent_rounds", f"stopped at MAX_AGENT_ROUNDS={budget.max_rounds} before a report")
            reported_plan = plan.model_copy(update={"hypotheses": hypotheses})
            outcome = report(ctx, reported_plan, observations, notes)
            if outcome.error is not None:
                return failure(outcome.error.get("code", "reporter_failed"), outcome.error.get("message", ""))
            if outcome.complete or not outcome.follow_up:
                if not outcome.complete:
                    notes.append("The Reporter marked the answer incomplete but proposed no follow-up.")
                return result(
                    status="success",
                    determinable=outcome.determinable,
                    causes=outcome.causes,
                    ruled_out=outcome.ruled_out,
                    limitations=outcome.limitations,
                )
            if budget.rounds_left < 2:
                return failure(
                    "max_agent_rounds",
                    f"stopped at MAX_AGENT_ROUNDS={budget.max_rounds}: the Reporter still asked for more "
                    "investigation",
                )
            follow_up = [
                h.model_copy(update={"id": f"H{len(hypotheses) + i}", "priority": len(hypotheses) + i})
                for i, h in enumerate(outcome.follow_up[:2], 1)
            ]
            hypotheses.extend(follow_up)
            queue = follow_up
            trace.write(agent="Reporter", action="request_follow_up", target="Investigator",
                        output_summary=[f"{h.id} {h.family}: {h.statement}" for h in follow_up])
    except Exception as exc:  # noqa: BLE001 - a run always ends in a structured result
        return failure("internal", f"{type(exc).__name__}: {exc}")

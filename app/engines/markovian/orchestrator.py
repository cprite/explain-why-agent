"""Markovian orchestrator: the bounded, chunked investigation loop (architecture §4, §5.2).

    result = run_markovian(question, run_id="r1", generate=generator, data=data_layer)

Replaces the simple loop (`app/loop.py`, still callable with `run.py --loop simple`). The agents and
the generator are injected; this module makes no HTTP call itself.

- Chunk 1 (the architecture's "chunk 0"): the Planner's plan and hypothesis list, written to the
  World Model, then the change check, run on the chunk input built from the ContextBuilder's `plan`
  payload for the question.
- Each later chunk: one round on one hypothesis, in the Planner's priority order. The chunk input is
  the goal, the carryover from the chunk before and the ContextBuilder's `investigate` evidence for
  the hypothesis followed by its `plan` overview, packed by the `ChunkManager` within
  `chunk_budget_chars`. The Investigator runs its queries on that input; every successful result is
  ingested into the World Model through `IngestPipeline` (rows for provenance, plus the measured
  value against its baseline with a supports / refutes edge); the Critic (Sprint 9, its own call on
  the critic lane; `critic=critic_hook` is the no-op) gives a verdict, stored in the World Model
  with the observations it relied on; the ranking is updated and the carryover cascade (Sprint 7)
  compresses it for the next chunk, with `rounds_left` taken from `ChunkManager.rounds_left`.
- Critique and revision: an `insufficient` verdict sends the hypothesis back to the Investigator
  once, in its own chunk, with the Critic's follow-up tests (results ingested into the World
  Model); the second critique decides, and a second `insufficient` demotes it. Critic calls are
  capped at `max_chunks` per run.
- Branches (each one an `Orchestrator` / `branch` trace line with why and the numbers used):
  `no_significant_change` (|observed - baseline| within `CHANGE_VARIATION_THRESHOLD` spreads, or no
  spread and the change check reads not real: the run ends after chunk 1, determinable with no
  causes); `promotion` (the leader is refuted or demoted: the next in the Planner's order leads);
  `cannot_be_determined` (no hypothesis supported, the Critic flagged the sample as smaller than
  `CRITIC_MIN_SAMPLE_SIZE`, or the cap reached without a supported leader: no causes, the refuted in
  `ruled_out`, the rest listed as unconfirmed in `limitations`) or `determined`.
- The Reporter writes the result from the last carryover and the World Model's `report` evidence;
  with a Critic only the causes it supported are kept. If the Reporter asks for follow-up hypotheses
  they are tested in further chunks while the cap allows.

Stops, each with a schema-valid `Result` and `stop_reason`: `completed` (every hypothesis tested and
reported), `max_chunks` (`MARKOVIAN_MAX_CHUNKS` reached with work left), `max_tool_calls`
(`MAX_TOOL_CALLS` reached with work left), `timeout` (the run passed `MARKOVIAN_RUN_TIMEOUT_S` or one
chunk passed `MARKOVIAN_CHUNK_TIMEOUT_SECONDS`), `no_hypotheses` (the no-significant-change branch)
and `error` (a fatal failure: no plan, no report, an unexpected exception). The run works in a daemon thread that the
calling thread monitors; on a timeout the worker is told to stop, any data call in flight is
interrupted and the caller returns once the worker has left the data layer (so the caller can close
it), so a slow model never holds the run beyond its limit.

Per chunk, one `Orchestrator` / `chunk` line in `logs/trace-<run>.jsonl` (chunk number, hypothesis id,
queries run, carryover step used, projected vs actual chunk chars) and one line in
`logs/markovian-<run>.jsonl` (the chunk record and the carryover passed on). The run's World Model is
an in-memory store, so prompts depend only on this run (the sample-mode cache key hashes them); its
append log is written to `logs/world-<run>.jsonl`.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.agents.base import AgentContext, Budget
from app.agents.critic import Critic
from app.agents.investigator import InvestigationOutcome, investigate
from app.agents.planner import make_plan
from app.agents.reporter import ReportOutcome, report
from app.config import Settings, get_settings, resolve_path
from app.data.layer import DataLayer, QueryError, QueryOutcome, QueryResult, SourceInfo
from app.engines.markovian.carryover import (
    Carryover,
    FallbackIds,
    RoundOutput,
    build_carryover,
)
from app.engines.markovian.chunks import ChunkInput, ChunkManager
from app.engines.markovian.config import MarkovianConfig
from app.engines.world_model.context import ContextBuilder, Intent
from app.engines.world_model.ingest import IngestPipeline
from app.engines.world_model.store import WorldStore
from app.llm.generator import GenerateFn, GenerationResult, Message
from app.loop import AGENTS, SAMPLE_MODE_NOTE, _display_path
from app.schemas import (
    Change,
    Hypothesis,
    Observation,
    Plan,
    QuerySpec,
    Result,
    ResultError,
    RuledOut,
    StopReason,
    TokenReport,
    Verdict,
)
from app.trace import TraceWriter

AGENT = "Orchestrator"
POLL_SECONDS = 0.1
"""How often the calling thread checks the run and chunk deadlines."""
STOP_GRACE_SECONDS = 5.0
"""After a timeout, how long the calling thread waits for the worker to leave the data layer."""
WORKER_JOIN_SECONDS = 0.5
"""After that, how long it waits for the worker to end (it may be inside a model call with its own timeout)."""
MAX_REPORTS = 3
"""Reporter calls per run (a report that asks for follow-ups costs another one)."""
MAX_FOLLOW_UPS = 2
"""Follow-up hypotheses taken from one report."""
MAX_REVISIONS = 1
"""Times the Critic can send one hypothesis back to the Investigator."""
MAX_FOLLOW_UP_TESTS = 2
"""Follow-up tests the Investigator runs in one revision."""
FOLLOW_UP_PREFIX = "Follow-up requested by the Critic: "
"""Leads the test description the Investigator gets in a revision."""
NOTE_MIN_CHARS = 24
"""Shortest note or reason kept per carryover item when notes are shortened to fit the budget."""


# --- The Critic seam (Sprint 9) -----------------------------------------------------------------------


@dataclass(frozen=True)
class CriticRequest:
    """What the Critic sees after the Investigator's round on one hypothesis."""

    run_id: str
    plan: Plan
    hypothesis: Hypothesis
    hypothesis_entity_id: str
    observation: Observation | None
    chunk_text: str
    context_builder: ContextBuilder
    budget_chars: int
    generate: GenerateFn
    # Sprint 9: the second critique after a revision, and the measured change.
    attempt: int = 1
    follow_up_tests: tuple[str, ...] = ()
    follow_up: tuple[Observation, ...] = ()
    change: Observation | None = None
    change_row: dict[str, Any] | None = None


CriticHook = Callable[[CriticRequest], Verdict | None]


def critic_hook(request: CriticRequest) -> Verdict | None:
    """The no-op critic: gives no verdict (pass `critic=critic_hook` for the Sprint 8 behaviour).

    The default for `run_markovian` is the real Critic (`app.agents.critic.Critic`). A verdict
    overrides the Investigator's reading for the ranking: `supported` ranks the hypothesis,
    `refuted` rules it out, `insufficient` leaves it open with the verdict's reason.
    """
    return None


# --- Wrappers: metering, cancellation and query capture ---------------------------------------------


class _MeteredGenerate:
    """The injected generator, counting the characters sent and received; refuses calls once cancelled."""

    def __init__(self, inner: GenerateFn, cancel: threading.Event) -> None:
        self.inner = inner
        self.cancel = cancel
        self.sent_chars = 0
        self.received_chars = 0
        self.calls = 0

    def __call__(
        self,
        messages: list[Message],
        *,
        schema: Any = None,
        role: str = "default",
        run_id: str | None = None,
    ) -> GenerationResult:
        if self.cancel.is_set():
            return GenerationResult(ok=False, error={"code": "cancelled", "message": "the run was stopped"})
        self.calls += 1
        self.sent_chars += sum(len(str(m.get("content", ""))) for m in messages)
        result = self.inner(messages, schema=schema, role=role, run_id=run_id)
        if isinstance(result, GenerationResult):
            self.received_chars += len(result.content or "")
        return result

    def with_limits(self, *, deadline_seconds: float, max_retries: int = 0) -> GenerateFn:
        """The inner generator's bounded form (if it has one), still metered and cancellable."""
        bounded = getattr(self.inner, "with_limits", None)
        if not callable(bounded):
            return self
        metered = _MeteredGenerate(bounded(deadline_seconds=deadline_seconds, max_retries=max_retries), self.cancel)

        def call(messages: list[Message], *, schema: Any = None, role: str = "default",
                 run_id: str | None = None) -> GenerationResult:
            result = metered(messages, schema=schema, role=role, run_id=run_id)
            self.sent_chars += metered.sent_chars
            self.received_chars += metered.received_chars
            metered.sent_chars = metered.received_chars = 0
            return result

        return call


class RunCancelled(RuntimeError):
    """Raised by a schema read once the run is stopped."""


class _ObservedData(DataLayer):
    """The injected data layer, keeping each query outcome for the World Model; refuses once cancelled.

    It counts the calls in flight, so that on a timeout the watching thread can interrupt them
    (`inner.interrupt()`, if the layer has one) and wait until the worker has left the layer: the
    caller closes the layer as soon as the run returns, and a connection busy on the worker's
    thread cannot be closed.
    """

    def __init__(self, inner: DataLayer, cancel: threading.Event) -> None:
        self.inner = inner
        self.cancel = cancel
        self.adapter_name = getattr(inner, "adapter_name", "unknown")
        self.log = getattr(inner, "log", None)
        self.outcomes: list[QueryOutcome] = []
        self.in_flight = 0
        self.idle = threading.Condition()

    def _enter(self) -> bool:
        with self.idle:
            if self.cancel.is_set():
                return False
            self.in_flight += 1
            return True

    def _leave(self) -> None:
        with self.idle:
            self.in_flight -= 1
            self.idle.notify_all()

    def list_sources(self) -> list[str]:
        if not self._enter():
            raise RunCancelled("the run was stopped")
        try:
            return self.inner.list_sources()
        finally:
            self._leave()

    def describe(self, source: str) -> SourceInfo:
        if not self._enter():
            raise RunCancelled("the run was stopped")
        try:
            return self.inner.describe(source)
        finally:
            self._leave()

    def query(self, source: str | None, sql: str, limit: int | None = None,
              timeout: float | None = None) -> QueryOutcome:
        if not self._enter():
            return QueryError(query_id="cancelled", source=source, sql=sql, adapter=self.adapter_name,
                              code="cancelled", message="the run was stopped")
        try:
            outcome = self.inner.query(source, sql, limit, timeout)
        finally:
            self._leave()
        self.outcomes.append(outcome)
        return outcome

    def drain(self, until: float) -> bool:
        """After `cancel` is set: interrupt the calls in flight until none is left or `until` passes."""
        interrupt = getattr(self.inner, "interrupt", None)
        with self.idle:
            while self.in_flight:
                if callable(interrupt):
                    interrupt()
                left = until - time.monotonic()
                if left <= 0:
                    return False
                self.idle.wait(min(POLL_SECONDS, left))
        return True

    def take(self) -> list[QueryOutcome]:
        """The outcomes since the last call."""
        taken, self.outcomes = self.outcomes, []
        return taken


# --- The run ---------------------------------------------------------------------------------------


@dataclass
class _Reading:
    """The current reading of one hypothesis, for the ranking."""

    supports: bool | None
    effect: float | None
    text: str


@dataclass
class _ChunkState:
    chunk: ChunkInput
    kind: str
    hypothesis_id: str | None
    started: float
    sent0: int
    received0: int
    carryover_in: Carryover | None
    queries: list[str] = field(default_factory=list)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


class _Run:
    """One orchestrated run. `execute()` is called once."""

    def __init__(
        self,
        question: str,
        *,
        run_id: str,
        generate: GenerateFn,
        data: DataLayer,
        settings: Settings,
        config: MarkovianConfig,
        log_dir: Path,
        sample_mode: bool,
        critic: CriticHook | None,
        world_db_path: str,
    ) -> None:
        self.question = question
        self.run_id = run_id
        self.settings = settings
        self.config = config
        self.log_dir = log_dir
        self.sample_mode = sample_mode
        self.critic: CriticHook = critic if critic is not None else Critic(settings)
        # The Sprint 9 rules (causes only from supported verdicts, the cannot-be-determined branch)
        # apply to any critic but the no-op one.
        self.critic_active = self.critic is not critic_hook
        self.world_db_path = world_db_path
        self.started = time.monotonic()
        self.deadline = self.started + config.run_timeout_s
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.trace = TraceWriter(log_dir, run_id)
        self.markovian_log = log_dir / f"markovian-{run_id}.jsonl"
        self.world_log = log_dir / f"world-{run_id}.jsonl"
        self.generate = _MeteredGenerate(generate, self.cancel)
        self.data = _ObservedData(data, self.cancel)
        self.budget = Budget(config.max_chunks, settings.max_tool_calls)
        self.ctx = AgentContext(run_id=run_id, generate=self.generate, data=self.data, trace=self.trace,
                                budget=self.budget)
        self.manager = ChunkManager(config)
        self.fallback_ids = FallbackIds()
        self.query_log = getattr(getattr(data, "log", None), "path", None)
        # Shared with the watching thread (read under `lock` when a timeout result is built).
        self.change: Change | None = None
        self.observations: list[Observation] = []
        self.notes: list[str] = []
        self.readings: dict[str, _Reading] = {}
        self.carryover: Carryover | None = None
        # The Critic's state (Sprint 9): latest verdict and status per hypothesis id.
        self.verdicts: dict[str, Verdict] = {}
        self.status: dict[str, str] = {}
        self.revisions: dict[str, int] = {}
        self.critic_calls = 0
        self.leader: str | None = None
        self.sample_flag: Verdict | None = None
        self.change_obs: Observation | None = None
        self.change_row: dict[str, Any] | None = None
        self.query_rows: dict[str, dict[str, Any]] = {}
        self.tool_cap_hit = False
        self.phase_started: float | None = None
        self.phase = "start"
        self.result: Result | None = None
        self.finished = False

    # --- entry ---------------------------------------------------------------------------------

    def execute(self) -> Result:
        """Run the investigation in a worker thread, watching the run and chunk deadlines."""
        worker = threading.Thread(target=self._work, name=f"markovian-{self.run_id}", daemon=True)
        worker.start()
        while worker.is_alive():
            now = time.monotonic()
            deadline, which = self._deadline()
            if now >= deadline:
                break
            worker.join(min(POLL_SECONDS, deadline - now))
        if worker.is_alive():
            self.cancel.set()
            _, which = self._deadline()
            if which == "run":
                message = f"stopped at MARKOVIAN_RUN_TIMEOUT_S={self.config.run_timeout_s:g} during {self.phase}"
            else:
                message = (f"{self.phase} passed MARKOVIAN_CHUNK_TIMEOUT_SECONDS="
                           f"{self.config.chunk_timeout_seconds:g}")
            timed_out = self._finish(
                "timeout", status="error", determinable=False, error=ResultError(code="timeout", message=message),
                limitations=self._partial_findings(),
            )
            self._stop_worker(worker)
            if timed_out is not None:
                return timed_out
        assert self.result is not None  # the worker always finishes with a result
        return self.result

    def _stop_worker(self, worker: threading.Thread) -> None:
        """Get the cancelled worker out of the data layer, then give it a short wait to end.

        The worker refuses new model and data calls once `cancel` is set; a data call in flight is
        interrupted. Waiting for that means the caller can close the data layer as soon as the run
        returns. A model call in flight is not waited for beyond `WORKER_JOIN_SECONDS` (it has its
        own timeout and touches nothing the caller closes).
        """
        if not self.data.drain(time.monotonic() + STOP_GRACE_SECONDS):
            self.trace.write(agent=AGENT, action="stop_worker", status="error",
                             output_summary=f"a data call was still running after {STOP_GRACE_SECONDS:g} s")
        worker.join(WORKER_JOIN_SECONDS)

    def _deadline(self) -> tuple[float, str]:
        phase_started = self.phase_started
        if phase_started is not None and phase_started + self.config.chunk_timeout_seconds < self.deadline:
            return phase_started + self.config.chunk_timeout_seconds, "chunk"
        return self.deadline, "run"

    def _work(self) -> None:
        store: WorldStore | None = None
        try:
            store = WorldStore(self.world_db_path, settings=self.settings)
            self._investigate(store)
        except Exception as exc:  # noqa: BLE001 - a run always ends in a structured result
            self._fail("internal", f"{type(exc).__name__}: {exc}")
        finally:
            if store is not None:
                try:
                    store.export_log_jsonl(self.run_id, self.world_log)
                except Exception as exc:  # noqa: BLE001 - the log export never fails the run
                    self.trace.write(agent="WorldModel", action="export_log", status="error",
                                     output_summary=f"{type(exc).__name__}: {exc}")
                store.close()
            if self.result is None:  # cancelled before finishing: the watcher holds the result
                self._fail("internal", "the run ended without a result")

    # --- the investigation ---------------------------------------------------------------------

    def _investigate(self, store: WorldStore) -> None:
        cfg = self.config
        pipeline = IngestPipeline(store, settings=self.settings, agent="Investigator")
        builder = ContextBuilder(store)
        self.trace.write(
            agent=AGENT, action="start", target="Planner", input_summary=self.question, sample_mode=self.sample_mode,
            max_chunks=cfg.max_chunks, chunk_budget_chars=cfg.chunk_budget_chars,
            carryover_budget_chars=cfg.carryover_budget_chars, run_timeout_s=cfg.run_timeout_s,
            chunk_timeout_seconds=cfg.chunk_timeout_seconds, max_tool_calls=self.budget.max_tool_calls,
            critic="on" if self.critic_active else "off",
        )
        question_id = store.put_entity("question", {"text": self.question}, agent="Planner", run_id=self.run_id)
        overview = Intent("plan", question_id=question_id)

        # Chunk 1: plan, hypotheses into the World Model, change check.
        self._enter("chunk 1 (plan)")
        planned = make_plan(self.ctx, self.question)
        if planned.plan is None:
            state = self._open_chunk(self.question, self._evidence(builder, overview), "plan", None)
            self._close_chunk(state, status="error")
            error = planned.error or {}
            self._fail(error.get("code", "planner_failed"), error.get("message", "no plan"))
            return
        plan = planned.plan
        entity_ids = {
            h.id: pipeline.put_hypothesis(h, run_id=self.run_id, question_id=question_id, agent="Planner")
            for h in plan.hypotheses
        }
        goal = self._goal(plan)
        state = self._open_chunk(goal, self._evidence(builder, overview), "plan", None)
        self.trace.write(agent="Planner", action="delegate", target="Investigator", input_summary="change_check")
        checked = investigate(self.ctx, plan, None, "obs-0", context=state.chunk.text)
        state.queries = self._ingest(pipeline, plan, None, None, checked)
        significant: bool | None = None
        numbers: dict[str, Any] = {}
        with self.lock:
            if checked.observation is not None:
                obs = checked.observation
                self.observations.append(obs)
                self.change_obs = obs
                self.change_row = self.query_rows.get(obs.query_id)
                significant, numbers = self._significance(obs, self.change_row)
                plan = plan.model_copy(update={"change_is_real": significant})
                self.change = Change(
                    metric=plan.metric, segment=plan.segment, window=f"{plan.window.start} to {plan.window.end}",
                    baseline=obs.baseline, observed=obs.value, significant=significant, spread=numbers.get("spread"),
                )
            elif checked.error:
                self.notes.append(f"Change check failed: {checked.error}")
        hypotheses: list[Hypothesis] = list(plan.hypotheses)
        self._carry(goal, hypotheses, "Plan: " + "; ".join(f"{h.id} {h.family}: {h.statement}" for h in hypotheses))
        if significant is False:
            # Branch: no significant change. The run ends here, without hypothesis rounds.
            summary = self._no_change_summary(plan, numbers)
            self._branch("no_significant_change", summary, **numbers)
            self._close_chunk(state)
            self._finish("no_hypotheses", status="success", determinable=True, summary=summary,
                         limitations=[summary])
            return
        self._branch("significant_change" if significant else "change_not_decided",
                     "the change is outside normal variation" if significant
                     else "the change check gave no reading; the hypotheses are tested", **numbers)
        self._close_chunk(state)
        queue = list(hypotheses)
        self.leader = hypotheses[0].id if hypotheses else None

        stop_reason: StopReason | None = None
        reports = 0
        while True:
            # One chunk per hypothesis, in priority order (plus one revision chunk when the Critic asks).
            while queue and not self.cancel.is_set():
                if self.sample_flag is not None:
                    self.notes.append(
                        f"Not tested after the Critic flagged the sample as too small: {', '.join(h.id for h in queue)}."
                    )
                    queue = []
                    break
                if not self.manager.can_start():
                    stop_reason = "max_chunks"
                    self.notes.append(
                        f"Chunk cap reached: MARKOVIAN_MAX_CHUNKS={cfg.max_chunks}; "
                        f"{len(queue)} hypotheses left untested ({', '.join(h.id for h in queue)})."
                    )
                    self.trace.write(agent=AGENT, action="cap_reached", status="cap_reached",
                                     output_summary=f"MARKOVIAN_MAX_CHUNKS={cfg.max_chunks}")
                    break
                if self.budget.tool_calls_used >= self.budget.max_tool_calls:
                    stop_reason = "max_tool_calls"
                    self.notes.append(
                        f"Tool-call cap reached: MAX_TOOL_CALLS={self.budget.max_tool_calls}; "
                        f"{len(queue)} hypotheses left untested ({', '.join(h.id for h in queue)})."
                    )
                    self.trace.write(agent=AGENT, action="cap_reached", status="cap_reached",
                                     output_summary=f"MAX_TOOL_CALLS={self.budget.max_tool_calls}")
                    break
                hypothesis = queue.pop(0)
                self._round(pipeline, builder, overview, plan, goal, hypotheses, hypothesis, entity_ids[hypothesis.id])
            if self.cancel.is_set():
                return

            # Report from the last carryover and the World Model.
            self._enter("the report")
            report_input = self.manager.build_input(
                self.manager.chunks_started + 1, goal, carryover=self.carryover,
                context=self._evidence(builder, Intent("report", question_id=question_id)),
            )
            self.trace.write(
                agent=AGENT, action="delegate", target="Reporter", input_summary=f"{len(self.observations)} observations",
                projected_chars=report_input.chars, chunk_budget_chars=cfg.chunk_budget_chars,
                carryover_step=self.carryover.carryover_step if self.carryover else None,
            )
            reports += 1
            reported_plan = plan.model_copy(update={"hypotheses": hypotheses})
            outcome = report(self.ctx, reported_plan, list(self.observations), list(self.notes),
                             context=report_input.text)
            if outcome.error is not None:
                self._fail(outcome.error.get("code", "reporter_failed"), outcome.error.get("message", ""))
                return
            if self.tool_cap_hit and stop_reason is None:
                stop_reason = "max_tool_calls"
            reason: StopReason = stop_reason or "completed"
            if outcome.complete or not outcome.follow_up or self.sample_flag is not None:
                if not outcome.complete and self.sample_flag is None:
                    self.notes.append("The Reporter marked the answer incomplete but proposed no follow-up.")
                self._conclude(reason, outcome, hypotheses)
                return
            if not self.manager.can_start() or reports >= MAX_REPORTS:
                cap = (f"MARKOVIAN_MAX_CHUNKS={cfg.max_chunks}" if not self.manager.can_start()
                       else f"{MAX_REPORTS} reports")
                if self.critic_active or outcome.causes:
                    outcome.limitations.append(
                        f"Incomplete: the Reporter asked for more investigation, but {cap} was reached.")
                    self._conclude("max_chunks", outcome, hypotheses)
                else:
                    self._fail("max_chunks", f"stopped at {cap}: the Reporter still asked for more investigation",
                               stop_reason="max_chunks")
                return
            follow_up = [
                h.model_copy(update={"id": f"H{len(hypotheses) + i}", "priority": len(hypotheses) + i})
                for i, h in enumerate(outcome.follow_up[:MAX_FOLLOW_UPS], 1)
            ]
            for h in follow_up:
                entity_ids[h.id] = pipeline.put_hypothesis(h, run_id=self.run_id, question_id=question_id,
                                                           agent="Reporter")
            hypotheses.extend(follow_up)
            if self.leader is None and follow_up:
                self.leader = follow_up[0].id
            queue = follow_up
            self.trace.write(agent="Reporter", action="request_follow_up", target="Investigator",
                             output_summary=[f"{h.id} {h.family}: {h.statement}" for h in follow_up])

    def _round_context(self, builder: ContextBuilder, overview: Intent, entity_id: str) -> dict[str, Any]:
        """The evidence for one round: `investigate` items for the hypothesis, then the `plan` overview."""
        investigate_payload = self._evidence(builder, Intent("investigate", hypothesis_id=entity_id))
        overview_payload = self._evidence(builder, overview)
        seen = {item["id"] for item in investigate_payload["items"]}
        return {
            "items": [*investigate_payload["items"], *(i for i in overview_payload["items"] if i["id"] not in seen)],
            "budget_chars": self.config.chunk_budget_chars,
            "used_chars": investigate_payload["used_chars"] + overview_payload["used_chars"],
        }

    def _round(
        self,
        pipeline: IngestPipeline,
        builder: ContextBuilder,
        overview: Intent,
        plan: Plan,
        goal: str,
        hypotheses: list[Hypothesis],
        hypothesis: Hypothesis,
        entity_id: str,
    ) -> None:
        """One chunk: investigate one hypothesis, ingest, critique, ranking, carryover; then a revision
        chunk if the Critic found the evidence insufficient."""
        self._enter(f"chunk {self.manager.chunks_started + 1} ({hypothesis.id})")
        state = self._open_chunk(goal, self._round_context(builder, overview, entity_id), "round", hypothesis.id)
        self.trace.write(agent="Planner", action="delegate", target="Investigator",
                         input_summary=f"{hypothesis.id} {hypothesis.family}: {hypothesis.statement}", chunk=state.chunk.index)
        outcome = investigate(self.ctx, plan, hypothesis, f"obs-{len(self.observations)}", context=state.chunk.text)
        state.queries = self._ingest(pipeline, plan, hypothesis, entity_id, outcome)
        with self.lock:
            if outcome.observation is not None:
                self.observations.append(outcome.observation)
            elif outcome.error:
                self.notes.append(f"Not tested: {outcome.error}")
        self.tool_cap_hit |= outcome.tool_cap_reached
        obs = outcome.observation
        reading = _Reading(obs.supports, obs.effect, obs.finding) if obs else _Reading(
            None, None, f"not tested: {outcome.error or 'no observation'}")
        verdict = self._critique(pipeline.store, builder, plan, hypothesis, entity_id, obs, state.chunk.text)
        if verdict is not None:
            reading = self._judged(hypotheses, hypothesis, verdict, reading)
        self.readings[hypothesis.id] = reading
        self._carry(goal, hypotheses, f"Round on {hypothesis.id} ({hypothesis.family}): {reading.text}")
        self._close_chunk(state)
        if (verdict is not None and verdict.verdict == "insufficient" and not verdict.sample_too_small
                and self.revisions.get(hypothesis.id, 0) < MAX_REVISIONS):
            if self.manager.can_start() and self.budget.tool_calls_used < self.budget.max_tool_calls:
                self._revise(pipeline, builder, overview, plan, goal, hypotheses, hypothesis, entity_id, verdict,
                             obs)
            else:
                self.notes.append(f"{hypothesis.id} was not revised: the chunk or tool-call cap was reached.")

    def _revise(
        self,
        pipeline: IngestPipeline,
        builder: ContextBuilder,
        overview: Intent,
        plan: Plan,
        goal: str,
        hypotheses: list[Hypothesis],
        hypothesis: Hypothesis,
        entity_id: str,
        first: Verdict,
        first_obs: Observation | None,
    ) -> None:
        """The revision chunk: the Investigator runs the Critic's follow-up tests, the Critic judges again.

        A second insufficient verdict demotes the hypothesis.
        """
        self.revisions[hypothesis.id] = self.revisions.get(hypothesis.id, 0) + 1
        tests = list(first.follow_up_tests[:MAX_FOLLOW_UP_TESTS])
        self._enter(f"chunk {self.manager.chunks_started + 1} ({hypothesis.id} revision)")
        state = self._open_chunk(goal, self._round_context(builder, overview, entity_id), "revision", hypothesis.id)
        self.trace.write(agent="Critic", action="request_revision", target="Investigator",
                         input_summary=f"{hypothesis.id} {hypothesis.family}: {hypothesis.statement}",
                         output_summary=tests, hypothesis_id=hypothesis.id, chunk=state.chunk.index)
        results: list[Observation] = []
        answered: list[dict[str, Any]] = []
        for test in tests:
            if self.cancel.is_set() or self.budget.tool_calls_used >= self.budget.max_tool_calls:
                answered.append({"test": test, "query_ids": [], "observation_id": None,
                                 "finding": "not run: tool-call cap reached"})
                continue
            follow = hypothesis.model_copy(update={"test": QuerySpec(description=FOLLOW_UP_PREFIX + test,
                                                                     sources=hypothesis.test.sources)})
            outcome = investigate(self.ctx, plan, follow, f"obs-{len(self.observations)}", context=state.chunk.text)
            queries = self._ingest(pipeline, plan, hypothesis, entity_id, outcome)
            state.queries.extend(queries)
            self.tool_cap_hit |= outcome.tool_cap_reached
            obs = outcome.observation
            with self.lock:
                if obs is not None:
                    self.observations.append(obs)
                    results.append(obs)
                elif outcome.error:
                    self.notes.append(f"Follow-up not run: {outcome.error}")
            answered.append({"test": test, "query_ids": queries, "observation_id": obs.id if obs else None,
                             "finding": obs.finding if obs else f"not run: {outcome.error or 'no observation'}"})
        reading = self.readings.get(hypothesis.id) or _Reading(None, None, "")
        verdict = self._critique(pipeline.store, builder, plan, hypothesis, entity_id, first_obs, state.chunk.text,
                                 attempt=2, follow_up_tests=tuple(tests), follow_up=tuple(results), answered=answered)
        if verdict is not None:
            reading = self._judged(hypotheses, hypothesis, verdict, reading)
        self.readings[hypothesis.id] = reading
        self._carry(goal, hypotheses, f"Revision of {hypothesis.id} ({hypothesis.family}): {reading.text}")
        self._close_chunk(state)

    # --- the Critic ------------------------------------------------------------------------------

    def _critique(
        self,
        store: WorldStore,
        builder: ContextBuilder,
        plan: Plan,
        hypothesis: Hypothesis,
        entity_id: str,
        obs: Observation | None,
        chunk_text: str,
        *,
        attempt: int = 1,
        follow_up_tests: tuple[str, ...] = (),
        follow_up: tuple[Observation, ...] = (),
        answered: list[dict[str, Any]] | None = None,
    ) -> Verdict | None:
        """One Critic call (capped at `max_chunks` per run); its trace line and World Model record."""
        if self.critic_calls >= self.config.max_chunks:
            self.notes.append(f"{hypothesis.id} was not critiqued: {self.config.max_chunks} Critic calls "
                              "(MARKOVIAN_MAX_CHUNKS) were made.")
            self.trace.write(agent=AGENT, action="cap_reached", status="cap_reached", hypothesis_id=hypothesis.id,
                             output_summary=f"Critic calls: MARKOVIAN_MAX_CHUNKS={self.config.max_chunks}")
            return None
        self.critic_calls += 1
        verdict = self.critic(CriticRequest(
            run_id=self.run_id, plan=plan, hypothesis=hypothesis, hypothesis_entity_id=entity_id, observation=obs,
            chunk_text=chunk_text, context_builder=builder, budget_chars=self.config.chunk_budget_chars,
            generate=self.generate, attempt=attempt, follow_up_tests=follow_up_tests, follow_up=follow_up,
            change=self.change_obs, change_row=self.change_row,
        ))
        if verdict is None:
            return None
        verdict_id = self._store_verdict(store, entity_id, verdict)
        self.trace.write(
            agent="Critic", action="critique", target="Orchestrator",
            input_summary=f"{hypothesis.id} {hypothesis.family}: {hypothesis.statement}",
            output_summary={"verdict": verdict.verdict, "reason": verdict.reason, "total_score": verdict.total_score},
            status="ok" if verdict.retry_count == 0 else "retried", retry_count=verdict.retry_count,
            verdict=verdict.verdict, hypothesis_id=hypothesis.id, family=hypothesis.family, attempt=attempt,
            checks=[c.model_dump() for c in verdict.checks],
            scores=verdict.scores.model_dump() if verdict.scores else None, total_score=verdict.total_score,
            follow_up_tests=verdict.follow_up_tests, follow_up_results=answered or [],
            observation_ids=verdict.observation_ids, query_ids=verdict.query_ids, sample_size=verdict.sample_size,
            sample_too_small=verdict.sample_too_small, critic_call=self.critic_calls,
            max_critic_calls=self.config.max_chunks, world_model_id=verdict_id,
        )
        return verdict

    def _store_verdict(self, store: WorldStore, entity_id: str, verdict: Verdict) -> str | None:
        """Write the verdict to the World Model with its provenance: `judges` the hypothesis, `relies_on`
        the observations behind it (named directly, or from the queries the verdict cites)."""
        try:
            verdict_id = store.put_entity("verdict", {
                "hypothesis_id": entity_id, "label": verdict.hypothesis_id, "attempt": verdict.attempt,
                "verdict": verdict.verdict, "reason": verdict.reason, "total_score": verdict.total_score,
                "scores": verdict.scores.model_dump() if verdict.scores else None,
                "checks": [c.model_dump() for c in verdict.checks], "follow_up_tests": verdict.follow_up_tests,
                "observation_ids": verdict.observation_ids, "query_ids": verdict.query_ids,
                "sample_size": verdict.sample_size, "sample_too_small": verdict.sample_too_small,
            }, agent="Critic", run_id=self.run_id)
            store.put_edge("judges", verdict_id, entity_id, agent="Critic", run_id=self.run_id)
            relied = {oid for oid in verdict.observation_ids if (e := store.get(oid)) and e.type == "observation"}
            relied |= {o.id for o in store.observations_for(entity_id) if o.content.get("query_id") in verdict.query_ids}
            for oid in sorted(relied):
                store.put_edge("relies_on", verdict_id, oid, agent="Critic", run_id=self.run_id)
            return verdict_id
        except Exception as exc:  # noqa: BLE001 - a failed write leaves the verdict in the run and the trace
            self.trace.write(agent="WorldModel", action="store_verdict", status="error",
                             output_summary=f"{type(exc).__name__}: {exc}")
            return None

    def _judged(self, hypotheses: list[Hypothesis], hypothesis: Hypothesis, verdict: Verdict,
                reading: _Reading) -> _Reading:
        """Record a verdict: status, sample flag, promotion of the next leader; the reading for the ranking."""
        status = verdict.verdict
        if status == "insufficient" and (verdict.attempt > 1 or self.revisions.get(hypothesis.id, 0) >= MAX_REVISIONS):
            status = "demoted"
        self.verdicts[hypothesis.id] = verdict
        self.status[hypothesis.id] = status
        if verdict.sample_too_small and self.sample_flag is None:
            self.sample_flag = verdict
        if status in ("refuted", "demoted") and self.leader == hypothesis.id:
            nxt = next((h.id for h in hypotheses if self.status.get(h.id) not in ("refuted", "demoted")), None)
            self._branch("promotion", f"{hypothesis.id} {status}: {verdict.reason}",
                         **{"from": hypothesis.id, "to": nxt, "reason": verdict.reason,
                            "total_score": verdict.total_score})
            self.leader = nxt
        supports = {"supported": True, "refuted": False}.get(verdict.verdict)
        label = "Critic demoted after revision" if status == "demoted" else f"Critic {verdict.verdict}"
        return _Reading(supports, reading.effect, f"{label}: {verdict.reason}")

    # --- branches and the answer ---------------------------------------------------------------

    def _significance(self, obs: Observation, row: dict[str, Any] | None) -> tuple[bool | None, dict[str, Any]]:
        """Is the change outside normal variation? With a spread from the change check's row:
        |observed - baseline| > CHANGE_VARIATION_THRESHOLD x spread. Without one: the Investigator's reading."""
        threshold = self.settings.change_variation_threshold
        spread = (row or {}).get("spread")
        spread = float(spread) if isinstance(spread, (int, float)) and not isinstance(spread, bool) else None
        numbers: dict[str, Any] = {"observed": obs.value, "baseline": obs.baseline, "spread": spread,
                                   "threshold": threshold, "n": (row or {}).get("n")}
        if spread and spread > 0 and isinstance(obs.value, (int, float)) and isinstance(obs.baseline, (int, float)):
            difference = abs(obs.value - obs.baseline)
            numbers.update(difference=round(difference, 6), spreads=round(difference / spread, 3),
                           decided_by="spread")
            return difference > threshold * spread, numbers
        numbers["decided_by"] = "investigator_reading"
        return obs.supports, numbers

    def _no_change_summary(self, plan: Plan, numbers: dict[str, Any]) -> str:
        observed, baseline, spread = numbers.get("observed"), numbers.get("baseline"), numbers.get("spread")

        def fmt(value: Any) -> str:
            return f"{value:.4g}" if isinstance(value, (int, float)) else "not measured"

        within = (f"within {numbers['threshold']:g} x the spread" if numbers.get("decided_by") == "spread"
                  else "not a significant change by the change check")
        return (f"No significant change: {plan.metric} ({plan.segment}) was {fmt(observed)} in "
                f"{plan.window.start} to {plan.window.end} against a baseline of {fmt(baseline)} "
                f"(spread {fmt(spread)}), {within}.")

    def _branch(self, branch: str, why: str, **numbers: Any) -> None:
        """One trace line per branch decision: the branch, why, and the numbers used."""
        self.trace.write(agent=AGENT, action="branch", target=None, input_summary=branch, output_summary=why,
                         branch=branch, why=why, numbers=numbers)

    def _conclude(self, stop_reason: StopReason, outcome: ReportOutcome, hypotheses: list[Hypothesis]) -> None:
        """Finish from the Reporter's outcome. With a Critic, only causes it supported are kept, refuted
        hypotheses are ruled out with the Critic's reason and query ids, and the run escalates to
        "cannot be determined" when no hypothesis was supported or the sample was too small."""
        causes, ruled_out, limitations = list(outcome.causes), list(outcome.ruled_out), list(outcome.limitations)
        determinable = outcome.determinable
        why = ""
        if self.critic_active:
            families = {h.id: h.family for h in hypotheses}
            kept, seen = [], set()
            for cause, hid in zip(outcome.causes, outcome.cause_hypotheses, strict=True):
                if self.status.get(hid) == "supported" and hid not in seen:  # one cause per hypothesis
                    kept.append(cause)
                    seen.add(hid)
            causes = [c.model_copy(update={"rank": i}) for i, c in enumerate(kept, 1)]
            refuted = [RuledOut(type=families[hid], why=f"{hid}: {v.reason}", evidence=v.query_ids)
                       for hid, v in self.verdicts.items() if self.status.get(hid) == "refuted" and hid in families]
            refuted_types = {r.type for r in refuted} | {c.type for c in causes}
            ruled_out = [*refuted, *(r for r in outcome.ruled_out if r.type not in refuted_types)]
            for h in hypotheses:
                status = self.status.get(h.id)
                verdict = self.verdicts.get(h.id)
                if status in ("demoted", "insufficient") and verdict is not None:
                    tests = "; ".join(t.rstrip(". ") for t in verdict.follow_up_tests) or "more records for this segment"
                    limitations.append(f"Unconfirmed: {h.id} ({h.family}) {verdict.reason} "
                                       f"Data that would decide it: {tests}.")
            supported = [hid for hid, st in self.status.items() if st == "supported"]
            if self.sample_flag is not None:
                flag = self.sample_flag
                why = (f"the Critic flagged the sample as too small ({flag.sample_size} records in the window, "
                       f"minimum {self.settings.critic_min_sample_size})")
                limitations.append(f"Sample too small: {flag.sample_size} records behind the change in the window "
                                   f"(CRITIC_MIN_SAMPLE_SIZE={self.settings.critic_min_sample_size}); more records "
                                   "for this segment, or a longer window, would decide it.")
            elif not supported and stop_reason in ("max_chunks", "max_tool_calls"):
                why = f"{stop_reason} was reached without a supported explanation"
            elif not supported:
                why = "every tested explanation was refuted or left unconfirmed by the Critic"
            elif not causes:
                why = "no cause in the report is one the Critic supported"
            if why:
                causes, determinable = [], False
            else:
                determinable = determinable and bool(causes)
            self._branch(
                "cannot_be_determined" if not determinable else "determined",
                why or "the Critic supported the leading explanation",
                supported=supported, refuted=[h for h, st in self.status.items() if st == "refuted"],
                demoted=[h for h, st in self.status.items() if st == "demoted"],
                unconfirmed=[h for h, st in self.status.items() if st == "insufficient"],
                untested=[h.id for h in hypotheses if h.id not in self.readings],
                critic_calls=self.critic_calls, max_critic_calls=self.config.max_chunks,
                chunks_used=self.manager.chunks_started, sample_size=getattr(self.sample_flag, "sample_size", None),
                min_sample_size=self.settings.critic_min_sample_size,
            )
        if not determinable:
            causes = []
        if determinable and causes:
            summary = f"Most likely cause ({causes[0].type}): {causes[0].summary}"
        else:
            tested = len(self.readings)
            summary = ("Cannot be determined from the data: "
                       + (why or "no tested explanation is supported by the data")
                       + f" ({tested} tested, {len(ruled_out)} ruled out).")
        self._finish(stop_reason, status="success", determinable=determinable, causes=causes,
                     ruled_out=ruled_out, limitations=limitations, summary=summary)

    # --- World Model ---------------------------------------------------------------------------

    def _ingest(
        self,
        pipeline: IngestPipeline,
        plan: Plan,
        hypothesis: Hypothesis | None,
        entity_id: str | None,
        outcome: InvestigationOutcome,
    ) -> list[str]:
        """Ingest this round's query results; return the query ids run in the round."""
        outcomes = self.data.take()
        results = [o for o in outcomes if isinstance(o, QueryResult)]
        for result in results:  # the first row of each result, e.g. the change check's spread and n
            if result.rows:
                self.query_rows[result.query_id] = dict(result.rows[0])
        written = alerts = 0
        try:
            for result in results:
                ingested = pipeline.ingest(result, run_id=self.run_id, hypothesis=entity_id, window=plan.window,
                                           baseline_window=plan.baseline_window)
                written += len(ingested.observations)
                alerts += ingested.alerts
            obs = outcome.observation
            measured = next((r for r in results if obs is not None and r.query_id == obs.query_id), None)
            if obs is not None and measured is not None and isinstance(obs.value, (int, float)):
                metric = f"{hypothesis.family} measure" if hypothesis else "change check measure"
                direction = None
                if entity_id is not None and obs.supports is not None:
                    direction = "supports" if obs.supports else "refutes"
                ingested = pipeline.ingest(
                    replace(measured, columns=[metric], rows=[{metric: obs.value}], row_count=1, truncated=False),
                    run_id=self.run_id, hypothesis=entity_id, window=plan.window,
                    baseline_window=plan.baseline_window, value_columns=(metric,),
                    baseline_rows=[{metric: obs.baseline}] if isinstance(obs.baseline, (int, float)) else None,
                    direction=direction,
                )
                written += len(ingested.observations)
                alerts += ingested.alerts
            self.trace.write(agent="WorldModel", action="ingest", input_summary=[r.query_id for r in results],
                             output_summary=f"{written} observations, {alerts} alerts",
                             hypothesis_id=hypothesis.id if hypothesis else None)
        except Exception as exc:  # noqa: BLE001 - a failed ingest leaves the round's observation in place
            self.notes.append(f"World Model ingest failed: {type(exc).__name__}")
            self.trace.write(agent="WorldModel", action="ingest", status="error",
                             output_summary=f"{type(exc).__name__}: {exc}")
        return [o.query_id for o in outcomes]

    # --- chunks and carryover ------------------------------------------------------------------

    def _evidence(self, builder: ContextBuilder, intent: Intent) -> dict[str, Any]:
        """The ContextBuilder payload for `intent`, with this run's id in selection reasons replaced.

        Every edge in the per-run store is from this run, so "run <id>" carries no information, and
        keeping it would make the prompts (and so the sample-mode cache keys) depend on the run id.
        """
        payload = builder.build(intent, self.config.chunk_budget_chars)
        marker = f"run {self.run_id}"
        for item in payload["items"]:
            item["selection_reason"] = str(item.get("selection_reason", "")).replace(marker, "this run")
        return payload

    def _goal(self, plan: Plan) -> str:
        return (f"Answer: {self.question} Metric: {plan.metric}; segment: {plan.segment}; window "
                f"{plan.window.start} to {plan.window.end} against {plan.baseline_window.start} to "
                f"{plan.baseline_window.end}.")

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_started = time.monotonic()

    def _open_chunk(self, goal: str, context: dict[str, Any], kind: str, hypothesis_id: str | None) -> _ChunkState:
        chunk = self.manager.start_chunk(goal, carryover=self.carryover, context=context,
                                         label=hypothesis_id or kind)
        return _ChunkState(chunk=chunk, kind=kind, hypothesis_id=hypothesis_id, started=time.monotonic(),
                           sent0=self.generate.sent_chars, received0=self.generate.received_chars,
                           carryover_in=self.carryover)

    def _close_chunk(self, state: _ChunkState, status: str = "ok") -> None:
        """Record the chunk's actual sizes; one trace line and one markovian log line per chunk."""
        record = self.manager.finish_chunk(
            state.chunk.index, sent_chars=self.generate.sent_chars - state.sent0,
            output_chars=self.generate.received_chars - state.received0,
        )
        carry_in = state.carryover_in
        carry_out = self.carryover if self.carryover is not carry_in else None
        if self.cancel.is_set():
            return
        self.trace.write(
            agent=AGENT, action="chunk", target="Investigator" if state.kind == "round" else "Planner",
            input_summary=f"chunk {state.chunk.index}/{self.config.max_chunks} {record.label}",
            output_summary=carry_out.render() if carry_out else None, status=status,
            chunk=state.chunk.index, max_chunks=self.config.max_chunks, kind=state.kind,
            hypothesis_id=state.hypothesis_id, queries=state.queries,
            carryover_step=carry_in.carryover_step if carry_in else None,
            carryover_out_step=carry_out.carryover_step if carry_out else None,
            projected_chars=record.projected_chars, actual_chars=record.actual_sent_chars,
            output_chars=record.output_chars, chunk_budget_chars=record.budget_chars,
            standard_chars=record.standard_chars, items_included=len(record.items_included),
            items_dropped=len(record.items_dropped), rounds_left=self.manager.rounds_left,
            duration_s=round(time.monotonic() - state.started, 3),
        )
        line = {"run_id": self.run_id, **record.to_dict(), "kind": state.kind, "hypothesis_id": state.hypothesis_id,
                "queries": state.queries, "carryover_in": carry_in.to_dict() if carry_in else None,
                "carryover_out": carry_out.to_dict() if carry_out else None}
        with self.markovian_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, default=str, ensure_ascii=False) + "\n")

    def _carry(self, goal: str, hypotheses: list[Hypothesis], headline: str) -> None:
        """Rank the hypotheses from the readings so far and run the carryover cascade."""
        ranked = sorted(
            (h for h in hypotheses if self.readings.get(h.id) and self.readings[h.id].supports is True),
            key=lambda h: (-abs(self.readings[h.id].effect or 0.0), h.priority),
        )
        ruled = [h for h in hypotheses if self.readings.get(h.id) and self.readings[h.id].supports is False]
        open_ = [h for h in hypotheses if h not in ranked and h not in ruled][:6]
        items = len(ranked) + len(ruled) + len(open_)
        # Shorten notes so the explicit state fits the carryover budget (step 1 of the cascade).
        allowance = max(NOTE_MIN_CHARS, (self.config.carryover_budget_chars - 40) // max(1, items) - 14)
        state = {
            "ranking": [{"id": h.id, "note": _clip(f"{h.family}: {self.readings[h.id].text}", allowance)}
                        for h in ranked[:6]],
            "ruled_out": [{"id": h.id, "reason": _clip(f"{h.family}: {self.readings[h.id].text}", allowance)}
                          for h in ruled[:6]],
            "open_questions": [
                _clip(f"{h.id} {h.family}: " + (self.readings[h.id].text if h.id in self.readings
                                                  else f"untested: {h.statement}"), allowance)
                for h in open_
            ],
        }
        lines = [headline]
        lines += [f"{i}. {h.id} supported: {self.readings[h.id].text}" for i, h in enumerate(ranked, 1)]
        lines += [f"{h.id} ruled out: {self.readings[h.id].text}" for h in ruled]
        lines += [f"Open question: {q}" for q in state["open_questions"]]
        carryover = build_carryover(
            RoundOutput(text="\n".join(lines), state=state), config=self.config,
            rounds_left=self.manager.rounds_left, generate=self.generate, previous=self.carryover, goal=goal,
            run_id=self.run_id, fallback_ids=self.fallback_ids,
        )
        with self.lock:
            self.carryover = carryover

    # --- results -------------------------------------------------------------------------------

    def _partial_findings(self) -> list[str]:
        with self.lock:
            found = [f"Measured before the stop: {o.finding}" for o in self.observations]
        return found

    def _fail(self, code: str, message: str, *, stop_reason: StopReason = "error") -> Result | None:
        return self._finish(stop_reason, status="error", determinable=False,
                            error=ResultError(code=code, message=message))

    def _finish(self, stop_reason: StopReason, **fields: Any) -> Result | None:
        """Build the result once (worker or watcher, whichever stops first); None if already built."""
        with self.lock:
            if self.finished:
                return None
            self.finished = True
            limitations = list(fields.pop("limitations", []))
            for note in self.notes:
                if note not in limitations:
                    limitations.append(note)
            if self.sample_mode:
                limitations.append(SAMPLE_MODE_NOTE)
            records = self.manager.report()
            standard = sum(r["standard_tokens"] for r in records)
            markovian = sum(r["projected_tokens"] for r in records)
            built = Result(
                run_id=self.run_id,
                question=self.question,
                change=self.change,
                agents=AGENTS,
                trace_id=self.run_id,
                log_file=_display_path(self.trace.path),
                query_log=_display_path(self.query_log) if self.query_log else None,
                token_report=TokenReport(
                    standard_estimate=standard, markovian_actual=markovian,
                    saving_percent=round(100.0 * (1 - markovian / standard), 1) if standard else 0.0,
                ),
                execution_time_seconds=round(time.monotonic() - self.started, 3),
                sample_mode=self.sample_mode,
                limitations=limitations,
                stop_reason=stop_reason,
                **fields,
            )
            self.result = built
        self.trace.write(
            agent=AGENT, action="finish", status=built.status, stop_reason=stop_reason,
            output_summary={"status": built.status, "stop_reason": stop_reason, "causes": len(built.causes),
                            "error": built.error.model_dump() if built.error else None},
            chunks_used=self.manager.chunks_started, max_chunks=self.config.max_chunks,
            tool_calls_used=self.budget.tool_calls_used,
        )
        # As in the simple loop: the answer still reaches the caller if the result file cannot be
        # written; `GET /runs/{id}` then reports the run as not found.
        with contextlib.suppress(OSError):
            self.trace.write_result(built.model_dump(mode="json"))
        return built


def run_markovian(
    question: str,
    *,
    run_id: str,
    generate: GenerateFn,
    data: DataLayer,
    settings: Settings | None = None,
    config: MarkovianConfig | None = None,
    log_dir: Path | str | None = None,
    sample_mode: bool | None = None,
    critic: CriticHook | None = None,
    world_db_path: str = ":memory:",
) -> Result:
    """Investigate `question` in Markovian chunks and return a `Result` with `stop_reason`; never raises.

    `critic` defaults to the real Critic (`app.agents.critic.Critic`); pass `critic=critic_hook` for the
    no-op critic (the Sprint 8 behaviour) or any `CriticHook`.
    `config` defaults to `MarkovianConfig.from_env()`; an invalid environment gives an error result.
    `world_db_path` is the run's World Model store (default in memory; its log goes to
    `logs/world-<run>.jsonl`).
    """
    settings = settings or get_settings()
    sample_mode = settings.sample_mode if sample_mode is None else sample_mode
    log_path = Path(log_dir) if log_dir else resolve_path(settings.log_dir)
    try:
        config = config or MarkovianConfig.from_env()
    except ValueError as exc:
        trace = TraceWriter(log_path, run_id)
        trace.write(agent=AGENT, action="finish", status="error", output_summary=str(exc), stop_reason="error")
        return Result(
            run_id=run_id, status="error", question=question, determinable=False, agents=AGENTS, trace_id=run_id,
            log_file=_display_path(trace.path), execution_time_seconds=0.0, sample_mode=sample_mode,
            error=ResultError(code="invalid_config", message=str(exc)), stop_reason="error",
        )
    run = _Run(question, run_id=run_id, generate=generate, data=data, settings=settings, config=config,
               log_dir=log_path, sample_mode=sample_mode, critic=critic, world_db_path=world_db_path)
    return run.execute()

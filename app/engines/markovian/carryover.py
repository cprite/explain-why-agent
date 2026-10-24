"""Carryover: the state passed from one Markovian chunk to the next (architecture §5.2).

    carryover = build_carryover(round_output, config=config, rounds_left=3, generate=generator)

The state is the current ranking, what has been ruled out (with the reason), the open questions and
the rounds left. It is produced by a four-step cascade; each step runs only if the one before it
failed or produced a state larger than `carryover_budget_chars` (measured on the rendered text, the
form that goes into the next chunk's input):

1. `explicit_state` — the structured state the round returned, validated against `CarryoverDraft`;
2. `model_compression` — one call through the injected generator (no HTTP in this package), the
   reply validated against `CarryoverDraft`, with `compression_timeout_seconds` as a wall-clock
   limit;
3. `heuristic_extraction` — deterministic: ranking / ruled-out / open lines pulled from the round
   text by pattern, trailing items dropped until the state fits;
4. `truncation` — the round text cut at a word boundary to the budget; always succeeds.

`Carryover.carryover_step` names the step that produced the result and `attempts` lists every step
tried with its outcome. Sample mode runs the cascade on a recorded round with a stub generator:

    python -m app.engines.markovian.carryover --sample
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import get_settings, resolve_path
from app.engines.markovian.config import MarkovianConfig
from app.llm.generator import GenerateFn, GenerationResult, Message, parse_json_reply
from app.schemas import validation_summary

CarryoverStep = Literal["explicit_state", "model_compression", "heuristic_extraction", "truncation"]
STEPS: tuple[CarryoverStep, ...] = ("explicit_state", "model_compression", "heuristic_extraction", "truncation")
AttemptStatus = Literal["ok", "failed", "over_budget"]

MAX_ITEMS = 6
"""Cap on each list in the state (ranking, ruled out, open questions)."""
HEURISTIC_ITEM_CHARS = 200
"""Heuristic items are clipped to this many characters."""
HEURISTIC_MAX_LINES = 400
"""Heuristic extraction reads at most this many lines of round text."""
COMPRESSION_ROLE = "compressor"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankedItem(_Model):
    """One explanation still in play, most likely first."""

    id: str = Field(min_length=1, max_length=40, description="Hypothesis id such as H3.")
    note: str = Field(default="", max_length=400, description="Why it ranks here, with the key number.")


class RuledOutItem(_Model):
    """One explanation rejected, with the reason."""

    id: str = Field(min_length=1, max_length=40, description="Hypothesis id such as H1.")
    reason: str = Field(min_length=1, max_length=400, description="Why it was rejected, with the key number.")


class CarryoverDraft(_Model):
    """The schema for steps 1 and 2: what a round or the compressor reports as the state."""

    ranking: list[RankedItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    ruled_out: list[RuledOutItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    open_questions: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)

    def is_empty(self) -> bool:
        """True when the draft carries nothing forward."""
        return not (self.ranking or self.ruled_out or [q for q in self.open_questions if q.strip()])


@dataclass
class RoundOutput:
    """What one chunk (round) produced: its text and, if the round returned one, a structured state."""

    text: str
    state: Mapping[str, Any] | None = None


@dataclass
class StepAttempt:
    """One cascade step tried: its outcome, a readable detail and the rendered size if it got that far."""

    step: CarryoverStep
    status: AttemptStatus
    detail: str
    used_chars: int | None = None


@dataclass
class Carryover:
    """The state handed to the next chunk."""

    ranking: list[RankedItem]
    ruled_out: list[RuledOutItem]
    open_questions: list[str]
    rounds_left: int
    budget_chars: int
    carryover_step: CarryoverStep
    notes: str = ""
    attempts: list[StepAttempt] = field(default_factory=list)

    def render(self) -> str:
        """The compact text that goes into the next chunk's input; its length is `used_chars`."""
        return render_state(self.ranking, self.ruled_out, self.open_questions, self.rounds_left, self.notes)

    @property
    def used_chars(self) -> int:
        """Size of the rendered carryover."""
        return len(self.render())

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form for the run log."""
        return {
            "carryover_step": self.carryover_step,
            "used_chars": self.used_chars,
            "budget_chars": self.budget_chars,
            "rounds_left": self.rounds_left,
            "ranking": [item.model_dump() for item in self.ranking],
            "ruled_out": [item.model_dump() for item in self.ruled_out],
            "open_questions": list(self.open_questions),
            "notes": self.notes,
            "text": self.render(),
            "attempts": [vars(a).copy() for a in self.attempts],
        }


def render_state(
    ranking: Sequence[RankedItem],
    ruled_out: Sequence[RuledOutItem],
    open_questions: Sequence[str],
    rounds_left: int,
    notes: str = "",
) -> str:
    """Render a state as the few lines the next chunk reads. Empty sections are left out."""
    lines = [f"Rounds left: {rounds_left}"]
    if ranking:
        lines.append(
            "Ranking: " + "; ".join(f"{i}) {r.id}" + (f": {r.note}" if r.note else "") for i, r in enumerate(ranking, 1))
        )
    if ruled_out:
        lines.append("Ruled out: " + "; ".join(f"{r.id} ({r.reason})" for r in ruled_out))
    questions = [q for q in open_questions if q.strip()]
    if questions:
        lines.append("Open questions: " + "; ".join(questions))
    if notes:
        lines.append(f"Notes: {notes}")
    return "\n".join(lines)


class _StepFailed(Exception):
    """A cascade step could not produce a state."""


def _from_draft(draft: CarryoverDraft, step: CarryoverStep, rounds_left: int, budget: int) -> Carryover:
    return Carryover(
        ranking=list(draft.ranking),
        ruled_out=list(draft.ruled_out),
        open_questions=[q.strip() for q in draft.open_questions if q.strip()],
        rounds_left=rounds_left,
        budget_chars=budget,
        carryover_step=step,
    )


def _validate_draft(data: Any, source: str) -> CarryoverDraft:
    if not isinstance(data, Mapping):
        raise _StepFailed(f"{source} is not an object")
    try:
        draft = CarryoverDraft.model_validate(dict(data))
    except ValidationError as exc:
        raise _StepFailed(f"{source} does not match CarryoverDraft: {validation_summary(exc)}") from None
    if draft.is_empty():
        raise _StepFailed(f"{source} is empty (no ranking, ruled-out item or open question)")
    return draft


# --- Step 1: explicit state -------------------------------------------------------------------------


def explicit_state(round_output: RoundOutput) -> CarryoverDraft:
    """The structured state the round returned, validated."""
    if round_output.state is None:
        raise _StepFailed("the round returned no structured state")
    return _validate_draft(round_output.state, "the round's state")


# --- Step 2: model compression ----------------------------------------------------------------------

COMPRESSION_SYSTEM_PROMPT = (
    "You compress the state of a data investigation so the next round can continue from it without the "
    "full history. Keep only what the next round needs: the explanations still in play, most likely "
    "first, each with the key number; the explanations ruled out, each with the reason; and the open "
    "questions. At most {max_items} items per list. The whole state must fit in {budget} characters "
    "when written as short lines, so be terse. Do not invent findings that are not in the input."
)


def compression_messages(
    round_output: RoundOutput, *, goal: str, previous: Carryover | None, budget: int, preview_chars: int
) -> list[Message]:
    """The single request sent to the compressor: goal, previous carryover and a preview of the round."""
    text = " ".join(round_output.text.split())
    preview = text if len(text) <= preview_chars else text[:preview_chars] + " [...]"
    parts = []
    if goal:
        parts.append(f"Goal: {goal}")
    parts.append("Previous state:\n" + (previous.render() if previous else "(first round)"))
    parts.append("This round:\n" + (preview or "(no text)"))
    return [
        {"role": "system", "content": COMPRESSION_SYSTEM_PROMPT.format(max_items=MAX_ITEMS, budget=budget)},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


class CompressionTimeout(Exception):
    """The compression call did not finish within its time limit."""


def call_with_timeout(fn: Callable[[], GenerationResult], timeout_seconds: float) -> GenerationResult:
    """Run `fn` in a daemon thread and give up after `timeout_seconds` (`CompressionTimeout`).

    On timeout the thread is abandoned, not killed (Python cannot stop a thread); the generator's own
    HTTP timeouts end it later, and as a daemon it never holds up process exit. Exceptions raised by
    `fn` are re-raised here.
    """
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller below
            outcome["error"] = exc

    worker = threading.Thread(target=target, name="carryover-compress", daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise CompressionTimeout(f"no answer within {timeout_seconds:g} s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def model_compression(
    round_output: RoundOutput,
    *,
    generate: GenerateFn | None,
    goal: str,
    previous: Carryover | None,
    config: MarkovianConfig,
    run_id: str | None,
) -> CarryoverDraft:
    """One generator call, schema-validated, with a wall-clock timeout."""
    if generate is None:
        raise _StepFailed("no generator injected")
    messages = compression_messages(
        round_output,
        goal=goal,
        previous=previous,
        budget=config.carryover_budget_chars,
        preview_chars=config.chunk_budget_chars,
    )
    timeout = config.compression_timeout_seconds
    try:
        result = call_with_timeout(
            lambda: generate(messages, schema=CarryoverDraft, role=COMPRESSION_ROLE, run_id=run_id), timeout
        )
    except CompressionTimeout:
        raise _StepFailed(f"the generator did not answer within {timeout:g} s") from None
    except Exception as exc:  # noqa: BLE001 - any generator failure moves the cascade on
        raise _StepFailed(f"the generator raised {type(exc).__name__}: {exc}") from None
    if not isinstance(result, GenerationResult):
        raise _StepFailed(f"the generator returned {type(result).__name__}, not a GenerationResult")
    if not result.ok:
        error = result.error or {}
        raise _StepFailed(f"the generator failed: {error.get('code', 'error')}: {error.get('message', '')}".rstrip())
    parsed = result.parsed
    if parsed is None:
        parsed, problem = parse_json_reply(result.content or "", CarryoverDraft)
        if parsed is None:
            raise _StepFailed(f"the reply was rejected: {problem}")
    return _validate_draft(parsed, "the compressed reply")


# --- Step 3: heuristic extraction -------------------------------------------------------------------

_HYPOTHESIS_ID = re.compile(r"\bH\d{1,3}\b")
_RULED_OUT = re.compile(
    r"\b(ruled out|refuted|rejected|not supported|unsupported|does not explain|did not (?:cause|drive|explain)|excluded)\b",
    re.IGNORECASE,
)
_RANKED = re.compile(
    r"^\s*(?:\d+[.)]\s|(?:cause|rank(?:ed|ing)?)\s*#?\d|(?:leading|leader|most likely|top cause|supported|"
    r"confirmed)\b)",
    re.IGNORECASE,
)
_OPEN = re.compile(
    r"\b(open question|unresolved|unclear|unknown|next check|still to (?:check|test)|follow[- ]up|to be tested)\b",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def _item_id(line: str, prefix: str, index: int) -> str:
    match = _HYPOTHESIS_ID.search(line)
    return match.group(0) if match else f"{prefix}{index}"


def heuristic_items(text: str) -> CarryoverDraft:
    """Deterministically pull ranking, ruled-out and open items from round text, line by line.

    A line that names a rejection ("ruled out", "refuted", "not supported", ...) is a ruled-out item;
    otherwise a numbered line or one starting "leading", "supported", "cause 1", ... is a ranking item;
    otherwise a question or a line naming a follow-up / open question is an open question. Each list
    keeps the first `MAX_ITEMS` distinct items; a hypothesis ruled out is removed from the ranking and
    not ranked again.
    """
    ranking: list[RankedItem] = []
    ruled_out: list[RuledOutItem] = []
    open_questions: list[str] = []
    seen_ids: set[str] = set()
    for raw in text.splitlines()[:HEURISTIC_MAX_LINES]:
        line = _BULLET.sub("", raw).strip()
        if len(line) < 8:
            continue
        clipped = _clip(line, HEURISTIC_ITEM_CHARS)
        if _RULED_OUT.search(line):
            item_id = _item_id(line, "R", len(ruled_out) + 1)
            # A later rejection wins over an earlier ranking of the same hypothesis.
            ranking = [r for r in ranking if r.id != item_id]
            if item_id not in {r.id for r in ruled_out} and len(ruled_out) < MAX_ITEMS:
                ruled_out.append(RuledOutItem(id=item_id, reason=clipped))
                seen_ids.add(item_id)
        elif _RANKED.search(raw):
            item_id = _item_id(line, "C", len(ranking) + 1)
            if item_id not in seen_ids and len(ranking) < MAX_ITEMS:
                ranking.append(RankedItem(id=item_id, note=clipped))
                seen_ids.add(item_id)
        elif (line.endswith("?") or _OPEN.search(line)) and len(open_questions) < MAX_ITEMS:
            if clipped not in open_questions:
                open_questions.append(clipped)
    return CarryoverDraft(ranking=ranking, ruled_out=ruled_out, open_questions=open_questions)


def heuristic_extraction(round_output: RoundOutput, *, rounds_left: int, budget: int) -> tuple[CarryoverDraft, int]:
    """Step 3: the extracted items, with trailing items dropped until the rendered state fits.

    Returns the draft and how many items were dropped. Raises when nothing is extractable or not even
    one item fits.
    """
    draft = heuristic_items(round_output.text)
    if draft.is_empty():
        raise _StepFailed("no ranking, ruled-out or open-question lines found in the round text")
    ranking, ruled_out, questions = list(draft.ranking), list(draft.ruled_out), list(draft.open_questions)
    dropped = 0
    # Least important first: open questions, then ruled-out items, then the tail of the ranking.
    while len(render_state(ranking, ruled_out, questions, rounds_left)) > budget:
        for bucket in (questions, ruled_out, ranking):
            if bucket:
                bucket.pop()
                dropped += 1
                break
        else:
            break
    fitted = CarryoverDraft(ranking=ranking, ruled_out=ruled_out, open_questions=questions)
    if fitted.is_empty():
        raise _StepFailed(f"no extracted item fits in {budget} characters")
    return fitted, dropped


# --- Step 4: truncation -----------------------------------------------------------------------------


def truncation(
    round_output: RoundOutput, *, previous: Carryover | None, rounds_left: int, budget: int
) -> Carryover:
    """Step 4: the round text (or, if empty, the previous carryover) cut to fit. Always succeeds."""
    source = " ".join(round_output.text.split()) or (" ".join(previous.render().split()) if previous else "")
    base = render_state([], [], [], rounds_left)
    available = budget - len(base) - len("\nNotes: ")
    notes = ""
    if source and available > 1:
        notes = source if len(source) <= available else _clip(source, available)
    carryover = Carryover([], [], [], rounds_left, budget, "truncation", notes=notes)
    if carryover.used_chars > budget:  # only possible with a budget below the header; keep the header cut
        carryover.notes = ""
    return carryover


# --- The cascade ------------------------------------------------------------------------------------


def build_carryover(
    round_output: RoundOutput,
    *,
    config: MarkovianConfig,
    rounds_left: int,
    generate: GenerateFn | None = None,
    previous: Carryover | None = None,
    goal: str = "",
    run_id: str | None = None,
) -> Carryover:
    """Run the four-step cascade and return the first state that is valid and within budget."""
    budget = config.carryover_budget_chars
    rounds_left = max(0, rounds_left)
    attempts: list[StepAttempt] = []

    def accept(carryover: Carryover, detail: str) -> Carryover | None:
        used = carryover.used_chars
        if used > budget:
            attempts.append(StepAttempt(carryover.carryover_step, "over_budget", f"{used} > {budget} chars", used))
            return None
        attempts.append(StepAttempt(carryover.carryover_step, "ok", detail, used))
        carryover.attempts = attempts
        return carryover

    steps: list[tuple[CarryoverStep, Callable[[], tuple[CarryoverDraft, str]]]] = [
        ("explicit_state", lambda: (explicit_state(round_output), "validated the round's structured state")),
        (
            "model_compression",
            lambda: (
                model_compression(
                    round_output, generate=generate, goal=goal, previous=previous, config=config, run_id=run_id
                ),
                "one generator call, reply validated",
            ),
        ),
        ("heuristic_extraction", lambda: _heuristic(round_output, rounds_left, budget)),
    ]
    for step, run in steps:
        try:
            draft, detail = run()
        except _StepFailed as exc:
            attempts.append(StepAttempt(step, "failed", str(exc)))
            continue
        accepted = accept(_from_draft(draft, step, rounds_left, budget), detail)
        if accepted is not None:
            return accepted

    final = truncation(round_output, previous=previous, rounds_left=rounds_left, budget=budget)
    attempts.append(StepAttempt("truncation", "ok", "hard cut to the budget", final.used_chars))
    final.attempts = attempts
    return final


def _heuristic(round_output: RoundOutput, rounds_left: int, budget: int) -> tuple[CarryoverDraft, str]:
    draft, dropped = heuristic_extraction(round_output, rounds_left=rounds_left, budget=budget)
    count = len(draft.ranking) + len(draft.ruled_out) + len(draft.open_questions)
    detail = f"extracted {count} items" + (f", dropped {dropped} to fit" if dropped else "")
    return draft, detail


# --- Sample mode ------------------------------------------------------------------------------------


SAMPLE_GOAL = "Why did order volume spike on 24 November 2017?"
"""The Day 1 question the recorded round belongs to."""


def recorded_report(cache_dir: Path) -> tuple[str, dict[str, Any]]:
    """The first recorded Reporter reply (by cache key) that asked for more investigation.

    Returns the cache key and the parsed reply. That reply is the end of a round: it ranks the causes
    still in play, lists what was ruled out and proposes the next hypotheses.
    """
    for path in sorted(cache_dir.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            reply = json.loads(entry.get("reply", ""))
        except (OSError, ValueError):
            continue
        if entry.get("schema") == "ReportDraft" and isinstance(reply, dict) and reply.get("complete") is False:
            return path.stem, reply
    raise FileNotFoundError(f"no recorded ReportDraft round with complete=false in {cache_dir}")


def round_from_report(report: Mapping[str, Any]) -> RoundOutput:
    """The round as the orchestrator will log it: a text transcript plus the structured state."""
    lines: list[str] = []
    for rank, cause in enumerate(report.get("causes", []), 1):
        lines.append(
            f"Cause {rank}: {cause.get('hypothesis_id')} ({cause.get('type')}), confidence "
            f"{cause.get('confidence')}: {cause.get('summary')}"
        )
        for statement in cause.get("statements", []):
            lines.append(f"  - {statement.get('kind')}: {statement.get('text')}")
    for item in report.get("ruled_out", []):
        lines.append(f"Ruled out: {item.get('hypothesis_id')} ({item.get('type')}): {item.get('why')}")
    for limitation in report.get("limitations", []):
        lines.append(f"Limitation: {limitation}")
    for hypothesis in report.get("follow_up", []):
        lines.append(f"Follow-up {hypothesis.get('id')}: {hypothesis.get('statement')}")
    state = {
        "ranking": [
            {"id": c.get("hypothesis_id"), "note": f"{c.get('summary')} (confidence {c.get('confidence')})"}
            for c in report.get("causes", [])
        ][:MAX_ITEMS],
        "ruled_out": [{"id": r.get("hypothesis_id"), "reason": r.get("why")} for r in report.get("ruled_out", [])][
            :MAX_ITEMS
        ],
        "open_questions": [f"{h.get('id')}: {h.get('statement')}" for h in report.get("follow_up", [])][:MAX_ITEMS],
    }
    return RoundOutput(text="\n".join(lines), state=state)


class SampleStubGenerator:
    """A scripted compressor for sample mode and tests: answers from a fixed reply, or fails on purpose."""

    def __init__(self, mode: Literal["reply", "raise", "invalid_json", "error"], reply: Mapping[str, Any] | None = None):
        self.mode = mode
        self.reply = dict(reply or {})
        self.calls = 0

    def __call__(
        self,
        messages: list[Message],
        *,
        schema: type[BaseModel] | None = None,
        role: str = "default",
        run_id: str | None = None,
    ) -> GenerationResult:
        self.calls += 1
        if self.mode == "raise":
            raise RuntimeError("stub generator: provider unavailable")
        if self.mode == "error":
            return GenerationResult(ok=False, provider="stub", error={"code": "offline", "message": "stub offline"})
        if self.mode == "invalid_json":
            return GenerationResult(ok=True, provider="stub", content="Ranking: H3 first, then H4 {not json")
        return GenerationResult(ok=True, provider="stub", content=json.dumps(self.reply))


def _print_carryover(title: str, carryover: Carryover) -> None:
    print(f"== {title}")
    for attempt in carryover.attempts:
        size = f" [{attempt.used_chars}/{carryover.budget_chars} chars]" if attempt.used_chars is not None else ""
        print(f"   step {STEPS.index(attempt.step) + 1} {attempt.step}: {attempt.status}{size} - {attempt.detail}")
    print(
        f"   -> carryover_step={carryover.carryover_step} used_chars={carryover.used_chars} "
        f"budget_chars={carryover.budget_chars}"
    )
    for line in carryover.render().splitlines():
        print(f"   | {line}")
    print()


def run_sample(config: MarkovianConfig | None = None) -> int:
    """Run the cascade on the recorded round four ways, forcing each fallback in turn."""
    config = config or MarkovianConfig.from_env()
    cache_dir = resolve_path(get_settings().llm_cache_dir)
    key, report = recorded_report(cache_dir)
    recorded = round_from_report(report)
    print(f"Recorded round: Reporter reply {key[:12]} from {cache_dir.name}/ (Day 1 question, complete=false)")
    print(f"Budget: carryover_budget_chars={config.carryover_budget_chars}; no network, stub generator only.\n")
    no_state = RoundOutput(text=recorded.text, state=None)
    invalid_state = RoundOutput(text=recorded.text, state={"ranking": "H3 then H4"})
    # A round whose text has numbers but no verdict lines: nothing for the heuristic to extract.
    observation = next((line for line in recorded.text.splitlines() if "measured:" in line), recorded.text)
    no_items = RoundOutput(text=observation.split("measured:", 1)[-1].strip(), state={"ruled_out": [{"id": "H1"}]})
    compressed = {
        "ranking": recorded.state["ranking"][:2] if recorded.state else [],
        "ruled_out": recorded.state["ruled_out"] if recorded.state else [],
        "open_questions": [],
    }
    cases = [
        ("A. recorded round with its structured state", recorded, SampleStubGenerator("reply", compressed)),
        ("B. state missing -> stub compressor answers", no_state, SampleStubGenerator("reply", compressed)),
        ("C. state invalid, compressor raises -> heuristic", invalid_state, SampleStubGenerator("raise")),
        ("D. state invalid, reply not JSON, no verdict lines -> truncation", no_items, SampleStubGenerator("invalid_json")),
    ]
    rounds_left = config.max_chunks - 2
    expected = ["explicit_state", "model_compression", "heuristic_extraction", "truncation"]
    ok = True
    for (title, round_output, stub), want in zip(cases, expected, strict=True):
        carryover = build_carryover(
            round_output, config=config, rounds_left=rounds_left, generate=stub, goal=SAMPLE_GOAL
        )
        _print_carryover(title, carryover)
        ok = ok and carryover.carryover_step == want and carryover.used_chars <= config.carryover_budget_chars
    print("Sample cascade: " + ("OK, each fallback step used as expected, all within budget" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """Command line: `--sample` runs the cascade on a recorded round (no network, no credentials)."""
    parser = argparse.ArgumentParser(prog="python -m app.engines.markovian.carryover", description=__doc__.split("\n")[0])
    parser.add_argument("--sample", action="store_true", help="run the cascade on a recorded round with a stub generator")
    args = parser.parse_args(argv)
    if not args.sample:
        parser.print_help()
        return 2
    return run_sample()


if __name__ == "__main__":
    sys.exit(main())

"""Pydantic v2 schemas for the investigation: question, plan, hypotheses, observations, verdicts
and the final result (architecture §4 and §7).

The result shape is the contract with the API, the web page and the evaluation. Every statement in
a cause is marked `measured` (it rests on a query and a number) or `inferred` (a conclusion drawn
from measurements); a measured statement must name the queries it rests on.

`json_schemas()` exports the JSON Schema of every model; the model generator sends the schema of
the expected reply with each JSON-mode call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)

CauseType = Literal[
    "volume",
    "price_discount",
    "mix_shift",
    "single_seller",
    "logistics_delay",
    "product_quality",
    "marketing_funnel",
    "data_artefact",
    "external_unknown",
]
"""Hypothesis families from architecture §4."""

HYPOTHESIS_FAMILIES: tuple[str, ...] = CauseType.__args__  # type: ignore[attr-defined]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(_Model):
    """A question put to the system."""

    text: str = Field(min_length=3, description="The question in plain language.")
    run_id: str | None = None
    sample_mode: bool = True


class Window(_Model):
    """A date window, ISO dates, start inclusive and end exclusive."""

    start: str = Field(description="ISO date, inclusive.")
    end: str = Field(description="ISO date, exclusive.")


class QuerySpec(_Model):
    """What a hypothesis needs measured, written by the Planner for the Investigator."""

    description: str = Field(description="What to measure, in words, in the window and the baseline.")
    sources: list[str] = Field(default_factory=list, description="Sources the query will touch.")


class Hypothesis(_Model):
    """One candidate explanation to test."""

    id: str = Field(description="Short id such as H1.")
    family: CauseType
    statement: str = Field(description="The explanation, phrased so data can confirm or refute it.")
    priority: int = Field(ge=1, description="1 is tested first.")
    test: QuerySpec


class Plan(_Model):
    """The Planner's investigation plan."""

    question: str
    metric: str = Field(description="The metric that moved, e.g. daily order count.")
    segment: str = Field(description="The slice the question is about, or 'all'.")
    window: Window
    baseline_window: Window
    change_check: QuerySpec = Field(description="The query that confirms the change is real.")
    change_is_real: bool | None = Field(
        default=None, description="Filled after the change check runs; None until then."
    )
    hypotheses: list[Hypothesis] = Field(min_length=2, max_length=4)


class Observation(_Model):
    """A measured fact with its provenance."""

    id: str
    hypothesis_id: str | None = Field(default=None, description="None for the change check.")
    query_id: str
    source: str = Field(description="Source(s) queried; 'orders+payments' for a cross-source query.")
    sql: str
    finding: str = Field(description="One sentence with the numbers.")
    value: float | None = None
    baseline: float | None = None
    effect: float | None = Field(default=None, description="Relative change (value/baseline - 1).")
    supports: bool | None = Field(default=None, description="Does it support the hypothesis?")


CheckName = Literal["alternative_cause", "concentration", "sample_size", "date_basis", "data_artefact"]
"""The Critic's disproof checks (architecture §4), each named in its output."""

CHECK_NAMES: tuple[str, ...] = CheckName.__args__  # type: ignore[attr-defined]

SUPPORTED_MIN_SCORE = 7
"""A critique total (of 9) at or above this supports the hypothesis; below it is insufficient."""


class CritiqueScores(_Model):
    """The Critic's scored critique, 0 to 3 on each point (architecture §4)."""

    supported_by_data: int = Field(ge=0, le=3, description="Is it supported by the data?")
    explains_size_and_timing: int = Field(ge=0, le=3, description="Does it explain the size and timing of the change?")
    alternatives_excluded: int = Field(ge=0, le=3, description="Are the alternative explanations excluded?")

    @property
    def total(self) -> int:
        """The sum of the three scores, 0 to 9."""
        return self.supported_by_data + self.explains_size_and_timing + self.alternatives_excluded


class CriticCheck(_Model):
    """One disproof check and what it found."""

    name: CheckName
    outcome: Literal["passed", "failed", "not_checked"] = Field(
        description="passed: the check did not break the hypothesis; failed: it did; not_checked: no evidence."
    )
    detail: str = Field(default="", description="One sentence with the numbers the check rests on.")


class Verdict(_Model):
    """The Critic's judgement on one hypothesis.

    The fields after `follow_up_tests` are optional so that verdicts written before the Critic existed
    (and hooks that give only a verdict and a reason) still validate.
    """

    hypothesis_id: str
    verdict: Literal["supported", "refuted", "insufficient"]
    reason: str
    follow_up_tests: list[str] = Field(default_factory=list)
    scores: CritiqueScores | None = None
    total_score: int | None = Field(default=None, ge=0, le=9)
    checks: list[CriticCheck] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list, description="Evidence the verdict relies on.")
    query_ids: list[str] = Field(default_factory=list, description="Queries behind that evidence.")
    sample_size: int | None = Field(default=None, description="Records behind the change in the window.")
    sample_too_small: bool = False
    attempt: int = Field(default=1, ge=1, description="1 for the first critique, 2 after the revision.")
    retry_count: int = Field(default=0, ge=0, description="Invalid replies retried before this verdict.")


class Change(_Model):
    """The change the question is about, as measured."""

    metric: str
    segment: str
    window: str
    baseline: float | None = None
    observed: float | None = None
    significant: bool | None = None
    spread: float | None = Field(
        default=None, description="Normal variation of the measure in the baseline (standard deviation)."
    )

    @model_serializer(mode="wrap")
    def _drop_unset_spread(self, handler):  # unannotated: a return type would change the JSON schema
        # Only the orchestrator measures a spread; the simple loop's output keeps its Sprint 2 shape.
        data = handler(self)
        if isinstance(data, dict) and data.get("spread", ...) is None:
            del data["spread"]
        return data


class Statement(_Model):
    """One statement in a cause, marked measured or inferred (architecture §4)."""

    text: str
    kind: Literal["measured", "inferred"]
    query_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _measured_needs_query(self) -> Statement:
        if self.kind == "measured" and not self.query_ids:
            raise ValueError("a measured statement must name at least one query_id")
        return self


class Evidence(_Model):
    """A pointer from a cause to the observation and query behind it."""

    observation_id: str
    source: str
    query_id: str
    finding: str


class Cause(_Model):
    """A ranked cause with its evidence."""

    rank: int = Field(ge=1)
    type: CauseType
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    statements: list[Statement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)
    next_checks: list[str] = Field(default_factory=list)


class RuledOut(_Model):
    """An explanation that was tested and rejected."""

    type: CauseType
    why: str
    evidence: list[str] = Field(default_factory=list, description="Query ids behind the rejection.")


class AgentInfo(_Model):
    """An agent that took part in the run."""

    name: str
    role: str


class TokenReport(_Model):
    """Projected versus actual token use (filled by the Markovian engine in a later sprint)."""

    standard_estimate: int = 0
    markovian_actual: int = 0
    saving_percent: float = 0.0


StopReason = Literal["completed", "max_chunks", "max_tool_calls", "timeout", "no_hypotheses", "error"]
"""Why an orchestrated (Markovian) run stopped."""


class ResultError(_Model):
    """Why a run did not produce an answer."""

    code: str
    message: str


class Result(_Model):
    """The final answer of a run (architecture §7)."""

    run_id: str
    status: Literal["success", "error"]
    question: str
    change: Change | None = None
    determinable: bool
    causes: list[Cause] = Field(default_factory=list)
    ruled_out: list[RuledOut] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    agents: list[AgentInfo] = Field(default_factory=list)
    trace_id: str
    log_file: str
    query_log: str | None = None
    token_report: TokenReport = Field(default_factory=TokenReport)
    execution_time_seconds: float = Field(ge=0.0)
    sample_mode: bool = False
    error: ResultError | None = None
    stop_reason: StopReason | None = Field(
        default=None, description="Why the Markovian orchestrator stopped; None for the simple loop."
    )
    summary: str | None = Field(
        default=None,
        description="One line for the reader (Markovian orchestrator); never names a cause when determinable is false.",
    )

    @model_serializer(mode="wrap")
    def _drop_unset_stop_reason(self, handler):  # unannotated: a return type would change the JSON schema
        # The simple loop has no stop reason or summary; its output keeps the Sprint 2 shape.
        data = handler(self)
        if isinstance(data, dict):
            for key in ("stop_reason", "summary"):
                if data.get(key, ...) is None:
                    del data[key]
        return data

    @model_validator(mode="after")
    def _consistent(self) -> Result:
        if self.status == "error" and self.error is None:
            raise ValueError("an error result must carry an error")
        if not self.determinable and self.causes:
            raise ValueError("an undeterminable result must not assert causes")
        ranks = [cause.rank for cause in self.causes]
        if ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
            raise ValueError("causes must be ordered by unique rank")
        return self


# --- Agent reply schemas: what the model returns to each agent (JSON mode). ---------------------


class SqlProposal(_Model):
    """The Investigator's model reply: one read-only statement for a test."""

    sql: str = Field(description="One DuckDB SELECT; tables qualified as <source>.<table>.")
    sources: list[str] = Field(default_factory=list, description="Sources the statement reads.")
    rationale: str = Field(default="", description="One sentence: why this answers the test.")


class ObservationDraft(_Model):
    """The Investigator's model reply after reading query rows."""

    finding: str = Field(description="One sentence with the numbers from the rows.")
    value: float | None = Field(default=None, description="The measured value in the window.")
    baseline: float | None = Field(default=None, description="The same measure in the baseline window.")
    effect: float | None = Field(default=None, description="value/baseline - 1, when both exist.")
    supports: bool | None = Field(
        default=None, description="True if the rows support the hypothesis, False if they refute it."
    )


class StatementDraft(_Model):
    """A statement in a drafted cause, pointing at observation ids."""

    text: str
    kind: Literal["measured", "inferred"]
    observation_ids: list[str] = Field(default_factory=list)


class CauseDraft(_Model):
    """A cause as drafted by the Reporter's model call."""

    hypothesis_id: str
    type: CauseType
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    statements: list[StatementDraft] = Field(default_factory=list)
    observation_ids: list[str] = Field(min_length=1, description="Observations that support the cause.")
    next_checks: list[str] = Field(default_factory=list)


class RuledOutDraft(_Model):
    """A rejected hypothesis as drafted by the Reporter."""

    hypothesis_id: str
    type: CauseType
    why: str
    observation_ids: list[str] = Field(default_factory=list)


class ReportDraft(_Model):
    """The Reporter's model reply. `complete=false` asks the loop for more investigation."""

    complete: bool = Field(description="False if the evidence is not enough to answer yet.")
    determinable: bool
    causes: list[CauseDraft] = Field(default_factory=list, description="Ranked, most likely first.")
    ruled_out: list[RuledOutDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    follow_up: list[Hypothesis] = Field(
        default_factory=list, description="Hypotheses to test next when complete is false."
    )


class CritiqueDraft(_Model):
    """The Critic's model reply. The code turns it into a `Verdict` (architecture §4):
    `contradicted` gives refuted; otherwise a total of 7 or more of 9 gives supported, less gives
    insufficient with the follow-up tests."""

    checks: list[CriticCheck] = Field(description="One entry per disproof check, each check named once.")
    scores: CritiqueScores
    contradicted: bool = Field(description="True when the evidence contradicts the hypothesis.")
    reason: str = Field(description="One or two sentences: why, with the numbers.")
    follow_up_tests: list[str] = Field(
        default_factory=list, max_length=3,
        description="Specific measurements that would decide it (when the evidence is not enough).",
    )
    sample_size: int | None = Field(
        default=None, ge=0, description="Records behind the change in the window, if the evidence shows it."
    )
    observation_ids: list[str] = Field(default_factory=list, description="Ids from the INPUT the verdict relies on.")

    @model_validator(mode="after")
    def _every_check_once(self) -> CritiqueDraft:
        names = [check.name for check in self.checks]
        missing = [name for name in CHECK_NAMES if name not in names]
        if missing or len(names) != len(set(names)):
            raise ValueError(f"checks must name each of {', '.join(CHECK_NAMES)} exactly once")
        return self


ALL_MODELS: tuple[type[BaseModel], ...] = (
    Question,
    Plan,
    Hypothesis,
    Observation,
    Verdict,
    Result,
)


def json_schemas() -> dict[str, dict[str, Any]]:
    """Return the JSON Schema of every top-level model, keyed by model name."""
    return {model.__name__: model.model_json_schema() for model in ALL_MODELS}


def validation_summary(error: ValidationError) -> str:
    """A readable, one-line-per-problem rendering of a pydantic validation error."""
    lines = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "<root>"
        lines.append(f"{where}: {item['msg']}")
    return "; ".join(lines)


def validate_result_file(path: Path) -> Result:
    """Load and validate a result JSON file; raises `ValueError` with a readable message."""
    try:
        return Result.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(f"{path} is not a valid Result: {validation_summary(exc)}") from exc


def main(argv: list[str] | None = None) -> int:
    """`python -m app.schemas [FILE ...]` validates result files (default: the example result)."""
    paths = argv if argv is not None else sys.argv[1:]
    paths = paths or [str(Path(__file__).resolve().parents[1] / "output_examples" / "example-result.json")]
    status = 0
    for name in paths:
        try:
            result = validate_result_file(Path(name))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[FAIL] {exc}")
            status = 1
            continue
        evidence = sum(len(cause.evidence) for cause in result.causes)
        print(
            f"[PASS] {Path(name).name}: valid Result (status={result.status}, "
            f"{len(result.causes)} causes, {evidence} evidence items)"
        )
    return status


if __name__ == "__main__":
    sys.exit(main())

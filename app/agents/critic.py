"""Critic: tries to disprove one hypothesis after the Investigator's round (architecture §2, §4).

    verdict = Critic(settings)(request)   # request: orchestrator.CriticRequest

Plugs into the Markovian orchestrator's critic seam (`CriticHook`). It is its own prompt
(`prompts/critic.md`) and its own model call on the critic lane (`role="critic"`, Meterless fast
by default, `METERLESS_MODEL_CRITIC` to override), through the generator in the request; the
Investigator never makes it.

The model input is the plan, the measured change (with the change check's row), the hypothesis,
the Investigator's observation, the World Model's `critique` payload for the hypothesis (built with
the request's `context_builder` within `budget_chars`), the chunk's investigation state and, on the
second critique, the follow-up tests with their results. The reply (`CritiqueDraft`) names each
disproof check (alternative cause, concentration, sample size, date basis, data artefact) and scores
the explanation 0-3 on three points. The verdict is decided here, not by the model:

- `contradicted` -> refuted, with the reason;
- otherwise a total of 7 or more of 9 -> supported, less -> insufficient with the follow-up tests;
- a reported sample size below `CRITIC_MIN_SAMPLE_SIZE` -> insufficient with `sample_too_small`
  (the orchestrator then ends the run as "cannot be determined").

An invalid reply (a failed call or one that does not validate) is asked for once more; a second
invalid reply gives `insufficient`. The Critic never raises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.agents.base import build_messages
from app.agents.prompts import load_prompt
from app.config import Settings, get_settings
from app.engines.world_model.context import Intent
from app.schemas import (
    CHECK_NAMES,
    SUPPORTED_MIN_SCORE,
    CritiqueDraft,
    Observation,
    Verdict,
    validation_summary,
)

if TYPE_CHECKING:  # the orchestrator imports this module; the request type is only for annotations
    from app.engines.markovian.orchestrator import CriticRequest

AGENT = "Critic"
ROLE = "critic"
MAX_REPLY_ATTEMPTS = 2
"""The first call plus one retry when the reply is invalid."""


def observation_payload(obs: Observation) -> dict[str, Any]:
    """What the Critic sees of one observation (the SQL stays in the World Model)."""
    return {
        "id": obs.id,
        "query_id": obs.query_id,
        "source": obs.source,
        "finding": obs.finding,
        "value": obs.value,
        "baseline": obs.baseline,
        "effect": obs.effect,
        "supports": obs.supports,
    }


def evidence_payload(request: CriticRequest) -> dict[str, Any]:
    """The World Model's `critique` payload for the hypothesis, within `budget_chars`.

    The ContextBuilder names the run that wrote each edge; in the per-run store that is always this
    run, so "run <id>" is replaced (as the orchestrator does) and the prompt does not depend on the
    run id, which keeps the sample-mode cache key stable. For the same reason only the items and the
    number of items cut for the budget are passed on: the payload's `used_chars` counts the run id.
    """
    try:
        payload = request.context_builder.build(
            Intent("critique", hypothesis_id=request.hypothesis_entity_id), request.budget_chars
        )
    except ValueError as exc:
        return {"items": [], "note": f"no World Model evidence: {exc}"}
    marker = f"run {request.run_id}"
    for item in payload.get("items", []):
        item["selection_reason"] = str(item.get("selection_reason", "")).replace(marker, "this run")
    return {"items": payload.get("items", []), "dropped": payload.get("dropped", {}).get("count", 0)}


def critic_input(request: CriticRequest, min_sample_size: int) -> dict[str, Any]:
    """The model input for one critique."""
    plan, hypothesis = request.plan, request.hypothesis
    change = None
    if request.change is not None:
        change = {**observation_payload(request.change), "row": request.change_row}
    payload: dict[str, Any] = {
        "question": plan.question,
        "plan": {
            "metric": plan.metric,
            "segment": plan.segment,
            "window": plan.window.model_dump(),
            "baseline_window": plan.baseline_window.model_dump(),
        },
        "change": change,
        "hypothesis": {
            "id": hypothesis.id,
            "family": hypothesis.family,
            "statement": hypothesis.statement,
            "test": hypothesis.test.model_dump(),
        },
        "observation": observation_payload(request.observation) if request.observation else None,
        "evidence": evidence_payload(request),
        "state": request.chunk_text,
        "checks": list(CHECK_NAMES),
        "min_sample_size": min_sample_size,
        "attempt": request.attempt,
    }
    if request.attempt > 1:
        payload["follow_up"] = {
            "requested": list(request.follow_up_tests),
            "results": [observation_payload(o) for o in request.follow_up],
        }
    return payload


def _known_ids(payload: dict[str, Any], request: CriticRequest) -> dict[str, str | None]:
    """Observation ids the Critic may rely on, each with its query id."""
    known: dict[str, str | None] = {}
    for obs in (request.observation, *request.follow_up):
        if obs is not None:
            known[obs.id] = obs.query_id
    for item in payload["evidence"].get("items", []):
        if item.get("type") == "observation":
            known[item["id"]] = (item.get("summary") or {}).get("query_id")
    return known


def judge(
    draft: CritiqueDraft,
    request: CriticRequest,
    payload: dict[str, Any],
    *,
    min_sample_size: int,
    retry_count: int = 0,
) -> Verdict:
    """Turn the model's critique into a verdict by the fixed rule in the module docstring."""
    hypothesis = request.hypothesis
    total = draft.scores.total
    too_small = draft.sample_size is not None and draft.sample_size < min_sample_size
    if draft.contradicted:
        verdict = "refuted"
    elif too_small:
        verdict = "insufficient"
    else:
        verdict = "supported" if total >= SUPPORTED_MIN_SCORE else "insufficient"
    reason = draft.reason.strip() or f"critique total {total}/9"
    if too_small:
        reason = f"Sample too small: {draft.sample_size} records in the window (minimum {min_sample_size}). {reason}"
    follow_up = [t.strip() for t in draft.follow_up_tests if t.strip()] if verdict == "insufficient" else []
    if verdict == "insufficient" and not follow_up and not too_small:
        follow_up = [f"Repeat the test with more evidence: {hypothesis.test.description}"]

    known = _known_ids(payload, request)
    relied = [oid for oid in dict.fromkeys(draft.observation_ids) if oid in known]
    if not relied:  # the model named none (or none that exist): the evidence it was shown
        relied = list(known)
    query_ids = list(dict.fromkeys(q for q in (known[oid] for oid in relied) if q))
    return Verdict(
        hypothesis_id=hypothesis.id,
        verdict=verdict,
        reason=reason,
        follow_up_tests=follow_up,
        scores=draft.scores,
        total_score=total,
        checks=draft.checks,
        observation_ids=relied,
        query_ids=query_ids,
        sample_size=draft.sample_size,
        sample_too_small=too_small,
        attempt=request.attempt,
        retry_count=retry_count,
    )


class Critic:
    """The real Critic, callable as a `CriticHook`."""

    def __init__(self, settings: Settings | None = None, *, min_sample_size: int | None = None) -> None:
        settings = settings or get_settings()
        self.min_sample_size = min_sample_size if min_sample_size is not None else settings.critic_min_sample_size
        self.last_problem = ""
        """The detail of the last invalid reply (for the trace; not part of the verdict)."""

    def __call__(self, request: CriticRequest) -> Verdict:
        payload = critic_input(request, self.min_sample_size)
        messages = build_messages(load_prompt("critic"), payload)
        # Only the error code goes into the reason: the reason reaches later prompts (the carryover),
        # and the sample-mode cache keys must not depend on a transient error message.
        problem = "no_reply"
        for attempt in range(MAX_REPLY_ATTEMPTS):
            reply = request.generate(messages, schema=CritiqueDraft, role=ROLE, run_id=request.run_id)
            if reply.ok and reply.parsed is not None:
                try:
                    draft = CritiqueDraft.model_validate(reply.parsed)
                except ValidationError as exc:
                    problem = "invalid_reply"
                    self.last_problem = validation_summary(exc)
                    continue
                return judge(draft, request, payload, min_sample_size=self.min_sample_size, retry_count=attempt)
            error = reply.error or {}
            problem = str(error.get("code", "error"))
            self.last_problem = str(error.get("message", ""))
        return Verdict(
            hypothesis_id=request.hypothesis.id,
            verdict="insufficient",
            reason=f"The Critic's reply was invalid twice ({problem}); treated as insufficient.",
            follow_up_tests=[],
            attempt=request.attempt,
            retry_count=MAX_REPLY_ATTEMPTS - 1,
        )

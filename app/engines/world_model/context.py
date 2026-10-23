"""ContextBuilder: the evidence one agent round sees, within a size budget (architecture §5.1).

`ContextBuilder(store).build(intent, budget_chars)` selects items from the World Model by fixed
rules (no model call), ranks them, and cuts from the bottom until the serialised payload fits:

- `critique H`: H, then every observation with a `supports` or `refutes` edge to H or derived from
  a query that `tests` H, strongest effect first (|relative change|, then |robust z|). The strongest
  refuting observation is never cut unless it alone exceeds the budget.
- `investigate H`: H, the queries that test it with their outcomes (observation, alert, supports
  and refutes counts, strongest effect), then the sources those queries used.
- `plan` / `report`: the question, its hypotheses with their supports/refutes counts, then the top
  observations by effect.

The payload is a dict: `intent`, `items` (each with `id`, `type`, a compact `summary` and a
`selection_reason`), `candidates`, `budget_chars`, `used_chars` and `dropped` (`count`, `ids`,
`ids_complete`). `used_chars` is the exact length of `serialise(payload)` (sorted-key compact JSON),
which never exceeds `budget_chars`. The same store and intent always give byte-identical output.

Sample-mode demo (seeds the store with the Sprint 5 ingest of the sample data):

    python -m app.engines.world_model.context --sample --intent critique
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Literal

from app.engines.world_model.store import Entity, WorldStore

IntentKind = Literal["plan", "investigate", "critique", "report"]
INTENT_KINDS: tuple[str, ...] = ("plan", "investigate", "critique", "report")

MAX_CANDIDATES = 100
"""At most this many items are considered per build (the rest are counted in `over_cap`)."""

TOP_OBSERVATIONS = 10
"""Observations listed for `plan` and `report`."""

MAX_SQL_CHARS = 160
"""Query text is shortened to this many characters in an item summary."""


@dataclass(frozen=True)
class Intent:
    """What the caller is about to do. `critique` and `investigate` need a hypothesis id."""

    kind: IntentKind
    hypothesis_id: str | None = None
    question_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in INTENT_KINDS:
            raise ValueError(f"unknown intent kind {self.kind!r}; expected one of {', '.join(INTENT_KINDS)}")
        if self.kind in ("critique", "investigate") and not self.hypothesis_id:
            raise ValueError(f"a {self.kind} intent needs a hypothesis_id")

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form (None fields left out)."""
        return {k: v for k, v in (("kind", self.kind), ("hypothesis_id", self.hypothesis_id),
                                  ("question_id", self.question_id)) if v is not None}


def serialise(payload: dict[str, Any]) -> str:
    """The canonical serialisation the budget is measured on: sorted keys, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _num(value: Any) -> Any:
    """Round a number to 4 significant digits for a compact summary; other values unchanged."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    rounded = float(f"{value:.4g}")
    return int(rounded) if rounded.is_integer() and abs(rounded) < 1e15 else rounded


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1%}"


def strength_key(observation: Entity) -> tuple[bool, float, float, str]:
    """Sort key, strongest effect first: |relative change|, then |robust z|, then id."""
    rel = observation.content.get("rel_change")
    z = observation.content.get("z")
    return (rel is None, -abs(rel or 0.0), -abs(z or 0.0), observation.id)


@dataclass
class _Candidate:
    id: str
    type: str
    summary: dict[str, Any]
    reason: str
    protected: bool = False

    def item(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "summary": self.summary, "selection_reason": self.reason}


class ContextBuilder:
    """Deterministic, budgeted evidence selection over a `WorldStore`."""

    def __init__(self, store: WorldStore) -> None:
        self.store = store

    # --- public ----------------------------------------------------------------------------------

    def build(self, intent: Intent, budget_chars: int) -> dict[str, Any]:
        """Select, rank and cut items for an intent; see the module docstring.

        Raises `ValueError` for an unknown hypothesis/question id or a budget too small for even an
        empty payload.
        """
        if intent.kind == "critique":
            candidates = self._critique(intent.hypothesis_id)
        elif intent.kind == "investigate":
            candidates = self._investigate(intent.hypothesis_id)
        else:
            candidates = self._overview(intent.kind, intent.question_id)
        over_cap = max(0, len(candidates) - MAX_CANDIDATES)
        protected = [c for c in candidates[MAX_CANDIDATES:] if c.protected]
        candidates = candidates[:MAX_CANDIDATES]
        if protected:  # a protected item past the cap replaces the last candidate
            candidates = [*candidates[: MAX_CANDIDATES - 1], protected[0]]
        return self._fit(intent, candidates, budget_chars, over_cap)

    # --- selection -------------------------------------------------------------------------------

    def _require(self, entity_id: str | None, entity_type: str) -> Entity:
        entity = self.store.get(entity_id) if entity_id else None
        if entity is None or entity.type != entity_type:
            raise ValueError(f"no {entity_type} with id {entity_id!r} in the world store")
        return entity

    def _direction_edges(self, observation_id: str, hypothesis_id: str) -> dict[str, Any]:
        """The supports/refutes edges from an observation to a hypothesis, by type."""
        found = {}
        for edge in self.store.edges(observation_id, direction="out"):
            if edge.dst == hypothesis_id and edge.type in ("supports", "refutes"):
                found[edge.type] = edge
        return found

    def _counts(self, hypothesis_id: str) -> dict[str, int]:
        return {
            "supports": len(self.store.edges(hypothesis_id, "supports", direction="in")),
            "refutes": len(self.store.edges(hypothesis_id, "refutes", direction="in")),
            "queries": len(self.store.edges(hypothesis_id, "tests", direction="in")),
        }

    def _hypothesis_summary(self, hypothesis: Entity) -> dict[str, Any]:
        content = hypothesis.content
        summary = {"statement": content.get("statement"), **self._counts(hypothesis.id)}
        for key in ("label", "family", "priority"):
            if content.get(key) is not None:
                summary[key] = content[key]
        return summary

    @staticmethod
    def _observation_summary(observation: Entity) -> dict[str, Any]:
        c = observation.content
        summary = {
            "metric": c.get("metric"), "segment": c.get("segment"), "window": c.get("window"),
            "baseline_window": c.get("baseline_window"), "value": _num(c.get("value")),
            "baseline": _num(c.get("baseline")), "abs_change": _num(c.get("abs_change")),
            "rel_change": _num(c.get("rel_change")), "z": _num(c.get("z")), "alert": c.get("alert"),
            "source": c.get("source"), "query_id": c.get("query_id"),
        }
        return {k: v for k, v in summary.items() if v is not None}

    @staticmethod
    def _effect_text(observation: Entity) -> str:
        c = observation.content
        text = f"rel {_pct(c.get('rel_change'))}"
        if c.get("z") is not None:
            text += f", z {c['z']:+.2f}"
        return text + (", alert" if c.get("alert") else "")

    def _critique(self, hypothesis_id: str | None) -> list[_Candidate]:
        hypothesis = self._require(hypothesis_id, "hypothesis")
        name = hypothesis.content.get("label") or hypothesis.id
        candidates = [_Candidate(hypothesis.id, "hypothesis", self._hypothesis_summary(hypothesis),
                                 f"the hypothesis under critique ({name})")]
        observations = sorted(self.store.observations_for(hypothesis.id), key=strength_key)
        refuting_kept = False
        for rank, observation in enumerate(observations, start=1):
            edges = self._direction_edges(observation.id, hypothesis.id)
            summary = self._observation_summary(observation)
            if edges:
                summary["direction"] = "+".join(sorted(edges))
                how = " and ".join(f"{kind} {name} ({edge.agent}, run {edge.run_id})"
                                   for kind, edge in sorted(edges.items()))
            else:
                how = f"from query {summary.get('query_id', '?')} testing {name}; no direction yet"
            reason = f"{how}; {self._effect_text(observation)}; effect rank {rank}/{len(observations)}"
            protected = "refutes" in edges and not refuting_kept
            if protected:
                refuting_kept = True
                reason += "; strongest refuting item, always kept"
            candidates.append(_Candidate(observation.id, "observation", summary, reason, protected))
        return candidates

    def _investigate(self, hypothesis_id: str | None) -> list[_Candidate]:
        hypothesis = self._require(hypothesis_id, "hypothesis")
        name = hypothesis.content.get("label") or hypothesis.id
        candidates = [_Candidate(hypothesis.id, "hypothesis", self._hypothesis_summary(hypothesis),
                                 f"the hypothesis under investigation ({name})")]
        queries = []
        for edge in self.store.edges(hypothesis.id, "tests", direction="in"):
            query = self.store.get(edge.src)
            observations = sorted((self.store.get(e.src) for e in self.store.edges(query.id, "derived_from",
                                                                                   direction="in")),
                                  key=strength_key)
            queries.append((strength_key(observations[0]) if observations else (True, 0.0, 0.0, query.id),
                            query, observations, edge))
        queries.sort(key=lambda item: (item[0], item[1].id))
        sources: dict[str, Entity] = {}
        for _key, query, observations, edge in queries:
            directions = [self._direction_edges(o.id, hypothesis.id) for o in observations]
            sql = query.content.get("sql", "")
            summary = {
                "query_id": query.content.get("query_id"), "source": query.content.get("source"),
                "sql": sql if len(sql) <= MAX_SQL_CHARS else sql[: MAX_SQL_CHARS - 1] + "…",
                "observations": len(observations), "alerts": sum(bool(o.content.get("alert")) for o in observations),
                "supports": sum("supports" in d for d in directions),
                "refutes": sum("refutes" in d for d in directions),
            }
            if observations:
                top = observations[0].content
                summary["strongest"] = {"id": observations[0].id, "metric": top.get("metric"),
                                        "segment": top.get("segment"), "window": top.get("window"),
                                        "rel_change": _num(top.get("rel_change"))}
            candidates.append(_Candidate(
                query.id, "query", summary,
                f"query already run to test {name} (edge by {edge.agent}, run {edge.run_id}) with its outcome; "
                "avoid repeating it",
            ))
            for source in self.store.neighbours(query.id, "from_source"):
                sources.setdefault(source.id, source)
        for source in sorted(sources.values(), key=lambda s: (s.content.get("name", ""), s.id)):
            used_by = [q.content.get("query_id") for _k, q, _o, _e in queries
                       if any(s.id == source.id for s in self.store.neighbours(q.id, "from_source"))]
            candidates.append(_Candidate(source.id, "source", {"name": source.content.get("name"),
                                                               "queries": len(used_by)},
                                         f"source already used by {len(used_by)} quer"
                                         f"{'y' if len(used_by) == 1 else 'ies'} testing {name}"))
        return candidates

    def _overview(self, kind: str, question_id: str | None) -> list[_Candidate]:
        purpose = "plan the next step" if kind == "plan" else "write the report"
        if question_id:
            questions = [self._require(question_id, "question")]
            hypotheses = [h for h in self.store.entities("hypothesis") if h.content.get("question_id") == question_id]
        else:
            questions = self.store.entities("question")
            hypotheses = self.store.entities("hypothesis")
        candidates = [_Candidate(q.id, "question", {"text": q.content.get("text")},
                                 f"the question being answered; needed to {purpose}") for q in questions]
        hypotheses.sort(key=lambda h: (h.content.get("priority") or 10**6, h.content.get("label") or "", h.id))
        observations: dict[str, Entity] = {}
        for hypothesis in hypotheses:
            summary = self._hypothesis_summary(hypothesis)
            candidates.append(_Candidate(
                hypothesis.id, "hypothesis", summary,
                f"current hypothesis with {summary['supports']} supporting and {summary['refutes']} refuting "
                f"observations; needed to {purpose}",
            ))
            for observation in self.store.observations_for(hypothesis.id):
                observations[observation.id] = observation
        if not question_id:
            observations.update((o.id, o) for o in self.store.entities("observation"))
        ranked = sorted(observations.values(), key=strength_key)
        for rank, observation in enumerate(ranked[:TOP_OBSERVATIONS], start=1):
            candidates.append(_Candidate(
                observation.id, "observation", self._observation_summary(observation),
                f"top observation by effect, rank {rank}/{len(ranked)}: {self._effect_text(observation)}",
            ))
        return candidates

    # --- budget ----------------------------------------------------------------------------------

    @staticmethod
    def _payload(intent: Intent, kept: list[_Candidate], dropped: list[str], ids_complete: bool, budget: int,
                 total: int, over_cap: int) -> tuple[dict[str, Any], str]:
        payload: dict[str, Any] = {
            "intent": intent.to_dict(),
            "items": [c.item() for c in kept],
            "candidates": total,
            "over_cap": over_cap,
            "budget_chars": budget,
            "used_chars": 0,
            "dropped": {"count": total - len(kept), "ids": dropped,
                        "ids_complete": ids_complete},
        }
        # used_chars is part of the text it measures: iterate to the fixed point (two or three passes).
        for _ in range(5):
            text = serialise(payload)
            if len(text) == payload["used_chars"]:
                return payload, text
            payload["used_chars"] = len(text)
        raise RuntimeError("used_chars did not settle")  # cannot happen: the length changes by digits only

    def _fit(self, intent: Intent, candidates: list[_Candidate], budget: int, over_cap: int) -> dict[str, Any]:
        """Keep the longest priority prefix (plus the protected item) whose payload fits the budget.

        Items come before the dropped-id list: when the complete list does not fit next to the kept
        items, the list is shortened (highest priority ids first, ``ids_complete`` false, the count
        stays exact) before another item is dropped. The protected refuting item goes only when a
        payload holding just it and an empty id list exceeds the budget.
        """
        total = len(candidates)
        protected = next((i for i, c in enumerate(candidates) if c.protected), None)
        # One pass per prefix length: bounded by MAX_CANDIDATES.
        for keep in range(total, -1, -1):
            indices = set(range(keep))
            if protected is not None:
                indices.add(protected)
            kept = [c for i, c in enumerate(candidates) if i in indices]
            dropped = [c.id for i, c in enumerate(candidates) if i not in indices]
            payload = self._listing(intent, kept, dropped, budget, total, over_cap)
            if payload is not None:
                return payload
        # The protected item alone exceeds the budget, so it goes too.
        payload = self._listing(intent, [], [c.id for c in candidates], budget, total, over_cap)
        if payload is not None:
            return payload
        minimum = len(self._payload(intent, [], [], False, budget, total, over_cap)[1])
        raise ValueError(f"budget_chars={budget} is below the minimum payload of {minimum} chars")

    def _listing(self, intent: Intent, kept: list[_Candidate], dropped: list[str], budget: int, total: int,
                 over_cap: int) -> dict[str, Any] | None:
        """The payload for `kept` with as many dropped ids as fit (all if possible), or None if none fits."""
        payload, text = self._payload(intent, kept, dropped, True, budget, total, over_cap)
        if len(text) <= budget:
            return payload
        payload, text = self._payload(intent, kept, [], not dropped, budget, total, over_cap)
        if len(text) > budget:
            return None
        # Binary search on the listed prefix length: the text grows with every id (bounded by log2 of the list).
        low, high = 0, len(dropped) - 1  # `low` ids fit; `len(dropped)` ids do not
        while low < high:
            middle = (low + high + 1) // 2
            candidate, text = self._payload(intent, kept, dropped[:middle], False, budget, total, over_cap)
            if len(text) <= budget:
                low, payload = middle, candidate
            else:
                high = middle - 1
        return payload


# --- sample-mode demo --------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """`python -m app.engines.world_model.context --sample --intent critique [--budget N] [--db PATH]`."""
    from app.engines.world_model.ingest import SAMPLE_RUN_ID, seed_sample

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sample", action="store_true", help="seed the store from the sample data first")
    parser.add_argument("--intent", choices=INTENT_KINDS, default="critique")
    parser.add_argument("--budget", type=int, default=4000, help="budget_chars (default 4000)")
    parser.add_argument("--db", default=None, help="SQLite file (default WORLD_DB_PATH, logs/world.db)")
    parser.add_argument("--run-id", default=SAMPLE_RUN_ID)
    args = parser.parse_args(argv)
    if not args.sample:
        print("only sample mode exists so far: pass --sample", file=sys.stderr)
        return 2
    with WorldStore(args.db) as store:
        seeded = seed_sample(store, run_id=args.run_id)
        needs_hypothesis = args.intent in ("critique", "investigate")
        intent = Intent(kind=args.intent, hypothesis_id=seeded["hypothesis_id"] if needs_hypothesis else None,
                        question_id=None if needs_hypothesis else seeded["question_id"])
        payload = ContextBuilder(store).build(intent, args.budget)
    print(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False))
    kinds: dict[str, int] = {}
    for item in payload["items"]:
        direction = item["summary"].get("direction")
        key = f"{item['type']}:{direction}" if direction else item["type"]
        kinds[key] = kinds.get(key, 0) + 1
    print(f"intent={args.intent} items={len(payload['items'])} {json.dumps(kinds, sort_keys=True)} "
          f"used_chars={payload['used_chars']} budget_chars={payload['budget_chars']} "
          f"dropped={payload['dropped']['count']} (used_chars counts the compact serialisation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

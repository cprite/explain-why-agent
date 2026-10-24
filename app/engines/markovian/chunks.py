"""Chunk manager: builds each chunk's input within budget and caps the chain (architecture §5.2).

    manager = ChunkManager(config)
    chunk = manager.start_chunk(goal, carryover=carryover, context=payload, label="H3")
    ...                                # the orchestrator (task 12) runs the round on chunk.text
    manager.finish_chunk(chunk.index, sent_chars=len(prompt), output_chars=len(reply))

The input for chunk N is the goal, the carryover state from chunk N-1 and the evidence the World
Model ContextBuilder selected, packed in that order and never longer than `chunk_budget_chars`:

- the goal is clipped to a quarter of the budget on chunk 1 and to `GOAL_CONTINUATION_CHARS` after
  (the guide's "truncated goal on continuation steps");
- the carryover is already within `carryover_budget_chars` (at most half the chunk budget);
- evidence items are added in the order the ContextBuilder ranked them; an item that does not fit in
  what is left is dropped (and recorded) and smaller items after it are still tried.

Starting chunk `max_chunks + 1` raises `ChunkCapError`. Each chunk's record keeps the projected size
(the input built here), the actual sizes reported back by the orchestrator, and the size the same
chunk would have had with a growing conversation, for the token report.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from app.engines.markovian.carryover import Carryover
from app.engines.markovian.config import MarkovianConfig

GOAL_CONTINUATION_CHARS = 300
"""Goal length on chunks after the first."""
MAX_CONTEXT_ITEMS = 200
"""Cap on the evidence items considered for one chunk."""


class ContextItem(Protocol):
    """One evidence item selected by the ContextBuilder (World Model, build-plan task 9)."""

    @property
    def id(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def summary(self) -> str: ...
    @property
    def selection_reason(self) -> str: ...


class ContextPayload(Protocol):
    """The ContextBuilder's payload: the items it selected and the size budget it worked to.

    A stand-in until the World Model sprint merges; the orchestrator sprint wires the real builder.
    """

    @property
    def items(self) -> Sequence[ContextItem]: ...
    @property
    def budget_chars(self) -> int: ...
    @property
    def used_chars(self) -> int: ...


class ChunkCapError(RuntimeError):
    """Raised when a chunk beyond `max_chunks` is started."""

    def __init__(self, index: int, max_chunks: int) -> None:
        super().__init__(f"cannot start chunk {index}: the run is capped at MARKOVIAN_MAX_CHUNKS={max_chunks}")
        self.index = index
        self.max_chunks = max_chunks


@dataclass
class ChunkInput:
    """The input built for one chunk."""

    index: int
    text: str
    goal_chars: int
    carryover_chars: int
    context_chars: int
    items_included: list[str]
    items_dropped: list[str]
    budget_chars: int

    @property
    def chars(self) -> int:
        """Size of the built input."""
        return len(self.text)


@dataclass
class ChunkRecord:
    """Sizes of one chunk, for the projected-versus-actual token report."""

    index: int
    label: str
    budget_chars: int
    projected_chars: int
    standard_chars: int
    carryover_step: str | None
    carryover_chars: int
    items_included: list[str] = field(default_factory=list)
    items_dropped: list[str] = field(default_factory=list)
    actual_sent_chars: int | None = None
    output_chars: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form with the guide's `ceil(chars / 4)` token estimates."""
        data = asdict(self)
        data["projected_tokens"] = estimate_tokens(self.projected_chars)
        data["standard_tokens"] = estimate_tokens(self.standard_chars)
        data["actual_sent_tokens"] = (
            estimate_tokens(self.actual_sent_chars) if self.actual_sent_chars is not None else None
        )
        data["output_tokens"] = estimate_tokens(self.output_chars) if self.output_chars is not None else None
        return data


def estimate_tokens(chars: int) -> int:
    """The guide's heuristic: `ceil(chars / 4)`. Not tokenizer-precise."""
    return math.ceil(max(0, chars) / 4)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def render_item(item: ContextItem) -> str:
    """One evidence line: id, type, summary and why it was selected."""
    line = f"- [{item.id}] ({item.type}) {' '.join(str(item.summary).split())}"
    reason = " ".join(str(item.selection_reason).split())
    return f"{line} | selected because: {reason}" if reason else line


class ChunkManager:
    """Counts chunks, builds each chunk's input within budget and records sizes."""

    def __init__(self, config: MarkovianConfig) -> None:
        self.config = config
        self.records: list[ChunkRecord] = []

    @property
    def chunks_started(self) -> int:
        """How many chunks have been started."""
        return len(self.records)

    @property
    def rounds_left(self) -> int:
        """Chunks that may still be started."""
        return max(0, self.config.max_chunks - self.chunks_started)

    def can_start(self) -> bool:
        """True while another chunk may be started."""
        return self.chunks_started < self.config.max_chunks

    def start_chunk(
        self,
        goal: str,
        *,
        carryover: Carryover | None = None,
        context: ContextPayload | None = None,
        label: str = "",
    ) -> ChunkInput:
        """Build the input for the next chunk; raise `ChunkCapError` past `max_chunks`."""
        index = self.chunks_started + 1
        if index > self.config.max_chunks:
            raise ChunkCapError(index, self.config.max_chunks)
        chunk = self.build_input(index, goal, carryover=carryover, context=context)
        all_items = list(context.items)[:MAX_CONTEXT_ITEMS] if context is not None else []
        history = sum(r.output_chars or 0 for r in self.records)
        standard = (
            len(goal)
            + (len("\n".join(render_item(i) for i in all_items)) if all_items else 0)
            + history
        )
        self.records.append(
            ChunkRecord(
                index=index,
                label=label,
                budget_chars=self.config.chunk_budget_chars,
                projected_chars=chunk.chars,
                standard_chars=standard,
                carryover_step=carryover.carryover_step if carryover else None,
                carryover_chars=chunk.carryover_chars,
                items_included=chunk.items_included,
                items_dropped=chunk.items_dropped,
            )
        )
        return chunk

    def build_input(
        self, index: int, goal: str, *, carryover: Carryover | None, context: ContextPayload | None
    ) -> ChunkInput:
        """Pack goal, carryover and evidence into at most `chunk_budget_chars` characters."""
        budget = self.config.chunk_budget_chars
        goal_limit = budget // 4 if index == 1 else min(GOAL_CONTINUATION_CHARS, budget // 4)
        goal_text = _clip(goal, goal_limit)
        parts = [f"Goal: {goal_text}"]
        carryover_text = ""
        if carryover is not None:
            carryover_text = carryover.render()
            if len(carryover_text) > self.config.carryover_budget_chars:
                carryover_text = _clip(carryover_text, self.config.carryover_budget_chars)
            parts.append(f"State so far:\n{carryover_text}")
        header = "\n\n".join(parts) + "\n\nEvidence:"
        included: list[str] = []
        dropped: list[str] = []
        lines: list[str] = []
        used = len(header)
        items = list(context.items)[:MAX_CONTEXT_ITEMS] if context is not None else []
        for item in items:
            line = render_item(item)
            if used + 1 + len(line) <= budget:
                lines.append(line)
                used += 1 + len(line)
                included.append(str(item.id))
            else:
                dropped.append(str(item.id))
        if not lines:
            none = " none selected"
            text = header + (none if len(header) + len(none) <= budget else "")
        else:
            text = header + "\n" + "\n".join(lines)
        # Unreachable with a valid config (goal <= 1/4, carryover <= 1/2 of the budget); kept as the guarantee.
        text = text[:budget]
        return ChunkInput(
            index=index,
            text=text,
            goal_chars=len(goal_text),
            carryover_chars=len(carryover_text),
            context_chars=sum(len(line) + 1 for line in lines),
            items_included=included,
            items_dropped=dropped,
            budget_chars=budget,
        )

    def finish_chunk(self, index: int, *, sent_chars: int, output_chars: int) -> ChunkRecord:
        """Record what the orchestrator actually sent (agent prompts included) and got back."""
        if not 1 <= index <= len(self.records):
            raise ValueError(f"chunk {index} was not started")
        record = self.records[index - 1]
        if record.actual_sent_chars is not None:
            raise ValueError(f"chunk {index} is already finished")
        record.actual_sent_chars = max(0, sent_chars)
        record.output_chars = max(0, output_chars)
        return record

    def report(self) -> list[dict[str, Any]]:
        """Per-chunk sizes and token estimates, in chunk order."""
        return [record.to_dict() for record in self.records]

"""Shared pieces for the agents: the run context, the budget and the prompt message format.

Agents receive everything they use through `AgentContext` (the injected generator, the data layer,
the trace writer and the budget), so tests can swap any of them. Model input is the agent's system
prompt plus one user message `INPUT:` followed by canonical JSON; the canonical form keeps the
sample-mode cache key stable across runs.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from app.data.layer import DataLayer
from app.llm.generator import GenerateFn, Message
from app.trace import TraceWriter


@dataclass
class Budget:
    """Caps for one run: agent rounds and tool (query) calls, from the environment."""

    max_rounds: int
    max_tool_calls: int
    rounds_used: int = 0
    tool_calls_used: int = 0

    @property
    def rounds_left(self) -> int:
        """Agent rounds still available."""
        return self.max_rounds - self.rounds_used

    def take_round(self) -> bool:
        """Consume one agent round; False when the cap is reached."""
        if self.rounds_used >= self.max_rounds:
            return False
        self.rounds_used += 1
        return True

    def take_tool_call(self) -> bool:
        """Consume one query; False when the cap is reached."""
        if self.tool_calls_used >= self.max_tool_calls:
            return False
        self.tool_calls_used += 1
        return True


@dataclass
class AgentContext:
    """What every agent needs for one run."""

    run_id: str
    generate: GenerateFn
    data: DataLayer
    trace: TraceWriter
    budget: Budget
    schema_cache: list[dict[str, Any]] = field(default_factory=list)

    def source_schemas(self) -> list[dict[str, Any]]:
        """Compact description of every source (tables, columns with types, row counts)."""
        if not self.schema_cache:
            for source in self.data.list_sources():
                info = self.data.describe(source)
                self.schema_cache.append(
                    {
                        "source": source,
                        "tables": [
                            {
                                "table": f"{source}.{table.name}",
                                "rows": table.row_count,
                                "columns": [f"{c.name} {c.type}" for c in table.columns],
                            }
                            for table in info.tables
                        ],
                    }
                )
        return self.schema_cache


def stable(value: Any) -> Any:
    """Round floats to 6 significant digits, recursively, so prompts do not change with float noise."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value) or value == 0:
            return value
        return float(f"{value:.6g}")
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [stable(v) for v in value]
    return value


def build_messages(system_prompt: str, payload: dict[str, Any]) -> list[Message]:
    """System prompt plus one `INPUT:` user message with canonical JSON."""
    body = json.dumps(stable(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"INPUT:\n{body}"},
    ]


def parse_input(messages: list[Message]) -> dict[str, Any]:
    """Inverse of `build_messages` for the last `INPUT:` user message (used by the scripted stub)."""
    for message in reversed(messages):
        content = str(message.get("content", ""))
        if message.get("role") == "user" and content.startswith("INPUT:"):
            return json.loads(content[len("INPUT:") :])
    return {}

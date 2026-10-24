"""Run trace writer: `logs/trace-<run_id>.jsonl`, one JSON line per agent action (architecture §8),
and the run's final result next to it, `logs/result-<run_id>.json` (served by `GET /runs/{id}`).

Each line carries a timestamp, the acting agent, the action, the target agent, short input and
output summaries, the status and the retry count; callers may add extra fields (the model generator
adds provider, models, duration and tokens). Secrets are never passed in, so none are written.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUMMARY_LIMIT = 400


def summarise(value: Any, limit: int = SUMMARY_LIMIT) -> str:
    """Compact one-line rendering of any value, cut to `limit` characters."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TraceWriter:
    """Append-only JSONL trace for one run."""

    def __init__(self, log_dir: Path | str, run_id: str) -> None:
        self.run_id = run_id
        self.path = Path(log_dir) / f"trace-{run_id}.jsonl"
        self.result_path = Path(log_dir) / f"result-{run_id}.json"
        self._lock = threading.Lock()

    def write(
        self,
        *,
        agent: str,
        action: str,
        target: str | None = None,
        input_summary: Any = None,
        output_summary: Any = None,
        status: str = "ok",
        retry_count: int = 0,
        **extra: Any,
    ) -> dict[str, Any]:
        """Append one action and return the record written."""
        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "agent": agent,
            "action": action,
            "target_agent": target,
            "input_summary": None if input_summary is None else summarise(input_summary),
            "output_summary": None if output_summary is None else summarise(output_summary),
            "status": status,
            "retry_count": retry_count,
        }
        record.update(extra)
        line = json.dumps(record, default=str, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return record

    def write_result(self, payload: dict[str, Any]) -> Path:
        """Write the run's final result JSON; replaces the file whole, so readers never see half of it."""
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with self._lock:
            self.result_path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.result_path.with_name(self.result_path.name + ".partial")
            partial.write_text(text, encoding="utf-8")
            partial.replace(self.result_path)
        return self.result_path

    def read(self) -> list[dict[str, Any]]:
        """Read the trace back."""
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

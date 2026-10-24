"""The one way to run an investigation, shared by `run.py` and the HTTP API (architecture §7).

`execute_run` wires the configured data layer (`make_data_layer`: Zetaris or local) and the model
generator around `run_investigation`; the loop writes `logs/trace-<run_id>.jsonl` and
`logs/result-<run_id>.json`. Setup failures (the data layer cannot open, say) raise; everything
after that ends in a structured `Result`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from app.config import Settings
from app.schemas import Result

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUN_ID_RULE = "run id must be 1-64 letters, digits, '.', '_' or '-', start with a letter or digit and not contain '..'"


def valid_run_id(run_id: str) -> bool:
    """True if `run_id` is safe to use in a file name under the log directory."""
    return bool(RUN_ID_RE.match(run_id)) and ".." not in run_id


def new_run_id() -> str:
    """A fresh run id: UTC timestamp plus six random hex digits."""
    return f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def execute_run(question: str, *, run_id: str, settings: Settings) -> Result:
    """Run one investigation on the configured data layer with the configured model generator."""
    from app.data.factory import make_data_layer
    from app.llm.generator import Generator
    from app.loop import run_investigation

    with make_data_layer(run_id, settings=settings) as data:
        return run_investigation(question, run_id=run_id, generate=Generator(settings), data=data, settings=settings)

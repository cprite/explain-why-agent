"""The one way to run an investigation, shared by `run.py` and the HTTP API (architecture §7).

`execute_run` wires the configured data layer (`make_data_layer`: Zetaris or local) and the model
generator around the selected loop: the Markovian orchestrator
(`app/engines/markovian/orchestrator.py`, default) or the Sprint 2 simple loop (`app/loop.py`,
`LOOP=simple`). Both write `logs/trace-<run_id>.jsonl` and `logs/result-<run_id>.json`. Setup
failures (the data layer cannot open, a bad `LOOP`) raise; everything after that ends in a
structured `Result`.
"""

from __future__ import annotations

import re
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.config import Settings
from app.schemas import Result

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUN_ID_RULE = "run id must be 1-64 letters, digits, '.', '_' or '-', start with a letter or digit and not contain '..'"
LOOPS = ("markovian", "simple")


def valid_run_id(run_id: str) -> bool:
    """True if `run_id` is safe to use in a file name under the log directory."""
    return bool(RUN_ID_RE.match(run_id)) and ".." not in run_id


def new_run_id() -> str:
    """A fresh run id: UTC timestamp plus six random hex digits."""
    return f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def select_loop(settings: Settings, loop: str | None = None) -> str:
    """The loop to run: `loop` if given, else `LOOP`; raises `ValueError` for an unknown name."""
    name = (loop or settings.loop).strip().lower()
    if name not in LOOPS:
        raise ValueError(f"LOOP must be one of {', '.join(LOOPS)}, got {loop or settings.loop!r}")
    return name


def _close_quietly(close: Callable[[], None]) -> None:
    """Close the data layer; a failure to close is reported on stderr and never replaces the result."""
    try:
        close()
    except Exception as exc:  # noqa: BLE001 - the run's result is already built
        print(f"warning: closing the data layer failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def execute_run(question: str, *, run_id: str, settings: Settings, loop: str | None = None) -> Result:
    """Run one investigation on the configured data layer with the configured model generator."""
    name = select_loop(settings, loop)
    from app.data.factory import make_data_layer
    from app.llm.generator import Generator

    data = make_data_layer(run_id, settings=settings)
    try:
        if name == "simple":
            from app.loop import run_investigation as run
        else:
            from app.engines.markovian.orchestrator import run_markovian as run
        return run(question, run_id=run_id, generate=Generator(settings), data=data, settings=settings)
    finally:
        _close_quietly(data.close)

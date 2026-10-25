"""The one way to run an investigation, shared by `run.py` and the HTTP API (architecture §7).

`execute_run` wires the configured data layer (`make_data_layer`: Zetaris or local) and the model
generator around the selected loop: the Markovian orchestrator
(`app/engines/markovian/orchestrator.py`, default) or the Sprint 2 simple loop (`app/loop.py`,
`LOOP=simple`). Both write `logs/trace-<run_id>.jsonl` and `logs/result-<run_id>.json`. Setup
failures (the data layer cannot open, a bad `LOOP`) raise; everything after that ends in a
structured `Result`. When the Zetaris adapter fell back to local data for any call, the result says
so in `limitations`, naming the adapter that answered (architecture §4), and the stored result
file is rewritten with that note.
"""

from __future__ import annotations

import contextlib
import re
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.config import Settings, resolve_path
from app.schemas import Result
from app.trace import TraceWriter

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


def _mark_data_fallback(result: Result, fallbacks: list[tuple[str, str]], adapter: str, settings: Settings) -> Result:
    """Add the data-fallback note to the result and to its stored file."""
    calls = ", ".join(call for call, _ in fallbacks)
    note = (
        f"Data adapter: Zetaris was unavailable, so {len(fallbacks)} data call(s) ({calls}) were answered by "
        f"the {adapter} adapter; first reason: {fallbacks[0][1]}"
    )
    marked = result.model_copy(update={"limitations": [*result.limitations, note]})
    with contextlib.suppress(OSError):  # as in the loops: the answer still reaches the caller
        TraceWriter(resolve_path(settings.log_dir), result.run_id).write_result(marked.model_dump(mode="json"))
    return marked


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
        result = run(question, run_id=run_id, generate=Generator(settings), data=data, settings=settings)
        fallbacks = list(getattr(data, "fallbacks", None) or [])
        if fallbacks and isinstance(result, Result):
            from app.data.zetaris import FALLBACK_ADAPTER

            result = _mark_data_fallback(result, fallbacks, FALLBACK_ADAPTER, settings)
        return result
    finally:
        _close_quietly(data.close)

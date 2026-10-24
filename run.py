"""Command line: one question in, result JSON out (architecture §7).

    python run.py "<question>" [--sample] [--run-id ID] [--save] [--loop markovian|simple]

The Markovian orchestrator (`app/engines/markovian/orchestrator.py`) runs the investigation by
default; `--loop simple` (or `LOOP=simple`) runs the Sprint 2 loop in `app/loop.py` instead. The flag
wins over the variable. Prints the result JSON on stdout. Exit code 0 when the result's status is success, 1 when the run
ended in a structured error, 2 on bad arguments. `--save` also writes
`output_examples/<run_id>.json`; nothing is written there otherwise. Traces go to
`logs/trace-<run_id>.jsonl` and queries to `logs/queries-<run_id>.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import REPO_ROOT, get_settings

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LOOPS = ("markovian", "simple")


def _error_payload(question: str, run_id: str, code: str, message: str, sample_mode: bool) -> dict:
    return {
        "run_id": run_id,
        "status": "error",
        "question": question,
        "determinable": False,
        "causes": [],
        "sample_mode": sample_mode,
        "error": {"code": code, "message": message},
    }


def main(argv: list[str] | None = None) -> int:
    """Run one investigation and print its result; return the exit code."""
    parser = argparse.ArgumentParser(description="Explain why a business metric changed.")
    parser.add_argument("question", help="Question to investigate")
    parser.add_argument("--sample", action="store_true", help="Force sample mode (local data, cached model replies)")
    parser.add_argument("--run-id", help="Run id used for the trace and log file names")
    parser.add_argument("--save", action="store_true", help="Also write output_examples/<run_id>.json")
    parser.add_argument("--loop", choices=LOOPS, help="Investigation loop (default: LOOP, else markovian)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.sample:
        settings = settings.model_copy(update={"sample_mode": True})
    run_id = args.run_id or f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    if not RUN_ID_RE.match(run_id):
        payload = _error_payload(args.question, run_id, "bad_run_id",
                                 "run id must be 1-64 letters, digits, '.', '_' or '-'", settings.sample_mode)
        print(json.dumps(payload, indent=2))
        return 2
    loop = args.loop or settings.loop.strip().lower()
    if loop not in LOOPS:
        payload = _error_payload(args.question, run_id, "bad_loop",
                                 f"LOOP must be one of {', '.join(LOOPS)}, got {settings.loop!r}", settings.sample_mode)
        print(json.dumps(payload, indent=2))
        return 2

    try:
        from app.data.local import LocalDataLayer
        from app.llm.generator import Generator

        with LocalDataLayer(run_id=run_id, settings=settings) as data:
            if loop == "simple":
                from app.loop import run_investigation

                result = run_investigation(
                    args.question, run_id=run_id, generate=Generator(settings), data=data, settings=settings
                )
            else:
                from app.engines.markovian.orchestrator import run_markovian

                result = run_markovian(
                    args.question, run_id=run_id, generate=Generator(settings), data=data, settings=settings
                )
        payload = result.model_dump(mode="json")
        if payload.get("stop_reason") is None:  # the simple loop's output keeps its Sprint 2 shape
            payload.pop("stop_reason", None)
    except Exception as exc:  # noqa: BLE001 - the CLI always answers with JSON
        payload = _error_payload(args.question, run_id, "internal", f"{type(exc).__name__}: {exc}", settings.sample_mode)

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.save:
        out = REPO_ROOT / "output_examples" / f"{run_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"saved {Path(out).relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0 if payload.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

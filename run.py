"""Command line: one question in, result JSON out (architecture §7).

    python run.py "<question>" [--sample] [--run-id ID] [--save]

Prints the result JSON on stdout. Exit code 0 when the result's status is success, 1 when the run
ended in a structured error, 2 on bad arguments. `--save` also writes
`output_examples/<run_id>.json`; nothing is written there otherwise. Traces go to
`logs/trace-<run_id>.jsonl`, the result to `logs/result-<run_id>.json` and queries to
`logs/queries-<run_id>.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import REPO_ROOT, get_settings
from app.runner import RUN_ID_RE, execute_run, new_run_id


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
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.sample:
        settings = settings.model_copy(update={"sample_mode": True})
    run_id = args.run_id or new_run_id()
    if not RUN_ID_RE.match(run_id):
        payload = _error_payload(args.question, run_id, "bad_run_id",
                                 "run id must be 1-64 letters, digits, '.', '_' or '-'", settings.sample_mode)
        print(json.dumps(payload, indent=2))
        return 2

    try:
        payload = execute_run(args.question, run_id=run_id, settings=settings).model_dump(mode="json")
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

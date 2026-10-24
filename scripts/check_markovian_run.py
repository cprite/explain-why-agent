"""Plan check for the Markovian orchestrator (build-plan task 12): verify a run.py result and its trace.

    python run.py "<question>" --sample --run-id ci-plan-check-i > result.json
    python scripts/check_markovian_run.py result.json [--max-seconds 600]

Prints the elapsed seconds, chunks used / max_chunks, the stop_reason and the top-ranked cause, then
one line per chunk from the trace (hypothesis, queries, carryover step, projected vs actual chars).
Fails when the result is not a schema-valid success, the run took longer than `--max-seconds`, more
chunks ran than `max_chunks`, a chunk input exceeded `chunk_budget_chars`, or the trace does not
have exactly one chunk line per chunk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.schemas import Result


def main(argv: list[str] | None = None) -> int:
    """Verify one orchestrated result file; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result")
    parser.add_argument("--max-seconds", type=float, default=600.0)
    args = parser.parse_args(argv)

    result = Result.model_validate_json(Path(args.result).read_text(encoding="utf-8"))
    trace_path = REPO_ROOT / result.log_file
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines = [line for line in lines if line.get("run_id") == result.run_id]
    chunks = [line for line in lines if line.get("agent") == "Orchestrator" and line.get("action") == "chunk"]
    finish = next((line for line in reversed(lines) if line.get("agent") == "Orchestrator"
                   and line.get("action") == "finish"), {})
    max_chunks = finish.get("max_chunks")
    used = finish.get("chunks_used")
    top = result.causes[0] if result.causes else None

    print(f"question: {result.question}")
    print(f"elapsed_seconds: {result.execution_time_seconds}")
    print(f"chunks: {used}/{max_chunks}")
    print(f"stop_reason: {result.stop_reason}")
    print(f"status: {result.status}; determinable: {result.determinable}; sample_mode: {result.sample_mode}")
    print(f"top_cause: {f'{top.type} (confidence {top.confidence}): {top.summary}' if top else 'none'}")
    print(f"token_report: {result.token_report.model_dump()}")
    for chunk in chunks:
        print(
            f"  chunk {chunk['chunk']}/{chunk['max_chunks']} {chunk['kind']:<5} hypothesis={chunk['hypothesis_id']} "
            f"queries={chunk['queries']} carryover_step={chunk['carryover_step']} "
            f"projected/budget={chunk['projected_chars']}/{chunk['chunk_budget_chars']} "
            f"actual_sent={chunk['actual_chars']}"
        )

    problems = []
    if result.status != "success":
        problems.append(f"status is {result.status}: {result.error}")
    if result.stop_reason in (None, "error", "timeout"):
        problems.append(f"stop_reason is {result.stop_reason}")
    if result.execution_time_seconds > args.max_seconds:
        problems.append(f"took {result.execution_time_seconds} s > {args.max_seconds:g} s")
    if max_chunks is None or used is None:
        problems.append("no Orchestrator finish line in the trace")
    elif used > max_chunks:
        problems.append(f"{used} chunks > max_chunks {max_chunks}")
    if used is not None and len(chunks) != used:
        problems.append(f"{len(chunks)} chunk lines in the trace for {used} chunks")
    for chunk in chunks:
        if chunk["projected_chars"] > chunk["chunk_budget_chars"]:
            problems.append(f"chunk {chunk['chunk']} input {chunk['projected_chars']} > {chunk['chunk_budget_chars']}")
    if problems:
        for problem in problems:
            print(f"[FAIL] {problem}")
        return 1
    print(f"[PASS] {used}/{max_chunks} chunks, every chunk input within budget, stop_reason={result.stop_reason}, "
          f"{result.execution_time_seconds} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

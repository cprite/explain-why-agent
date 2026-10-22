"""Plan check for the end-to-end slice (build-plan task 6): verify a run.py result file.

    SAMPLE_MODE=true python run.py "<question>" --run-id ci-day1 > result.json
    python scripts/check_result.py result.json

Checks that the result validates, has at least one cause with at least one evidence item, that every
evidence query id is in the run's query log, and that the trace file exists. Prints a summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.schemas import Result


def main(argv: list[str] | None = None) -> int:
    """Verify one result file; return the exit code."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python scripts/check_result.py RESULT.json")
        return 2
    result = Result.model_validate_json(Path(args[0]).read_text(encoding="utf-8"))
    problems = []
    if result.status != "success":
        problems.append(f"status is {result.status}: {result.error}")
    if not result.causes:
        problems.append("no cause")
    if not any(cause.evidence for cause in result.causes):
        problems.append("no evidence item")
    trace = REPO_ROOT / result.log_file
    if not trace.is_file():
        problems.append(f"trace file missing: {result.log_file}")
    logged: set[str] = set()
    if result.query_log and (REPO_ROOT / result.query_log).is_file():
        with (REPO_ROOT / result.query_log).open(encoding="utf-8") as handle:
            logged = {json.loads(line)["query_id"] for line in handle if line.strip()}
    for cause in result.causes:
        for item in cause.evidence:
            if item.query_id not in logged:
                problems.append(f"evidence query {item.query_id} not in {result.query_log}")

    print(f"question: {result.question}")
    print(f"status: {result.status}; sample_mode: {result.sample_mode}; determinable: {result.determinable}")
    for cause in result.causes:
        print(f"cause {cause.rank} [{cause.type}, confidence {cause.confidence}]: {cause.summary}")
        for item in cause.evidence:
            print(f"  evidence {item.query_id} ({item.source}): {item.finding}")
    for item in result.ruled_out:
        print(f"ruled out [{item.type}]: {item.why}")
    if trace.is_file():
        lines = trace.read_text(encoding="utf-8").count("\n")
        print(f"trace file: {result.log_file} ({lines} lines); query log: {result.query_log} ({len(logged)} queries)")
    if problems:
        for problem in problems:
            print(f"[FAIL] {problem}")
        return 1
    print(f"[PASS] {len(result.causes)} causes, {sum(len(c.evidence) for c in result.causes)} evidence items, "
          "every evidence query in the query log, trace file present")
    return 0


if __name__ == "__main__":
    sys.exit(main())

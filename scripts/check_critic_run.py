"""Plan check N (build-plan tasks 13+14): verify the Critic and the branches in a run.py result and its trace.

    python scripts/check_critic_run.py --question incident-06       # prints the question from eval/answer_key.json
    python run.py "<question>" --sample --run-id ci-plan-check-n-06 > result.json
    python scripts/check_critic_run.py result.json --expect refuted:logistics_delay
    python scripts/check_critic_run.py result.json --expect undeterminable
    python scripts/check_critic_run.py result.json --expect no-change

`--question ID` prints one question string from the answer key, so CI copies it verbatim instead of
retyping it (the answer key is read here only for the question; the agents never see it).

For a result it prints the status, stop reason, determinable, summary, the change, causes, ruled-out
list and limitations, then one line per Critic call from the trace (hypothesis, attempt, verdict,
scores, checks, follow-up tests) and one per branch decision. It fails when the result is not a
schema-valid success or the expectation does not hold:

- `refuted:<family>`: the Critic judged a hypothesis of that family and refuted it;
- `undeterminable`: determinable false, no causes, limitations given, and the summary names none of
  the hypothesis families as a cause;
- `no-change`: change.significant false, determinable true, no causes and no Critic call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.schemas import HYPOTHESIS_FAMILIES, Result

ANSWER_KEY = REPO_ROOT / "eval" / "answer_key.json"


def question(incident: str) -> str:
    """The question string of one incident in the answer key."""
    for item in json.loads(ANSWER_KEY.read_text(encoding="utf-8")):
        if item.get("id") == incident:
            return str(item["question"])
    raise SystemExit(f"no incident {incident!r} in {ANSWER_KEY}")


def trace_lines(result: Result) -> list[dict]:
    """The run's trace lines, from its last start (a reused run id appends)."""
    path = REPO_ROOT / result.log_file
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines = [line for line in lines if line.get("run_id") == result.run_id]
    starts = [i for i, line in enumerate(lines) if line.get("agent") == "Orchestrator" and line.get("action") == "start"]
    return lines[starts[-1]:] if starts else lines


def check(path: Path, expect: str) -> int:
    """Print the report for one result and return the exit code."""
    result = Result.model_validate_json(path.read_text(encoding="utf-8"))
    lines = trace_lines(result)
    critiques = [line for line in lines if line.get("agent") == "Critic" and line.get("action") == "critique"]
    branches = [line for line in lines if line.get("agent") == "Orchestrator" and line.get("action") == "branch"]

    change = result.change
    print(f"question: {result.question}")
    print(f"status: {result.status}; stop_reason: {result.stop_reason}; determinable: {result.determinable}")
    print(f"summary: {result.summary}")
    if change is not None:
        print(f"change: significant={change.significant} observed={change.observed} baseline={change.baseline} "
              f"spread={change.spread}")
    print(f"causes: {[f'{c.rank}. {c.type}: {c.summary}' for c in result.causes]}")
    print(f"ruled_out: {[f'{r.type} ({len(r.evidence)} queries)' for r in result.ruled_out]}")
    print("limitations:")
    for item in result.limitations:
        print(f"  - {item}")
    print(f"critic calls: {len(critiques)}")
    for line in critiques:
        scores = line.get("scores") or {}
        checks = ", ".join(f"{c['name']}={c['outcome']}" for c in line.get("checks") or [])
        print(f"  {line['hypothesis_id']} {line.get('family')} attempt {line.get('attempt')}: {line.get('verdict')} "
              f"total {line.get('total_score')}/9 {scores} | {checks}")
        if line.get("follow_up_tests"):
            print(f"    follow-up tests: {line['follow_up_tests']}")
        for answered in line.get("follow_up_results") or []:
            print(f"    answered by {answered['query_ids']}: {answered['finding']}")
    for line in branches:
        print(f"  branch {line['branch']}: {line['why']} {line.get('numbers')}")

    problems = []
    if result.status != "success":
        problems.append(f"status is {result.status}: {result.error}")
    if expect.startswith("refuted:"):
        family = expect.split(":", 1)[1]
        judged = [line for line in critiques if line.get("family") == family]
        if not judged:
            problems.append(f"the Critic judged no {family} hypothesis")
        elif not any(line.get("verdict") == "refuted" for line in judged):
            problems.append(f"the {family} hypothesis was not refuted: {[line.get('verdict') for line in judged]}")
    elif expect == "undeterminable":
        if result.determinable or result.causes:
            problems.append(f"determinable={result.determinable} with {len(result.causes)} causes")
        if not result.limitations:
            problems.append("no limitations")
        named = [family for family in HYPOTHESIS_FAMILIES if family in (result.summary or "")]
        if named:
            problems.append(f"the summary names {named}")
    elif expect == "no-change":
        if change is None or change.significant is not False:
            problems.append(f"change.significant is {change.significant if change else None}")
        if not result.determinable or result.causes:
            problems.append(f"determinable={result.determinable} with {len(result.causes)} causes")
        if critiques:
            problems.append(f"{len(critiques)} Critic calls on a run that should end after the change check")
    else:
        problems.append(f"unknown expectation {expect!r}")
    if problems:
        for problem in problems:
            print(f"[FAIL] {problem}")
        return 1
    print(f"[PASS] {expect}: determinable={result.determinable}, {len(result.causes)} causes, "
          f"{len(critiques)} Critic calls, stop_reason={result.stop_reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Print a question from the answer key, or check one result file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result", nargs="?")
    parser.add_argument("--question", metavar="INCIDENT_ID", help="print this incident's question and exit")
    parser.add_argument("--expect", default="", help="refuted:<family> | undeterminable | no-change")
    args = parser.parse_args(argv)
    if args.question:
        print(question(args.question))
        return 0
    if not args.result:
        parser.error("a result file is needed unless --question is given")
    return check(Path(args.result), args.expect)


if __name__ == "__main__":
    sys.exit(main())

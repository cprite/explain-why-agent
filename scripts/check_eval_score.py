"""Plan check for the evaluation (Sprint 11c): the sample-mode score must equal the committed after score.

    python eval/run_eval.py --sample | tee /tmp/eval.txt
    python scripts/check_eval_score.py /tmp/eval.txt

Fails (exit 1) when the output has no `Score: N/T (...)` line as its last line, or when a committed
`logs/eval-after-<timestamp>.json` exists and its score differs from the sample-mode score. The newest
after report (by file name) is the reference. While no after report is committed it says so and only
reports the score (exit 0): the after report is produced by a recorded run through the model, which
also re-records the sample-mode cache that CI replays.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORE_RE = re.compile(r"^Score: (\d+)/(\d+) \(answered \d+, no_cache \d+, errors \d+\)$")


def parse_score(line: str) -> tuple[int, int] | None:
    """(found, total) from a score line, or None when it is not one."""
    match = SCORE_RE.match(line.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def committed_after(logs: Path) -> Path | None:
    """The newest `eval-after-*.json` under `logs`, by name (the name carries the UTC timestamp)."""
    reports = sorted(logs.glob("eval-after-*.json"))
    return reports[-1] if reports else None


def check(output: str, logs: Path) -> tuple[int, str]:
    """(exit code, message) for one eval output."""
    lines = [line for line in output.splitlines() if line.strip()]
    score = parse_score(lines[-1]) if lines else None
    if score is None:
        return 1, "[FAIL] the eval output does not end with a 'Score: N/T (...)' line"
    after = committed_after(logs)
    if after is None:
        return 0, (f"[REPORT] sample-mode score {score[0]}/{score[1]}; no committed logs/eval-after-*.json yet, "
                   "so the score is reported, not gated")
    report = json.loads(after.read_text(encoding="utf-8"))
    expected = parse_score(str(report.get("score_line", "")))
    if expected is None:
        return 1, f"[FAIL] {after.name} has no valid score_line"
    if expected != score:
        return 1, (f"[FAIL] sample-mode score {score[0]}/{score[1]} differs from the committed after score "
                   f"{expected[0]}/{expected[1]} ({after.name})")
    return 0, f"[PASS] sample-mode score {score[0]}/{score[1]} equals the committed after score ({after.name})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", help="the saved output of eval/run_eval.py")
    parser.add_argument("--logs", default=str(REPO_ROOT / "logs"), help="where the committed after report is")
    args = parser.parse_args(argv)
    code, message = check(Path(args.output).read_text(encoding="utf-8"), Path(args.logs))
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())

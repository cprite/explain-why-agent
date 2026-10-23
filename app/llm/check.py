"""Plan check for the model generator and schemas (build-plan tasks 4+5), run in CI.

Runs the stubbed-transport generator suite (no network, no credentials) and validates the example
result, printing a one-line summary of each. The live half of the check ("one live call returns
valid JSON") is `scripts/live_check.py`, run by hand on the build machine.

    python -m app.llm.check
"""

from __future__ import annotations

import subprocess
import sys

from app.config import REPO_ROOT
from app.schemas import main as validate_examples


def main() -> int:
    """Run both checks; return the process exit code."""
    suite = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests/test_generator.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    lines = [line for line in suite.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else "no output"
    if suite.returncode == 0:
        print(f"[PASS] generator stub suite (tests/test_generator.py): {summary}")
    else:
        print(suite.stdout[-4000:])
        print(f"[FAIL] generator stub suite (tests/test_generator.py): {summary}")
    schema_status = validate_examples([])
    return 0 if suite.returncode == 0 and schema_status == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

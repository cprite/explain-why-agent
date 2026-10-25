"""Plan check O (task 23): run the README quick start exactly as written.

    python scripts/readme_quickstart.py            # print the ```bash readme-quickstart``` block
    python scripts/readme_quickstart.py --run [--timeout 1200]

`--run` extracts the one block tagged `bash readme-quickstart` from README.md, prints its commands,
and runs them with `bash -e -x -o pipefail` in the repository root (`-x` echoes each command into
the log). On Apple Silicon (Darwin with `sysctl -n hw.optional.arm64` = 1) the block runs as
`arch -arm64 /bin/bash ...`, so python, pip and the venv run as arm64 even when the caller's shell
runs under Rosetta (a universal python started from an x86_64 process starts as x86_64 and cannot
load arm64-only wheels such as pydantic_core). The environment is the caller's minus every variable named in `.env.example`, with
`SAMPLE_MODE=true` added, so no credential or service setting can leak in. Afterwards it asserts
that the block produced a new `logs/result-*.json` (a success result with `sample_mode: true`) and a
new non-empty `logs/trace-*.jsonl`. Exit 0 on pass, 1 on fail, 2 when the block is missing.

Standard library only: it runs before the block installs the dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^```bash readme-quickstart[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
ENV_NAME = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def extract_blocks(readme_text: str) -> list[str]:
    """Every ```bash readme-quickstart``` block in the text, without the fences."""
    return FENCE.findall(readme_text)


def extract_block(readme_text: str) -> str:
    """The one quick-start block; ValueError unless there is exactly one."""
    blocks = extract_blocks(readme_text)
    if len(blocks) != 1:
        raise ValueError(f"expected exactly one ```bash readme-quickstart``` block, found {len(blocks)}")
    return blocks[0]


def env_example_names(root: Path = REPO_ROOT) -> list[str]:
    """Variable names documented in .env.example."""
    return ENV_NAME.findall((root / ".env.example").read_text(encoding="utf-8"))


def clean_env(root: Path = REPO_ROOT) -> dict[str, str]:
    """The caller's environment without any .env.example variable, plus SAMPLE_MODE=true."""
    names = set(env_example_names(root))
    env = {k: v for k, v in os.environ.items() if k not in names and k != "VIRTUAL_ENV"}
    env["SAMPLE_MODE"] = "true"
    return env


def _apple_silicon() -> bool:
    """True on a Mac whose hardware is arm64, also when this process runs under Rosetta."""
    if platform.system() != "Darwin":
        return False
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True,
                             timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.stdout.strip() == "1"


def bash_command(block: str) -> list[str]:
    """The argv that runs the block: native arm64 /bin/bash on Apple Silicon, PATH bash elsewhere."""
    args = ["-e", "-x", "-o", "pipefail", "-c", block]
    if _apple_silicon():
        return ["/usr/bin/arch", "-arm64", "/bin/bash", *args]
    return ["bash", *args]


def _snapshot(logs: Path) -> set[str]:
    return {p.name for p in logs.glob("result-*.json")} | {p.name for p in logs.glob("trace-*.jsonl")}


def run(root: Path, timeout: float) -> int:
    """Run the block in `root` and check its outputs; return the exit code."""
    try:
        block = extract_block((root / "README.md").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 2
    print("--- README.md ```bash readme-quickstart``` block ---")
    print(block, end="" if block.endswith("\n") else "\n")
    cmd = bash_command(block)
    print(f"--- running it ({' '.join(cmd[:-2])} -c <block>, SAMPLE_MODE=true, no .env.example variables set) ---",
          flush=True)
    logs = root / "logs"
    before = _snapshot(logs) if logs.is_dir() else set()
    try:
        proc = subprocess.run(cmd, cwd=root,
                              env=clean_env(root), timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"[FAIL] the block did not finish within {timeout:g} s")
        return 1
    print(f"--- block exit code: {proc.returncode} ---")
    if proc.returncode != 0:
        print("[FAIL] the quick-start block failed")
        return 1

    new = _snapshot(logs) - before if logs.is_dir() else set()
    results = sorted(n for n in new if n.startswith("result-"))
    traces = sorted(n for n in new if n.startswith("trace-"))
    if not results or not traces:
        print(f"[FAIL] expected a new result and trace file in logs/, got results={results} traces={traces}")
        return 1
    failures = []
    for name in results:
        data = json.loads((logs / name).read_text(encoding="utf-8"))
        if data.get("status") != "success" or data.get("sample_mode") is not True:
            failures.append(f"{name}: status={data.get('status')} sample_mode={data.get('sample_mode')} "
                            f"error={data.get('error')}")
        else:
            causes = [c.get("type") for c in data.get("causes", [])]
            print(f"result: logs/{name} status=success sample_mode=True causes={causes}")
    for name in traces:
        lines = [ln for ln in (logs / name).read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            failures.append(f"{name}: empty trace")
        else:
            print(f"trace: logs/{name} ({len(lines)} lines)")
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1
    print(f"[PASS] README quick start produced {len(results)} result file(s) and {len(traces)} trace file(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="run the block and check its outputs")
    parser.add_argument("--timeout", type=float, default=1200.0, help="seconds the block may take (default 1200)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.run:
        return run(args.root, args.timeout)
    try:
        print(extract_block((args.root / "README.md").read_text(encoding="utf-8")), end="")
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

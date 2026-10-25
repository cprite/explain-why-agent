"""Evaluation: run every answer-key question and score the result (architecture §9).

    python eval/run_eval.py [--sample] [--only incident-04 ...] [--timeout S] [--total-timeout S]
                            [--loop markovian|simple] [--label before|after]

Each question runs through the same code path as `run.py` (`LocalDataLayer` + `Generator` + the
loop chosen by `--loop`, else `LOOP`: the Markovian orchestrator by default, as `run.py`; since
Sprint 11c, before it the eval always ran the simple loop) in its own child process, so the
per-question timeout really stops it; a crashed or timed-out question is recorded as an error and
the run continues. The whole run is capped too: questions not started before the cap are recorded
as `run_cap_reached`.

Prints a per-incident table, the reasons behind every failed check, and a last line
`Score: N/10 (answered A, no_cache M, errors E)`; writes the same as JSON to
`logs/eval-<timestamp>.json` (`logs/eval-<label>-<timestamp>.json` with `--label`) with each
question's run id, trace, query log and the model routes its replies came from. Exit code 0 whenever
scoring completed, whatever the score; 2 on bad arguments.

Configuration (environment, with defaults): `EVAL_QUESTION_TIMEOUT_SECONDS` (600) and
`EVAL_TOTAL_TIMEOUT_SECONDS` (3600). This is the only module that reads `eval/answer_key.json`.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
# Run as a script: the scoring module next to this file and the app package at the repo root.
sys.path[:0] = [str(EVAL_DIR), str(REPO_ROOT)]

from scoring import CHECKS, score, vocabulary_gaps

from app.config import get_settings, resolve_path
from app.runner import LOOPS, select_loop
from app.schemas import HYPOTHESIS_FAMILIES, Result

ANSWER_KEY = EVAL_DIR / "answer_key.json"
WRONG_TYPES = EVAL_DIR / "wrong_explanation_types.json"
DEFAULT_QUESTION_TIMEOUT = 600
DEFAULT_TOTAL_TIMEOUT = 3600

# (result or None, error or None) for one question; error is {"code", "message"}.
Outcome = tuple[Result | None, dict[str, str] | None]
Runner = Callable[[str, str, bool, float], Outcome]
LABELS = ("before", "after")


def env_seconds(name: str, default: int) -> int:
    """A positive whole number of seconds from the environment, or `default` when unset or empty."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {raw}")
    return value


def load_incidents(
    answer_key: Path = ANSWER_KEY, wrong_types: Path = WRONG_TYPES
) -> list[dict[str, Any]]:
    """The answer key, each incident with its `wrong_explanation_type` from the eval-only mapping."""
    incidents = json.loads(answer_key.read_text(encoding="utf-8"))
    mapping = json.loads(wrong_types.read_text(encoding="utf-8"))
    for incident in incidents:
        entry = mapping.get(incident["id"])
        if entry is None:
            raise ValueError(f"{wrong_types.name} has no entry for {incident['id']}")
        if entry["type"] is not None and entry["type"] not in HYPOTHESIS_FAMILIES:
            raise ValueError(f"{wrong_types.name}: {incident['id']} type {entry['type']!r} is not a CauseType")
        incident["wrong_explanation_type"] = entry["type"]
    return incidents


def run_question(question: str, run_id: str, sample: bool, timeout: float, loop: str | None = None) -> Outcome:
    """Run one question in a child process (see `worker`); kill it after `timeout` seconds."""
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--run-id", run_id, "--question", question]
    if sample:
        command.append("--sample")
    if loop:
        command += ["--loop", loop]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT, check=False)
    except subprocess.TimeoutExpired:
        return None, {"code": "timeout", "message": f"no result within {timeout:g} s; the question was stopped"}
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or ["no output"])[-1]
        return None, {"code": "crashed", "message": f"exit code {proc.returncode}: {tail}"}
    try:
        return Result.model_validate_json(proc.stdout), None
    except ValueError as exc:
        return None, {"code": "bad_result", "message": f"{type(exc).__name__}: {str(exc)[:300]}"}


def worker(question: str, run_id: str, sample: bool, loop: str | None = None) -> int:
    """Child process: the `run.py` wiring for one question; prints the Result JSON."""
    from app.data.local import LocalDataLayer
    from app.llm.generator import Generator

    settings = get_settings()
    if sample:
        settings = settings.model_copy(update={"sample_mode": True})
    if select_loop(settings, loop) == "simple":
        from app.loop import run_investigation as run
    else:
        from app.engines.markovian.orchestrator import run_markovian as run
    with LocalDataLayer(run_id=run_id, settings=settings) as data:
        result = run(question, run_id=run_id, generate=Generator(settings), data=data, settings=settings)
    print(result.model_dump_json(indent=2))
    return 0


def trace_tokens(log_file: str | None) -> int | None:
    """Total tokens over the model calls in a run's trace; None when the trace has no token counts."""
    if not log_file:
        return None
    path = resolve_path(log_file)
    if not path.is_file():
        return None
    total, seen = 0, False
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            tokens = json.loads(line).get("tokens")
            if isinstance(tokens, dict) and isinstance(tokens.get("total_tokens"), int):
                total += tokens["total_tokens"]
                seen = True
    return total if seen else None


def trace_routes(log_file: str | None) -> list[str]:
    """The model routes behind a run's replies, `<recorded_with or provider>:<model_routed>`, sorted."""
    if not log_file:
        return []
    path = resolve_path(log_file)
    if not path.is_file():
        return []
    routes = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            entry = json.loads(line) if line.strip() else {}
            if entry.get("action") == "model_call" and entry.get("status") == "ok":
                routes.add(f"{entry.get('recorded_with') or entry.get('provider')}:{entry.get('model_routed')}")
    return sorted(routes)


def evaluate(
    incidents: list[dict[str, Any]],
    *,
    sample: bool,
    question_timeout: float,
    total_timeout: float,
    run_prefix: str,
    runner: Runner = run_question,
) -> list[dict[str, Any]]:
    """Run and score every incident in order; one row per incident."""
    deadline = time.monotonic() + total_timeout
    rows = []
    for incident in incidents:
        run_id = f"{run_prefix}-{incident['id']}"
        remaining = deadline - time.monotonic()
        started = time.perf_counter()
        if remaining <= 0:
            result, error = None, {"code": "run_cap_reached",
                                   "message": f"EVAL_TOTAL_TIMEOUT_SECONDS={total_timeout:g} reached before this question"}
        else:
            try:
                result, error = runner(incident["question"], run_id, sample, min(question_timeout, remaining))
            except Exception as exc:  # noqa: BLE001 - one broken question must not stop the run
                result, error = None, {"code": "crashed", "message": f"{type(exc).__name__}: {exc}"}
        elapsed = round(time.perf_counter() - started, 3)
        if result is not None:
            row = score(result, incident)
            row.update(run_time_seconds=elapsed, tokens=trace_tokens(result.log_file),
                       trace_file=result.log_file, query_log=result.query_log,
                       model_routes=trace_routes(result.log_file))
        else:
            row = {"id": incident["id"], "status": "error", "found": False, "checks": {}, "error": error,
                   "run_time_seconds": elapsed, "tokens": None, "trace_file": None, "query_log": None}
            gaps = vocabulary_gaps([incident]).get(incident["id"])
            if gaps:
                row["cause_type_not_in_vocabulary"] = gaps
        row["run_id"] = run_id
        rows.append(row)
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Counts behind the score line."""
    statuses = [row["status"] for row in rows]
    return {
        "found": statuses.count("found"),
        "total": len(rows),
        "answered": statuses.count("found") + statuses.count("not_found"),
        "no_cache": statuses.count("no_cache"),
        "errors": statuses.count("error"),
    }


def score_line(summary: dict[str, int]) -> str:
    return (f"Score: {summary['found']}/{summary['total']} (answered {summary['answered']}, "
            f"no_cache {summary['no_cache']}, errors {summary['errors']})")


def _mark(check: dict[str, Any] | None) -> str:
    if check is None:
        return "-"
    return {True: "PASS", False: "FAIL", None: "n/a"}[check["pass"]]


def render(rows: list[dict[str, Any]], gaps: dict[str, list[str]]) -> str:
    """The per-incident table, the reasons for failed checks and errors, and the score line."""
    header = ("id", "status", *CHECKS, "undeterminable", "time_s", "tokens")
    table = [header]
    for row in rows:
        checks = row["checks"]
        table.append((
            row["id"], row["status"], *(_mark(checks.get(name)) for name in (*CHECKS, "undeterminable")),
            f"{row['run_time_seconds']:.1f}", "-" if row["tokens"] is None else str(row["tokens"]),
        ))
    widths = [max(len(line[i]) for line in table) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
             for line in table]
    lines.append("")
    lines.append("Detail:")
    for row in rows:
        lines.append(f"  {row['id']} [{row['status']}] run_id={row['run_id']} trace={row['trace_file'] or '-'}")
        if row["error"]:
            lines.append(f"    error {row['error']['code']}: {row['error']['message']}")
        for name, check in row["checks"].items():
            lines.append(f"    {name}: {_mark(check)} - {check['reason']}")
    for incident_id, missing in gaps.items():
        lines.append(f"cause_type_not_in_vocabulary: {', '.join(missing)} ({incident_id})")
    lines.append("")
    lines.append(score_line(summarise(rows)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run and score the questions, print and save the report."""
    parser = argparse.ArgumentParser(description="Score the agent against the answer key.")
    parser.add_argument("--sample", action="store_true", help="Force sample mode (local data, cached model replies)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="Only these incident ids, e.g. incident-04")
    parser.add_argument("--timeout", type=float, help="Seconds per question (default EVAL_QUESTION_TIMEOUT_SECONDS)")
    parser.add_argument("--total-timeout", type=float, help="Seconds for the whole run (default EVAL_TOTAL_TIMEOUT_SECONDS)")
    parser.add_argument("--loop", choices=LOOPS, help="Investigation loop (default LOOP, else markovian, as run.py)")
    parser.add_argument("--label", choices=LABELS, help="Name the report logs/eval-<label>-<timestamp>.json")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--question", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.worker:
        return worker(args.question, args.run_id, args.sample, args.loop)

    try:
        question_timeout = args.timeout or env_seconds("EVAL_QUESTION_TIMEOUT_SECONDS", DEFAULT_QUESTION_TIMEOUT)
        total_timeout = args.total_timeout or env_seconds("EVAL_TOTAL_TIMEOUT_SECONDS", DEFAULT_TOTAL_TIMEOUT)
    except ValueError as exc:
        parser.error(str(exc))
    if question_timeout <= 0 or total_timeout <= 0:
        parser.error("timeouts must be positive")

    incidents = load_incidents()
    if args.only:
        known = {incident["id"] for incident in incidents}
        unknown = [incident_id for incident_id in args.only if incident_id not in known]
        if unknown:
            parser.error(f"unknown incident id(s): {', '.join(unknown)}")
        incidents = [incident for incident in incidents if incident["id"] in args.only]

    settings = get_settings()
    try:
        loop = select_loop(settings, args.loop)
    except ValueError as exc:
        parser.error(str(exc))
    sample = args.sample or settings.sample_mode
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    started = time.perf_counter()
    rows = evaluate(incidents, sample=sample, question_timeout=question_timeout, total_timeout=total_timeout,
                    run_prefix=f"eval-{stamp}", runner=functools.partial(run_question, loop=loop))
    gaps = vocabulary_gaps(incidents)
    summary = summarise(rows)

    report = {
        "timestamp": stamp,
        "sample_mode": sample,
        "loop": loop,
        "label": args.label,
        "model_routes": sorted({route for row in rows for route in row.get("model_routes", [])}),
        "question_timeout_seconds": question_timeout,
        "total_timeout_seconds": total_timeout,
        "run_time_seconds": round(time.perf_counter() - started, 3),
        **summary,
        "score_line": score_line(summary),
        "cause_type_not_in_vocabulary": gaps,
        "incidents": rows,
    }
    name = f"eval-{args.label}-{stamp}.json" if args.label else f"eval-{stamp}.json"
    out = resolve_path(settings.log_dir) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        shown = out.relative_to(REPO_ROOT)
    except ValueError:
        shown = out
    print(f"Evaluation, {'sample' if sample else 'live'} mode, {loop} loop, {len(rows)} question(s); report: {shown}")
    print()
    print(render(rows, gaps))
    return 0


if __name__ == "__main__":
    sys.exit(main())

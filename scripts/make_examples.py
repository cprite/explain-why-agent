"""Regenerate the three examples in input_examples/ and output_examples/ in sample mode (Sprint 16).

    python scripts/make_examples.py [--out-dir DIR] [--input-dir DIR] [--log-dir DIR]

For each example the question is read verbatim from eval/answer_key.json and written as a
`POST /run` body to `input_examples/example_N.json`. The question then runs through
`app.runner.execute_run` (the code path of `run.py` and `POST /run`) in sample mode with the
Markovian loop and run id `example_N`, and the script copies what the app wrote:

- `output_examples/example_N.json`: the result, as the app wrote it to `logs/result-example_N.json`;
- `output_examples/example_N.trace.jsonl`: its trace (`logs/trace-example_N.jsonl`), with the
  requested model, the routed model and `recorded_with` on every `model_call` line;
- `output_examples/example_N.meta.json`: which input, answer-key incident and loop produced it, and
  how many of the cache entries the run replayed were recorded with the stub and how many with
  Meterless Nightshift. A stub-recorded entry is a reply of the deterministic stand-in in
  `app/llm/stub.py`, not a model's answer; the result schema has no room for this, hence the
  separate file.

No network: sample mode replays `data/sample/llm_cache` and reads `data/sample`. Every variable
named in `.env.example` is dropped from this process's environment first, so a local `.env` or
shell setting cannot change the outputs. A file whose new content differs from the committed one
only in run-specific fields (timestamps, durations) is left as it is, so a rerun on an unchanged
cache leaves `git status` clean. Exit 0 when all three runs ended in a success result, 1 otherwise
(the files are still written, so a cache miss shows up in the outputs rather than as a crash).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT, Settings, resolve_path

ANSWER_KEY = REPO_ROOT / "eval" / "answer_key.json"
LOOP = "markovian"
# (example number, answer-key incident, what it shows)
EXAMPLES = (
    (1, "incident-01", "Day 1: the order-volume spike on 24 November 2017, ranked causes with evidence"),
    (2, "incident-06", "review-score dip: the Critic refutes the delivery-delay explanation and product quality is kept"),
    (3, "incident-09", "cannot be determined: too few reviews behind the drop, so no cause is asserted"),
)
# Fields that differ between two runs of the same question on the same cache.
VOLATILE_KEYS = {"timestamp", "execution_time_seconds", "duration_s", "duration_ms", "elapsed_s", "elapsed_seconds"}
ENV_NAME = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def question(incident: str) -> str:
    """The question of one incident in the answer key, verbatim."""
    for item in json.loads(ANSWER_KEY.read_text(encoding="utf-8")):
        if item.get("id") == incident:
            return str(item["question"])
    raise SystemExit(f"no incident {incident!r} in {ANSWER_KEY}")


def request_body(incident: str) -> dict:
    """The `POST /run` body of one example."""
    return {"input": {"query": question(incident)}, "options": {"sample_mode": True}}


def normalise(value):
    """`value` with the run-specific fields (timestamps, durations) blanked, recursively."""
    if isinstance(value, dict):
        return {k: (None if k in VOLATILE_KEYS else normalise(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    return value


def normalised_text(text: str, jsonl: bool) -> str:
    """Normalised canonical form of a JSON or JSONL text, for comparing two outputs."""
    if jsonl:
        rows = [normalise(json.loads(line)) for line in text.splitlines() if line.strip()]
        return "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    return json.dumps(normalise(json.loads(text)), sort_keys=True)


def write_if_changed(path: Path, text: str, jsonl: bool = False) -> str:
    """Write `text` unless `path` already holds the same content up to run-specific fields."""
    if path.exists():
        try:
            if normalised_text(path.read_text(encoding="utf-8"), jsonl) == normalised_text(text, jsonl):
                return "unchanged"
        except json.JSONDecodeError:
            pass
    path.write_text(text, encoding="utf-8")
    return "written"


def model_calls(trace_text: str) -> list[dict]:
    """The `model_call` lines of a trace."""
    rows = [json.loads(line) for line in trace_text.splitlines() if line.strip()]
    return [row for row in rows if row.get("action") == "model_call"]


def meta(number: int, incident: str, shows: str, result: dict, calls: list[dict]) -> dict:
    """Provenance of one example: input, loop, and stub vs Meterless cache entries replayed."""
    entries: dict[str, str] = {}
    for call in calls:
        if call.get("cache_key"):
            entries[call["cache_key"]] = str(call.get("recorded_with") or "unknown")
    by_kind = Counter(entries.values())
    stub, meterless = by_kind.get("stub", 0), by_kind.get("meterless", 0)
    if not calls:
        note = "No model call was replayed."
    elif meterless and not stub:
        note = "Every replayed reply was recorded live through Meterless Nightshift."
    elif stub and not meterless:
        note = ("Every replayed reply was recorded from the deterministic stand-in model (app/llm/stub.py): "
                "this output shows the agent logic, not a model's answer.")
    else:
        note = f"Mixed recording: {stub} stub entries and {meterless} Meterless entries."
    return {
        "example": number,
        "input": f"input_examples/example_{number}.json",
        "answer_key_id": incident,
        "shows": shows,
        "loop": LOOP,
        "sample_mode": True,
        "status": result.get("status"),
        "error_code": (result.get("error") or {}).get("code"),
        "model_calls": len(calls),
        "cache_entries": {"stub": stub, "meterless": meterless,
                          "other": sum(n for kind, n in by_kind.items() if kind not in ("stub", "meterless"))},
        "models_requested": sorted({str(c.get("model_requested")) for c in calls if c.get("model_requested")}),
        "models_routed": sorted({str(c.get("model_routed")) for c in calls if c.get("model_routed")}),
        "note": note,
    }


def clean_environment() -> None:
    """Drop every variable named in .env.example (commented or not) from this process's environment."""
    names = set(ENV_NAME.findall((REPO_ROOT / ".env.example").read_text(encoding="utf-8")))
    for name in names:
        os.environ.pop(name, None)


def run_example(number: int, incident: str, shows: str, out_dir: Path, input_dir: Path, log_dir: str) -> bool:
    """Write one example's input, result, trace and meta; True when the run succeeded."""
    from app.runner import execute_run

    run_id = f"example_{number}"
    body = request_body(incident)
    status_in = write_if_changed(input_dir / f"{run_id}.json", json.dumps(body, indent=2, ensure_ascii=False) + "\n")

    settings = Settings(sample_mode=True, loop=LOOP, log_dir=log_dir)
    logs = resolve_path(settings.log_dir)
    logs.mkdir(parents=True, exist_ok=True)
    for old in logs.glob(f"*-{run_id}.*"):  # a reused run id would append to the old trace
        old.unlink()
    execute_run(body["input"]["query"], run_id=run_id, settings=settings, loop=LOOP)

    result_text = (logs / f"result-{run_id}.json").read_text(encoding="utf-8")
    trace_text = (logs / f"trace-{run_id}.jsonl").read_text(encoding="utf-8")
    result = json.loads(result_text)
    info = meta(number, incident, shows, result, model_calls(trace_text))
    status_out = write_if_changed(out_dir / f"{run_id}.json", result_text)
    status_trace = write_if_changed(out_dir / f"{run_id}.trace.jsonl", trace_text, jsonl=True)
    status_meta = write_if_changed(out_dir / f"{run_id}.meta.json", json.dumps(info, indent=2) + "\n")
    entries = info["cache_entries"]
    print(f"example_{number} ({incident}, loop {LOOP}): status={info['status']} determinable={result.get('determinable')} "
          f"causes={[c.get('type') for c in result.get('causes', [])]} model_calls={info['model_calls']} "
          f"cache entries stub={entries['stub']} meterless={entries['meterless']} | input {status_in}, "
          f"result {status_out}, trace {status_trace}, meta {status_meta}")
    return info["status"] == "success"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "output_examples")
    parser.add_argument("--input-dir", type=Path, default=REPO_ROOT / "input_examples")
    parser.add_argument("--log-dir", default="logs", help="LOG_DIR for the runs (default logs)")
    args = parser.parse_args(argv)
    clean_environment()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.input_dir.mkdir(parents=True, exist_ok=True)
    ok = [run_example(n, incident, shows, args.out_dir, args.input_dir, args.log_dir) for n, incident, shows in EXAMPLES]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())

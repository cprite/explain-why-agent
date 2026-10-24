"""Record sample-mode cache entries for a question with the scripted stub (no model key needed).

    python scripts/record_stub_cache.py "Why did order volume spike on 24 November 2017?" --loop simple
    python scripts/record_stub_cache.py "<question>" --record-queries

Runs the real investigation (agents, DuckDB queries) with `app.llm.stub.ScriptedModel` standing in
for the model, and writes one cache entry per model call to `LLM_CACHE_DIR` (default
`data/sample/llm_cache/`), each marked `"recorded_with": "stub"`. `--loop` picks the Markovian
orchestrator (default, what run.py uses) or the simple loop; the two send different prompts, so
each needs its own recording. `--record-queries` also writes the query rows to `QUERY_CACHE_DIR`
(default `data/sample/query_cache/`) so sample mode serves the same rows on every machine. Replace these with a real
recording: `SAMPLE_MODE=false RECORD_CACHE=true python run.py "<question>"` through Meterless.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, resolve_path
from app.data.local import LocalDataLayer
from app.engines.markovian.orchestrator import run_markovian
from app.llm.generator import GenerationResult, Message, ResponseCache
from app.llm.stub import ScriptedModel
from app.loop import run_investigation


class StubRecorder:
    """Wraps the scripted stub and writes each reply to the cache under the generator's key."""

    def __init__(self, cache: ResponseCache) -> None:
        self.cache = cache
        self.stub = ScriptedModel()
        self.written: list[Path] = []

    def __call__(self, messages: list[Message], *, schema=None, role="default", run_id=None) -> GenerationResult:
        result = self.stub(messages, schema=schema, role=role, run_id=run_id)
        if result.ok:
            schema_name = schema.__name__ if schema else None
            key = ResponseCache.key(messages, schema_name, role)
            self.written.append(
                self.cache.put(
                    key,
                    {
                        "role": role,
                        "schema": schema_name,
                        "messages": messages,
                        "reply": result.content,
                        "provider": "stub",
                        "model_requested": None,
                        "model_routed": result.model_routed,
                        "receipt_id": None,
                        "usage": None,
                        "recorded_with": "stub",
                        "recorded_at": None,
                    },
                )
            )
        return result


def main(argv: list[str] | None = None) -> int:
    """Record the cache for one question; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--run-id", default="record-stub")
    parser.add_argument("--loop", choices=("markovian", "simple"), default="markovian",
                        help="investigation loop to record (default markovian, as run.py)")
    parser.add_argument("--record-queries", action="store_true", help="also record the query rows")
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(update={"sample_mode": False, "record_cache": args.record_queries})
    recorder = StubRecorder(ResponseCache(resolve_path(settings.llm_cache_dir)))
    run = run_investigation if args.loop == "simple" else run_markovian
    with LocalDataLayer(run_id=args.run_id, settings=settings) as data:
        result = run(
            args.question, run_id=args.run_id, generate=recorder, data=data, settings=settings, sample_mode=False
        )
    print(f"status: {result.status}; causes: {len(result.causes)}; entries written: {len(recorder.written)}")
    for path in recorder.written:
        print(f"  {path.relative_to(resolve_path('.'))}")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

# Sprint 8 — Markovian orchestrator replaces the simple loop

Build-plan task 12, issue #21. The Markovian orchestrator (architecture §4, §5.2) now runs every
`run.py` investigation by default. It is built from the World Model (Sprint 5, PR #14) and the
Markovian config, chunk manager and carryover cascade (Sprint 7, PR #15). The Sprint 2 loop is still
there: `run.py --loop simple` or `LOOP=simple`.

## What was built

- `app/engines/markovian/orchestrator.py` — `run_markovian(question, run_id=, generate=, data=,
  settings=, config=, critic=)`. The agents (Planner, Investigator, Reporter) and the generator are
  injected; the module makes no HTTP call.
  - **Chunk 1** (the architecture's "chunk 0"): the Planner's plan; the question and the hypotheses
    go into the run's World Model; the change check runs on the chunk input. That input is the goal
    plus the ContextBuilder's `plan` payload for the question.
  - **Each later chunk**: one round on one hypothesis, in the Planner's priority order. The
    `ChunkManager` packs the input within `MARKOVIAN_CHUNK_BUDGET_CHARS`: goal, the carryover from
    the chunk before, then the ContextBuilder's `investigate` items for the hypothesis followed by
    its `plan` overview. The Investigator gets this as `chunk` in its SQL request. A note in
    `app/agents/prompts/chunk_note.md` is appended to its system prompt. The existing prompt files
    are unchanged, and without `context` the request is byte-identical to the simple loop's.
    Each successful query result goes into the World Model through `IngestPipeline`. The rows are
    stored for provenance, and the measured value is stored against its baseline with a `supports`
    or `refutes` edge. `critic_hook` runs next. The ranking is then updated: supported first, by
    |effect|, then ruled out, then open. `build_carryover` turns it into the state for the next
    chunk, with `rounds_left` taken from `ChunkManager.rounds_left`.
  - **Critic seam**: `critic_hook(CriticRequest) -> Verdict | None`. The default returns None. A
    verdict overrides the Investigator's reading: `supported` ranks the hypothesis, `refuted` rules
    it out, `insufficient` leaves it open. `CriticRequest` carries the plan, the hypothesis and its
    World Model id, the observation, the chunk text, the `ContextBuilder` (for a `critique`
    payload), the budget and the generator. Sprint 9 replaces the default.
  - **Report**: the Reporter gets the last carryover plus the ContextBuilder's `report` payload,
    packed by `ChunkManager.build_input`. It does not count as a chunk. If the Reporter asks for
    follow-up hypotheses (at most 2 per report, at most 3 reports), they run in further chunks
    while the cap allows.
  - **Stops**: every stop returns a schema-valid `Result` with `stop_reason`:
    - `completed`: every hypothesis tested and reported;
    - `max_chunks`: hypotheses left when the cap was reached. The Reporter still answers from what
      was tested, and the untested ids are listed in `limitations`;
    - `timeout`: the run passed `MARKOVIAN_RUN_TIMEOUT_S`, or one chunk passed
      `MARKOVIAN_CHUNK_TIMEOUT_SECONDS`. The result is an error with code `timeout`, and what was
      measured before the stop is listed in `limitations`;
    - `no_hypotheses`: the change check found no significant change, so nothing was tested. The
      result is a success with `determinable: false`;
    - `error`: no plan, no report, an unexpected exception or an invalid `MARKOVIAN_*` value. The
      error code comes from the failure, e.g. `cache_miss` or `retries_exhausted`.

    A model failure on one hypothesis is not fatal: it goes into `limitations` as "Not tested: …"
    (as in the simple loop).
  - **Never hangs**: the investigation runs in a daemon worker thread. The calling thread checks the
    run and chunk deadlines every 0.1 s. On a timeout it builds the timeout result and sets a cancel
    flag; from then on the metered generator and the observed data layer refuse new calls, so the
    worker winds down. Before returning it interrupts any data call in flight
    (`LocalDataLayer.interrupt()`, which interrupts every running DuckDB cursor, schema reads
    included) and waits, at most 5 s, until the worker has left the data layer, then up to 0.5 s for
    the worker to end. Without that wait `run.py` closed the data layer while the worker was still
    inside a DuckDB call: the close raised "connection is busy", the timeout result was lost and
    DuckDB aborted the interpreter at exit (exit code 134). `LocalDataLayer.close()` now interrupts
    running statements itself, and `run.py` reports a close failure on stderr instead of letting it
    replace the result.
  - **Logs**:
    - `logs/trace-<run>.jsonl` gets one `Orchestrator` / `chunk` line per chunk: `chunk`,
      `max_chunks`, `kind`, `hypothesis_id`, `queries`, `carryover_step` (the step that produced
      the carryover the chunk read), `carryover_out_step`, `projected_chars` (the chunk input),
      `actual_chars` (everything sent to the model in the chunk, agent prompts and source schemas
      included), `output_chars`, `chunk_budget_chars`, `standard_chars`, `rounds_left` and
      `duration_s`. A `finish` line follows with `stop_reason`, `chunks_used` and `max_chunks`;
    - `logs/markovian-<run>.jsonl` gets one line per chunk: the chunk record with token estimates
      and the carryover in and out (architecture §8);
    - `logs/world-<run>.jsonl` holds the run's World Model append log.

    `token_report` in the result compares the standard estimate (growing conversation) with the
    Markovian chunk inputs, using the guide's `ceil(chars / 4)` token estimate.
  - **Per-run World Model**: the store is in memory, one per run. A store shared across runs would
    put other runs' queries into the prompt. The ContextBuilder's selection reasons name the run
    that wrote an edge ("run <id>"); in a per-run store that is always this run, so the
    orchestrator replaces it with "this run". Prompts therefore depend only on the run's own work,
    and the sample-mode cache keys are stable. This is checked with two different run ids, and by a
    test that the run id never appears in a model request.
- `MARKOVIAN_RUN_TIMEOUT_S` (default 540, >0, ≤3600) in `MarkovianConfig`, and `LOOP` (default
  `markovian`) in `Settings`, both documented in `.env.example`. `Result.stop_reason` is new and
  optional. `run.py` leaves the key out when it is None, so the simple loop's JSON keeps its Sprint
  2 shape.
- `run.py --loop markovian|simple`. The flag wins over `LOOP`; a bad `LOOP` value exits 2 with
  `bad_loop`.
- `scripts/check_markovian_run.py RESULT.json`: the plan-check report (below).
- `scripts/record_stub_cache.py`: `--loop` (default `markovian`) and `--record-queries` (also writes
  the query rows to `data/sample/query_cache/`).
- `app/llm/stub.py`: the scripted model learns a second generic question shape, delivery lateness on
  a day or in "the week of" a date. It measures the share of deliveries completed after their
  estimate, in that window against the four weeks before. It tests four hypotheses: longer carrier
  transit, more deliveries than usual, a single seller and invalid delivery dates. Like the
  order-volume shape, it knows nothing about the planted incidents.

### Carried over from the Sprint 7 review

- **Heuristic extraction** (`carryover.py`, step 3). Lines are split into clauses at `;` and at
  while / whereas / but / although. A rejection phrase is filed under the hypothesis id nearest
  before it, or under the single id after it ("Ruled out: H1 (…)"). It becomes an open question
  instead when:
  - the phrase is negated ("not ruled out", "cannot be ruled out", "have not excluded", "never been
    ruled out", "yet to be rejected");
  - the clause is a question;
  - the attribution is ambiguous (several ids before the phrase, or several after it with none
    before).

  A clause that says a hypothesis "is supported" or "is the leading cause" ranks it. Both reviewers'
  example texts are regression tests.
- **Abandoned compression thread**. `Generator.with_limits(deadline_seconds=, max_retries=0)`
  returns a generate function whose calls end by the deadline:
  - each HTTP request's timeout is cut to the time left;
  - there is no retry sleep past the deadline;
  - there is no repair or fallback call once the deadline has passed.

  `model_compression` uses it with a deadline of 0.9 × `compression_timeout_seconds`. The HTTP call
  therefore gives up before the cascade stops waiting, and the worker thread has ended when
  `build_carryover` returns. Tested with a slow mock server: one request, its read timeout cut to
  0.45 s, no `carryover-compress` thread alive afterwards.
- **Fallback ids**: `FallbackIds` is one running counter. The orchestrator shares one per run, so a
  `C`/`R` id never names two items.
- **rounds_left**: the orchestrator always passes `ChunkManager.rounds_left` to the carryover; a
  test checks it on every chunk. The carryover sample mode now takes it from a `ChunkManager` too
  (same output).
- Also from that review: `ChunkManager.start_chunk` / `build_input` accept the ContextBuilder's dict
  payload (`as_context_payload`), and `render_item` writes a dict summary as compact sorted-key
  JSON. The Sprint 7 note's line that the ContextBuilder "is not on main yet" is out of date; the
  real builder is wired here.

### Sample-mode cache and CI

- The plan-check question's cache is 12 entries in `data/sample/llm_cache/`, all marked
  `recorded_with: stub` (provider `stub`, model `scripted-stub`). It also has 5 query-row files in
  `data/sample/query_cache/`. They were recorded with:

  ```
  python scripts/record_stub_cache.py "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?" --record-queries --run-id record-plan-check-i
  ```

  A coordinator re-records them through Nightshift after the PR. The 15 Day 1 entries
  (`recorded_with: meterless`) and their 5 query files are untouched.
- The orchestrator sends different prompts from the simple loop, so the Day 1 question misses the
  cache under the new default (a structured `cache_miss` error). Two things that use the Day 1
  recording are therefore **pinned to the simple loop**:
  - CI "Plan check C" (`--loop simple` and `LOOP=simple`). Its output is unchanged: the
    `check_result.py` lines are identical and so is the result JSON apart from
    `execution_time_seconds`;
  - the three `run.py` CLI tests in `tests/test_loop.py` (`LOOP=simple` in `_run_cli`).
- `test_committed_cache_entries_are_real_meterless_recordings` now accepts the stub entries if they
  are marked as such. All other entries, including every Day 1 entry, must still be live Meterless
  recordings on Nemotron with a receipt (at least 15).
- New CI step **"Plan check I (task 12)"**. It runs the plan-check question in sample mode under
  `timeout 600`, prints the wall-clock seconds, then runs `scripts/check_markovian_run.py`. The
  script fails on:
  - a non-success result, or a `stop_reason` of `timeout` or `error`;
  - more chunks than `max_chunks`;
  - any chunk input over `chunk_budget_chars`;
  - a chunk-line count that differs from `chunks_used`;
  - more than 600 s.

  Plan checks A–H are unchanged.

## Left out

- **The Critic** (Sprint 9). Only the `critic_hook` seam exists. The run's verdicts come from the
  Investigator's `supports` reading, and `Verdict` scoring and revision requests are not built.
- **Real-model cache for the plan-check question**. The committed entries are stub recordings, so
  the plan-check answer shows the orchestrator's mechanics, not a model's reasoning. Re-record
  through Nightshift with `SAMPLE_MODE=false RECORD_CACHE=true python run.py "<question>"`.
- **A Markovian recording of the Day 1 question**. Day 1 still replays only under `--loop simple`.
- The architecture's `investigate-and-critique` per chunk is investigate-only until the Critic
  lands. A carryover compressor reply is not recorded either: in these runs the explicit state
  always fits, so step 2 is never reached.

## How it was tested

- `tests/test_markovian_orchestrator.py` (25 tests, scripted stub, real DuckDB and World Model):
  - completed runs on both question shapes;
  - sample-mode replay of the committed cache under two run ids, every call a cache hit;
  - `max_chunks` at caps 1–4, and a Reporter that always asks for follow-ups (never above the cap);
  - run timeout with a stub that stalls 10 s (returns in under 6 s including data loading), and a
    chunk timeout;
  - a run timeout while the worker is inside a stalled schema read: the read is interrupted, the
    worker has left the data layer when the run returns, and closing the layer works;
  - `no_hypotheses`;
  - generator errors on the Plan and on the Report (`error`), on one investigation (noted, run
    goes on), a generator that raises, and an invalid `MARKOVIAN_MAX_CHUNKS`;
  - every chunk input within the chunk budget at budgets 1000, 2500 and 12000, read from the
    trace;
  - one trace entry per chunk with the listed fields, and the markovian and world logs;
  - `rounds_left` equal to `max_chunks - chunk`;
  - chunk inputs carrying the state and the evidence;
  - the default critic hook gives no verdict, and a custom verdict moves H1 to ruled out;
  - the run id never appears in a model request, although the critique payload names it.
- `tests/test_markovian_review_fixes.py` (10 tests): both reviewers' heuristic lines, contrast
  clauses, ambiguous rejections, negation words, fallback ids within a text and across a run, the
  compression timeout leaving no thread, the bounded generator not retrying while the plain one
  still retries 3 times, and the real ContextBuilder payload through `start_chunk`.
- `tests/test_run_loop.py` (9 tests): the default is the orchestrator; `--loop simple`, `LOOP=simple`
  and flag-over-variable; a bad `LOOP`; `run.py` on the plan-check question with
  `MARKOVIAN_RUN_TIMEOUT_S` of 0.02, 0.05 and 0.1 s exits 1 with a valid JSON result,
  `stop_reason: timeout` and no traceback or DuckDB abort on stderr (before the fix 11 of 12 such
  runs between 0.02 and 0.3 s exited 134 with an `internal` error).
- `tests/test_data_local.py`: `close()` while another thread runs a slow query returns, and the
  query ends with code `cancelled`; `interrupt()` stops a query and the layer stays usable.
- Whole suite: `pytest -q` gives 304 passed under
  `systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0` on the build machine (arm64), about
  100 s. `ruff check .` is clean. No test uses the network: the generator runs on the stub, the
  cache or an httpx `MockTransport`.
- Every CI step that existed on main was re-run on this branch and on `origin/main`, and the outputs
  diffed. Plan checks A, B, D–H and the two World Model sample steps are identical apart from the
  checkout path. Plan check C is identical apart from `execution_time_seconds`.
- Plan check I on the build machine:

  ```
  wall_clock_seconds: 2
  elapsed_seconds: 0.173
  chunks: 5/8
  stop_reason: completed
  status: success; determinable: True; sample_mode: True
  top_cause: logistics_delay (confidence 0.75): Deliveries took longer after hand-off to the carrier: transit time rose in the window.
  token_report: {'standard_estimate': 5730, 'markovian_actual': 4043, 'saving_percent': 29.4}
    chunk 1/8 plan  hypothesis=None queries=['q001'] carryover_step=None projected/budget=1793/12000 actual_sent=8719
    chunk 2/8 round hypothesis=H1 queries=['q002'] carryover_step=explicit_state projected/budget=2181/12000 actual_sent=9041
    chunk 3/8 round hypothesis=H2 queries=['q003'] carryover_step=explicit_state projected/budget=3125/12000 actual_sent=9814
    chunk 4/8 round hypothesis=H3 queries=['q004'] carryover_step=explicit_state projected/budget=4044/12000 actual_sent=11073
    chunk 5/8 round hypothesis=H4 queries=['q005'] carryover_step=explicit_state projected/budget=5018/12000 actual_sent=12057
  [PASS] 5/8 chunks, every chunk input within budget, stop_reason=completed, 0.173 s
  ```

  The change check measured a late share of 0.1007 in the week against 0.0149 in the four weeks
  before. Carrier transit rose from 6.68 to 10.20 days (supported). Deliveries per day fell 59 %,
  so volume was ruled out; single seller and data artefact were ruled out too.

## Known limits

- **`execution_time_seconds` covers the investigation, not data loading.** The local DuckDB sample
  loads in about 2 s on the build machine before the run starts; CI prints the wall clock too.
- **A timed-out worker is abandoned, not killed** (Python cannot stop a thread). After the cancel
  flag is set it makes no new model or data call; a DuckDB call in flight is interrupted, but a
  model call in flight runs until its own timeout (180 s for Meterless). Trace lines from that call can
  appear after the `finish` line. A stub without timeouts, as in the tests, keeps the daemon thread
  until it returns.
- **The compressor deadline needs the real `Generator`.** An injected function without
  `with_limits` is called unbounded, as before (its thread is abandoned on a timeout).
- **The tool-call cap (`MAX_TOOL_CALLS`)**, if hit, stops the rounds with a note and
  `stop_reason: completed`. There is no separate reason for it, and with the defaults (20 queries,
  at most about 15 in 8 chunks) it is not reached.
- **`actual_chars` is larger than the chunk budget** (about 8–12k against 12k projected-input
  budget). It counts the agent system prompts and the source schemas, which are outside the chunk
  input. The budget guarantee is on `projected_chars`.
- **The ranking is a simple rule** until the Critic exists: supported by |effect|, ruled out, open.
- **The World Model is per run and in memory**, so nothing carries across runs. That is by design
  (architecture §5.2: no H-MEM), and the append log is exported to `logs/world-<run>.jsonl`.

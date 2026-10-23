# Sprint 2 — Day 1 end to end: data adapter, model generator + schemas, thin agent loop

Build-plan tasks 3–6, issue #7. The work came in three parts, each committed and pushed on its own
with CI green: A (data adapter), B (generator and schemas), C (agents, loop, `run.py`).

## What was built

### Part A — Local data adapter on DuckDB (task 3)

- `app/data/layer.py`: the `DataLayer` interface (`list_sources`, `describe`, `query`) and the
  shapes a later Zetaris adapter returns unchanged: `SourceInfo`/`TableInfo`/`ColumnInfo`,
  `QueryResult` (query id, source, SQL, adapter, columns, rows, row count, `truncated`, duration)
  and `QueryError` (`code` = `rejected` | `timeout` | `unknown_source` | `failed`, message). A query
  never raises. `QueryLog` writes `logs/queries-<run_id>.jsonl`: query id, source, SQL, adapter,
  duration, row count, truncated, status, error (architecture §8).
- `app/data/local.py`: `LocalDataLayer` loads `data/sample/<source>/*.csv` for `orders`,
  `payments`, `reviews`, `marketing` into one DuckDB database with one schema per source (tables
  named after the CSV), so cross-source SQL reads `orders.orders JOIN payments.order_payments`.
  `query(None, …)` runs cross-source statements; `query("payments", …)` also resolves unqualified
  table names in that source.
- Read-only in three layers: (1) a lexical guard accepts exactly one `SELECT` / `WITH … SELECT`
  (comments and string literals are ignored, so a `;` or `DROP` inside a string is fine) and
  rejects INSERT, UPDATE, DELETE, MERGE, CREATE, DROP, ALTER, TRUNCATE, COPY, ATTACH, DETACH, PRAGMA,
  INSTALL, LOAD, EXPORT, IMPORT, SET, RESET, CALL, transactions, multiple statements and file-reading
  table functions (`read_*`, `glob`, …); (2) DuckDB's parser must classify the statement as SELECT;
  (3) the database is built in a temporary file, then reopened `read_only=True` with
  `enable_external_access=false`, so writes and file reads fail even if the guard is bypassed.
- Row limit (`MAX_QUERY_ROWS`, default 5000) applied in SQL (`LIMIT n+1` around the statement); the
  result says whether it was truncated; a caller can ask for fewer rows, never more. Timeout
  (`QUERY_TIMEOUT_SECONDS`, default 30) enforced with DuckDB's `interrupt()` on a per-query cursor;
  a timed-out query returns `code: "timeout"` and the connection stays usable.
- Query ids are `q001`, `q002`, … per run: unique within the run's log and deterministic, which keeps
  the prompts (and so the sample-mode cache keys) stable.
- The answer key is not reachable: `eval/` is not a source, nothing outside the four folders is
  loaded, and file access is disabled in the engine.
- `app/data/check.py` (`python -m app.data.check`): the plan check.

### Part B — Model generator and result schemas (tasks 4+5)

- `app/schemas.py` (pydantic v2): `Question`, `Plan`, `Hypothesis`, `Observation`, `Verdict`,
  `Result` with the architecture §7 shape (status, question, change, determinable, causes with
  evidence, ruled_out, limitations, agents, trace_id, log_file, token_report,
  execution_time_seconds, plus query_log, sample_mode and error). Each statement in a cause is
  `measured` (must name ≥1 query id) or `inferred`. A result cannot be `determinable: false` and
  assert causes; an error result must carry an error. `json_schemas()` exports the JSON Schema of
  each model; `python -m app.schemas [FILE…]` validates result files. The agents' reply schemas
  (`SqlProposal`, `ObservationDraft`, `ReportDraft`) live in the same module.
- `output_examples/example-result.json`: a hand-written example that validates.
- `app/llm/generator.py`: `Generator` — one callable `generate(messages, *, schema=None, role=…,
  run_id=…) -> GenerationResult`, injected into every agent.
  - Meterless Runtime (Nightshift) primary, to the provider contract in
    `docs/research/meterless-power-prompts-2026-10-19.md`: `normalise_base_url` (with or without
    scheme, `/v1`, `/v1/chat/completions`, `/v1/models`, `/healthz`; never `/v1/v1`);
    `Authorization: Bearer $METERLESS_RUNTIME_TOKEN` on every call, the `rt-local` placeholder refused
    without a call; `meterless-app: explain-why` on every request, `meterless-scope: user` on chat;
    `status()` decides online / unauthorized (401, 403) / offline from `GET /v1/models` and keeps
    unknown `meterless/*` ids; 180 s timeout. Model per role: `METERLESS_MODEL_<ROLE>`, else
    `METERLESS_MODEL`, else Planner/Reporter `meterless/deep`, Investigator/Critic `meterless/fast`.
  - The reply's `meterless.routed_model` and receipt id (`meterless.receipt_id`,
    `meterless.receipt.id` or a `meterless-receipt` header) are recorded in the result and trace.
  - NVIDIA hosted API directly as fallback (`NVIDIA_API_KEY`, `NVIDIA_BASE_URL` defaulting to
    `https://integrate.api.nvidia.com/v1`, `NVIDIA_MODEL`), used only when Meterless is offline
    (connection error or timeout) or its retries are exhausted. `MODEL_PROVIDER=nvidia` selects
    NVIDIA as the only provider.
  - 429/5xx retried after 2 s, 4 s, 8 s (`MAX_RETRIES`, max 3), then fallback.
  - JSON mode: the schema goes into the system message; the reply is parsed (code fences tolerated)
    and validated; one repair call sends the validation error back; a second failure returns
    `error.code = "invalid_json"`. No exception escapes `generate`.
  - `MODEL_TEMPERATURE` (0.2) and `MAX_OUTPUT_TOKENS` (4096) from the environment.
  - Sample mode: replies from `data/sample/llm_cache/<sha256>.json`, keyed by the normalised request
    (messages with whitespace collapsed, schema name, role; not the provider or model). A miss
    returns `error.code = "cache_miss"`, "this question needs a model key …". With
    `RECORD_CACHE=true` in live mode every reply is written to the cache, marked with the provider.
  - Every provider call (and cache lookup) is one line in `logs/trace-<run_id>.jsonl`: provider,
    model requested, model routed, receipt, duration, tokens, status, retry count. Tokens are only
    ever placed in request headers, never in traces or cache files.
- `app/trace.py`: `TraceWriter`, shared by the generator and the agents.
- `scripts/live_check.py`: one real call (Meterless by default, `--provider nvidia` directly) for a
  small schema-validated JSON object; prints status, provider, requested and routed model, receipt
  and the parsed JSON. Skips with a message and exit 0 when the variables are missing. Not in CI.
- `app/llm/check.py` (`python -m app.llm.check`): the plan check.

### Part C — Thin end-to-end slice (task 6)

- Prompts in `app/agents/prompts/*.md` (Planner, Investigator SQL, Investigator observe, Reporter):
  generic method only, no dates, segments or answers. Model input is the system prompt plus one
  `INPUT:` message with canonical JSON (floats rounded to 6 significant digits) so the cache key does
  not change with float noise.
- `app/agents/planner.py`: question + `DataLayer.describe` for every source → `Plan` (metric,
  segment, window, baseline window, change check, 2–4 hypotheses from the §4 families, each with
  its test); ids renumbered H1… by priority.
- `app/agents/investigator.py`: one hypothesis (or the change check) → SQL from the model →
  `DataLayer.query` → rows back to the model → `Observation` whose query id, SQL and sources come
  from the data layer, not the model. A failed statement is repaired once from the error message
  (`repair_sql` in the trace with `retry_count: 1` and the error); a second failure is recorded as a
  limitation.
- `app/agents/reporter.py`: plan + observations → ranked causes. The model names observation ids;
  the code turns them into evidence items with the real query ids. A cause whose ids do not resolve
  is dropped and noted; measured statements without a resolvable query are dropped.
- `app/loop.py`: `run_investigation` — round 1 the Planner and the change check, then the
  Investigator over hypotheses in priority order, then the Reporter. `MAX_AGENT_ROUNDS` (default 6:
  plan + 4 hypotheses + report) and `MAX_TOOL_CALLS` (default 20) cap it; one round is always kept for
  the Reporter. If the Reporter returns `complete: false` with follow-up hypotheses they are
  investigated in further rounds; if it never finishes, the run ends at the round cap with
  `status: "error"`, `error.code: "max_agent_rounds"`. If the change check finds no real change the
  hypotheses are skipped (the "no significant change" branch, minimal for now). Never raises.
- `run.py "<question>" [--sample] [--run-id ID] [--save]`: prints the result JSON; exit 0 on
  success, 1 with a structured error result, 2 for an invalid run id. `--save` writes
  `output_examples/<run_id>.json`; nothing is written there otherwise.
- Trace `logs/trace-<run>.jsonl`, one line per action (timestamp, agent, action, target agent,
  input and output summaries, status, retry count, plus query/observation ids where relevant);
  queries in `logs/queries-<run>.jsonl`. The result's `trace_id`, `log_file` and `query_log` point
  to them.
- `app/llm/stub.py`: `ScriptedModel`, a deterministic stand-in for the model with the generator's
  signature. It handles one generic question shape ("why did order volume change on <date>?"),
  reads the date from the question, compares the day with the seven days before, and tests four
  generic explanations (broad rise across sellers, price drop, single seller, duplicate rows). It
  does not read the answer key.
- `scripts/record_stub_cache.py "<question>"`: runs the real loop with the stub and writes one
  cache entry per model call, each `"recorded_with": "stub"`. The committed cache
  (`data/sample/llm_cache/`, 12 entries) was produced this way for the Day 1 question.
- `scripts/check_result.py RESULT.json`: the plan check verifier (cause, evidence, query ids in the
  query log, trace file).

### Configuration

New settings, all in `.env.example` with safe defaults: `SAMPLE_DATA_DIR`, `MODEL_PROVIDER`,
`METERLESS_RUNTIME_TOKEN`, `METERLESS_MODEL`, `METERLESS_MODEL_{PLANNER,INVESTIGATOR,CRITIC,REPORTER}`,
`NVIDIA_MODEL`, `MODEL_TEMPERATURE`, `MAX_OUTPUT_TOKENS`, `MAX_RETRIES`, `RECORD_CACHE`,
`LLM_CACHE_DIR`, `MAX_AGENT_ROUNDS`, `MAX_TOOL_CALLS`. `METERLESS_API_KEY` and `MODEL_NAME` from
Sprint 1 are kept (the config test pins them) but marked unused.

## Deliberately left out

- Zetaris adapter (task 10), Critic (13), World Model (7–9), Markovian orchestrator (11–12): the
  loop and agents take the generator, the data layer and the trace as injected seams for them.
- Meterless discovery of `/v1/meterless/classes`, Auto Detect over ports, streaming and media
  answer shapes: not needed for text JSON calls.
- An unauthorized Meterless token does not fall back to NVIDIA: the brief says the fallback is used
  only when Meterless is offline or its retries fail, so a wrong token is reported instead of hidden.
- The token report stays at zeros until the Markovian engine exists.
- The "no significant change" and "cannot be determined" branches are minimal (task 14).

## How it was tested

- `ruff check .` → `All checks passed!`; `pytest -q` → `109 passed` (local 25 s on the Pi; CI
  `109 passed in 15.54s`).
- Tests added:
  - `tests/test_data_local.py` (Part A): row counts from `describe()` equal `data/sample/README.md`
    (parsed from the README); column types; cross-source join; source-scoped query; every rejected
    statement type and multi-statement input (guard and adapter); accepted SELECT forms; the
    connection refuses writes without the guard; truncation; limit and timeout from the environment
    and their defaults; a slow cross join interrupted after 1 s; the answer key not loadable
    (no table, `read_json_auto` rejected, direct file path refused by the engine); the query log
    read back with every field; the plan-check script.
  - `tests/test_generator.py` (Part B): URL normalisation for every form; status online /
    unauthorized (401, 403) / offline (connection error, 500, no meterless ids); headers; 180 s
    timeout; `rt-local` refused; role models, temperature and max tokens in the request; valid JSON;
    exactly one repair; structured error on the second failure; 429/503 retry sequence 2-4-8 s;
    retries exhausted → NVIDIA; offline → NVIDIA (recorded in result and trace); unauthorized → no
    fallback; routed model and receipt (three shapes); cache hit without network (fixture cache in
    `tests/fixtures/llm_cache/`); cache key normalisation; cache miss error; recorder → replay; no
    token in trace or cache files; `generate` never raises; `live_check.py` skips without variables.
  - `tests/test_schemas.py` (Part B): example validates; a malformed result fails with a readable
    message (`causes.0.evidence: Field required; …`); measured statements need a query; consistency
    rules; JSON Schema export for all six models; 2–4 hypotheses.
  - `tests/test_loop.py` (Part C): every cause's evidence query id is in the query log with status
    ok; trace fields; a failed SQL repaired once and visible in the trace; SQL failing twice
    reported; a never-finishing Reporter stops at `MAX_AGENT_ROUNDS` with a structured error;
    `MAX_TOOL_CALLS` stops queries; a generator error becomes an error result; the committed cache
    serves every call in sample mode and is marked stub; prompts and agent code contain none of the
    answer key's window dates (ISO, "24 November 2017", "November 2017", "2017-11" forms) or segment
    values; no code under `app/` mentions the answer key; `run.py` exit codes 0 / 1 / 2 and `--save`.
  - `tests/test_run.py` and `tests/test_config.py`: the placeholder expectation
    (`status: not_implemented`, exit 0) was replaced: `run.py "test"` with settings cleared now
    returns a structured `cache_miss` error, exit 1, still in sample mode.
- Plan checks, each a CI step with its output in the log (CI run of commit 3a07fbf):
  - A, `python -m app.data.check`:
    `[PASS] cross-source join orders x payments: 22 monthly rows (query q001, truncated=False)` (the
    monthly table follows) and
    `[PASS] write statement rejected: 'DELETE FROM orders.orders' -> rejected: only SELECT or WITH ... SELECT is allowed, got DELETE`.
  - B, `python -m app.llm.check`:
    `[PASS] generator stub suite (tests/test_generator.py): 40 passed in 0.60s` and
    `[PASS] example-result.json: valid Result (status=success, 1 causes, 2 evidence items)`.
    The live half (`scripts/live_check.py`) is for the build machine; it was not run here (this
    session has no model credentials).
  - C, `SAMPLE_MODE=true python run.py "Why did order volume spike on 24 November 2017?" --run-id ci-day1`
    then `python scripts/check_result.py`: cause 1 `volume` ("The rise is broad: many more sellers
    than usual received orders") with evidence `q002` (distinct sellers per day 383 vs 90) and
    `q001` (orders per day 1176 vs 136.6); cause 2 `price_discount` (average item price 111.75 vs
    135.52); `single_seller` and `data_artefact` ruled out; `trace file: logs/trace-ci-day1.jsonl (36
    lines); query log: logs/queries-ci-day1.jsonl (5 queries)`;
    `[PASS] 2 causes, 4 evidence items, every evidence query in the query log, trace file present`.
    The cache recorded on the Pi (arm64) is hit on CI (x86), so the cache keys are stable across
    machines.

## Known limits

- **The Part C cache is a real recording (replaced the stub on 23 Oct).** The 15 entries in
  `data/sample/llm_cache/` come from a live run through Meterless Nightshift on the build machine
  (`"recorded_with": "meterless"`, each with the routed Nemotron model and a Nightshift receipt id):
  Planner and Reporter on `meterless/deep` → `nemotron-3.5-super-vl-120b-a12b`, Investigator on
  `meterless/fast` → `nemotron-3.5-lightning-30b-a3b`. The slower Nemotron Ultra 550B and Nano Omni
  reasoning models were switched off in Nightshift after they took 70–120 s per call and returned
  HTTP 502s. Re-record with
  `SAMPLE_MODE=false RECORD_CACHE=true METERLESS_RUNTIME_TOKEN=… python run.py "Why did order volume spike on 24 November 2017?"`.
- **The Day 1 answer is weak, by design of this thin slice.** The real driver of 24 Nov 2017 is
  Black Friday, a market-wide calendar event; with no Critic and no calendar hypothesis yet, the
  model settles on a small product-mix shift and one seller. The Critic (task 13) and prompt tuning
  from the evaluation (task 16) are where this is meant to improve.
- **Fixes made while recording (23 Oct, session):** (1) a failed model call is now noted as
  `"<target>: model call failed"` without the transient error text, so later prompts (and cache
  keys) do not depend on whether a live run saw a 502; (2) when the round cap is hit while the
  Reporter already has causes, the run returns them marked incomplete instead of an error;
  (3) DuckDB defaults to one thread, because rows that tie in an `ORDER BY … LIMIT` came back in a
  different order across runs and broke replay; (4) `MAX_OUTPUT_TOKENS` defaults to 4096, because
  2048 cut the Planner's JSON off on Nemotron Lightning.
- **Recorded query results (23 Oct, after Nikolay's test on macOS failed).** One query asked for the
  top 20 sellers while about 15 tie at 20th place; which of them DuckDB returns differs between
  platforms (and thread counts), so on his Mac the model saw different rows and the cache missed.
  Now a recording run (`RECORD_CACHE=true`, live) also saves each successful query's rows to
  `data/sample/query_cache/<sha256>.json` (key: source, whitespace-normalised SQL, limit), and sample
  mode serves those rows. The query still runs for real (guard, timeout and errors apply); only the
  rows are swapped, and the query log marks it `"replayed": true`. Verified by replaying with 1–4
  DuckDB threads, where the raw query returns a different set of sellers.
- Any change to a prompt, a reply schema or the data changes the cache keys; sample mode then
  returns `cache_miss` until the cache is re-recorded.
- The baseline is the seven days before the date (136.6 orders per day, weekend included), so the
  numbers differ from the detectability report's 20–23 November average.
- The guard is conservative: an identifier spelled exactly like a forbidden keyword (a column named
  `set`, `load`, …) is rejected; none exist in the sample.
- Re-running `run.py` with the same `--run-id` appends to the existing trace and query log files
  (they are append-only); use a fresh id for a clean log.
- The whole sample is loaded at start (about 1.2 s on the Pi), once per run.
- `scripts/live_check.py` and the recorder path (`RECORD_CACHE=true`) have only been tested with a
  stubbed transport.

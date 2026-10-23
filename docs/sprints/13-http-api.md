# Sprint 13 — HTTP API: POST /run, GET /runs/{id}, GET /runs/{id}/trace

Build-plan task 18, issue #18. A FastAPI app over the existing investigation loop (architecture §7
and §8), with no second implementation of the loop.

## What was built

- `app/runner.py`: the one shared helper. `execute_run(question, *, run_id, settings)` opens
  `LocalDataLayer` and calls `app.loop.run_investigation` with `Generator(settings)`, exactly the
  wiring `run.py` had. `run.py` and `POST /run` both call it. `RUN_ID_RE` moved here
  (`run.py` imports it, so its command-line check is unchanged); `valid_run_id` adds the
  "no `..`" rule for the API; `new_run_id` is the same id format as before.
- `logs/result-<run_id>.json`: the loop writes the final result next to the trace, through
  `TraceWriter.write_result` (atomic replace, so a reader never sees half a file). `run.py` runs get
  one too. A result file that cannot be written does not fail the run; the run is then `not_found`
  to `GET /runs/{id}`. Prompts, agents and anything the model sees are unchanged, so the recorded
  sample-mode cache still matches.
- `app/api/main.py` (start: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`, or
  `python -m app.api`, which reads `API_HOST` / `API_PORT`):
  - `POST /run` — body `{"run_id": "<optional>", "input": {"query": "..."}, "options": {"sample_mode": true|false}}`.
    `options.sample_mode` absent means `SAMPLE_MODE` from the environment. Returns the result JSON
    (§7 shape) with 200. A result with `status: error` that is a normal end of a run (for example
    `max_agent_rounds`) is also returned with 200; `cache_miss` and `internal` are mapped as below.
  - `GET /runs/{id}` — the stored result, validated with `validate_result_file` before it is served.
  - `GET /runs/{id}/trace` — `logs/trace-<id>.jsonl` as `application/x-ndjson` (also while the run
    is still going).
  - `GET /health` — `{"status": "ok", "sample_mode": <bool>}`; reads settings only.
- One error shape everywhere, including unknown routes: `{"error": {"code", "message", "run_id"}}`.

  | code | HTTP | when |
  |---|---|---|
  | `invalid_input` | 422 | body fails validation: missing/empty/blank query, query over 1,000 characters, bad `run_id`, unknown fields (e.g. `anomaly_id`), malformed JSON |
  | `invalid_input` | 400 | `/runs/{id}` with an id that fails the run-id rule (`a..b`, `.x`, 65 characters) |
  | `not_found` | 404 | no stored result / trace for the id; also unknown routes and ids with `/` (`/runs/../etc`, `/runs/a%2Fb` do not match the route) |
  | `run_failed` | 500 | the run raised, the loop ended with `internal`, or the API layer raised; the message names the exception type only (no stack trace, no exception text, which may hold URLs or tokens); details go to the server log |
  | `cache_miss` | 409 | sample mode and no recorded model reply for this question (§10); the result is still stored |
  | `busy` | 429 | a run is already in progress |
  | `timeout` | 504 | the run passed `API_RUN_TIMEOUT_SECONDS` (default 600) |
  | `method_not_allowed` | 405 | e.g. `GET /run` |

- One run at a time: a process-wide lock taken without waiting; a second `POST /run` gets `busy`
  at once. The run works in a background thread; the request waits for it up to
  `API_RUN_TIMEOUT_SECONDS`. A Python thread cannot be killed, so a timed-out run finishes in the
  background, still holding the lock (memory stays capped at one DuckDB instance), and its result
  appears at `GET /runs/{id}` when it ends. It does end: rounds, tool calls, each model call and each
  query are already capped and timed.
- Path safety: an id becomes a file name only after the run-id check
  (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, no `..`), and the resolved path must sit directly in
  `LOG_DIR`.
- Settings: `API_HOST` (0.0.0.0), `API_PORT` (8000), `API_RUN_TIMEOUT_SECONDS` (600), in
  `app/config.py` and `.env.example`.

## Left out

- `GET /anomalies` and the `{anomaly_id}` input: the anomaly scanner (PR #10) is not merged. An
  `anomaly_id` today is rejected as `invalid_input`.
- `GET /runs/{id}/events` (live trace stream).
- The web page: build-plan task 19.

## How it was tested

- `tests/test_api.py` (47 tests, FastAPI `TestClient`, sample mode, no network): the Day-1 run
  returns 200 with a valid result and writes `trace-` and `result-` files; `GET /runs/{id}` returns
  the same body; the trace endpoint returns the trace lines as NDJSON; unknown id → 404; eleven
  traversal-style ids → 400/404 with no file opened (checked with a spy on `Path.is_file` /
  `read_bytes`); every error code above, the lock (second run → 429 at once, lock free afterwards),
  the timeout (patched 0.2 s, stub run, the late run still holds the lock until it ends), the
  `sample_mode` option against the environment, `python -m app.api` binding from `API_HOST` /
  `API_PORT`, and `/health` with the settings variables cleared and `socket.connect` patched to fail.
- Same code path: a test runs `run.main([...,"--sample"])` and `POST /run` on the Day-1 question and
  asserts the results are equal apart from `run_id`, `trace_id`, `log_file`, `query_log` and
  `execution_time_seconds`, and that the API went through `app.runner.execute_run`.
- Full suite: `pytest -q` — 161 passed; `ruff check .` clean.
- Plan check D in CI: starts `python -m app.api` with `SAMPLE_MODE=true`, waits for `/health`
  (30 s cap), `curl -sS -X POST localhost:8000/run -H 'Content-Type: application/json' -d
  '{"input":{"query":"Why did order volume spike on 24 November 2017?"},"options":{"sample_mode":true}}'`,
  prints the response, validates it with `python -m app.schemas` and `scripts/check_result.py`,
  checks `GET /runs/<id>` equals the response, prints the first trace lines and the server log, and
  stops the server. Local run of the same script (port 8765, port 8000 was taken on the build
  machine):

  ```text
  {"status":"ok","sample_mode":true}
  {"run_id":"run-20261023T223138Z-d3ad05","status":"success","question":"Why did order volume spike on 24 November 2017?", ...}
  [PASS] api-result.json: valid Result (status=success, 2 causes, 2 evidence items)
  cause 1 [mix_shift, confidence 0.75]: Product mix shifted toward higher-frequency categories on 24 Nov 2017.
  cause 2 [single_seller, confidence 0.6]: A single seller generated a disproportionate number of orders on 24 Nov 2017.
  [PASS] 2 causes, 2 evidence items, every evidence query in the query log, trace file present
  [PASS] GET /runs/run-20261023T223138Z-d3ad05 returns the POST /run result
  --- GET /runs/run-20261023T223138Z-d3ad05/trace: 41 lines, first 2 ---
  ```

## Known limits

- One run at a time per process, no queue; a timed-out run keeps the API `busy` until it ends.
- Results and traces live on disk under `LOG_DIR` (no database); there is no listing of runs and no
  clean-up. Re-using a `run_id` appends to its trace and replaces its stored result.
- Run in a single uvicorn worker: the lock is per process, so several workers would allow several
  runs at once.
- No authentication (none in the brief); bind to 127.0.0.1 with `API_HOST` where that matters.

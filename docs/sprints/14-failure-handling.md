# Sprint 14 — Failure handling and sample mode from a clean clone

Build-plan task 20 (Day 4), issue #29. Most of the retry and fallback code was already on main
(090da6b). This sprint audited it against architecture §4 (Retry and fallback), §6, §8 and §10,
added the missing tests, and fixed only the gaps the audit found.

## What was built

Gaps found on main and fixed:

- **Model attempt cap** (`app/llm/generator.py`). On main, one `generate` call could send 4 requests
  to Meterless (`MAX_RETRIES=3`) and 4 more to NVIDIA, and twice that with the JSON repair call.
  `MAX_MODEL_ATTEMPTS = 3` now caps the HTTP requests of one `generate` call (one agent step).
  Retries, the NVIDIA fallback and the repair call all count against it. When the fallback is
  configured, Meterless leaves one of the three for it: two Meterless attempts (one retry after
  2 s), then NVIDIA. Without a fallback, Meterless may use all three (retries after 2 s and 4 s). If
  no attempt is left for a repair call, the result is `invalid_json` with a message naming the cap.
  `MAX_RETRIES` still applies on top (0–3). `with_limits` (the carryover compressor) is unchanged:
  no retries, deadline-bounded.
- **Trace lines for model calls** now carry `model`, `attempt` (requests sent so far in this step)
  and, on the fallback provider's line, `fallback_reason` (for example
  `retries_exhausted: meterless returned HTTP 503 after 1 retries`), next to the existing
  `provider`, `model_requested`, `model_routed`, `retry_count` and `fallback`. Cache lines in
  sample mode are unchanged.
- **`METERLESS_API_KEY`** was ignored on main. `Settings.meterless_token` returns
  `METERLESS_RUNTIME_TOKEN`, or `METERLESS_API_KEY` when the first is empty; the generator and
  `scripts/live_check.py` use it. `.env.example` documents the alias.
- **Zetaris fallback in the trace and the result.** On main, the fallback was recorded in the query
  log (`adapter`, `fallback_reason`) but not in the trace or the result. Now:
  - `QueryResult` / `QueryError` have an optional `fallback_reason` (`app/data/layer.py`).
  - `ZetarisDataLayer` sets it and keeps a list of `fallbacks` (query ids, and `describe <source>`
    for schema reads).
  - The Investigator writes a `data_fallback` trace line for each fallback query, and every
    `run_query` line now names the `adapter`.
  - `app/runner.py` adds a `Data adapter: …` limitation to the result that names
    `local (fallback from zetaris)`, the calls it answered and the first reason, then rewrites
    `logs/result-<id>.json`. Both loops go through the runner, so `app/engines/markovian/` was not
    touched.
- **Carry-overs.**
  - `POST /run` with a `run_id` whose trace, result or query log already exists answers 409
    `run_id_taken` in the standard error shape and writes nothing (PR #19 should_fix).
  - A bad `LOOP` setting answers 400 `invalid_input` before the run lock is taken. On main it was
    500 `run_failed` (Sprint 8 nit).
  - `run.py` already answered `LOOP=chunky` with `bad_loop` JSON and exit code 2, and argparse
    already refused `--loop chunky` with exit code 2. Both are now tested.
  - `record.err`, `result.json` and `result-live.json` are removed from the root, and `.gitignore`
    covers `/result.json`, `/result-*.json` and `/record.err` at the root only.
- **`scripts/clean_clone_check.sh`.** Runs three questions in sample mode, each through `env -i`
  (only `PATH`, `HOME` and `SAMPLE_MODE=true`), so no shell variable or credential leaks in. The app
  never reads `.env` itself.
  - (a) the Day 1 question with `--loop simple`, checked with `scripts/check_result.py`
  - (b) the plan check J question with the default loop, checked with
    `scripts/check_markovian_run.py`
  - (c) "Why did review scores fall in March 2018?", which has no recording and must return the
    structured `cache_miss` error

  The script prints one line per question and exits 1 if any check fails. Every command runs under a
  timeout (`CLEAN_CLONE_TIMEOUT_SECONDS`, default 300 s per run), enforced by `timeout`, `gtimeout`
  or `perl -e alarm` on a Mac without coreutils.
- **macOS fix after the owner's Mac test (revision 2).** On an Apple Silicon Mac with a universal2
  Python 3.14, all three runs crashed at import: under `env -i` the venv's interpreter started as
  x86_64 (Rosetta) while the installed wheels (`pydantic_core`) are arm64. `pytest` in the same venv
  passed, so the venv was fine. On Darwin the script now asks the interpreter for its CPU as it starts
  normally (`"$PY" -c 'import platform; print(platform.machine())'`, without `env -i`) and, for
  `arm64` or `x86_64`, runs every command as `arch -<cpu> env -i … ARCHPREFERENCE=<cpu> arch -<cpu>
  python …`: `arch` before `env -i` as asked, and again right before the interpreter, so the CPU is
  pinned whether or not `env` passes it on. Any other answer leaves the prefix as before. Linux and CI
  are unchanged (the prefix there is still `env -i PATH=… HOME=… PYTHONUTF8=1 SAMPLE_MODE=true`).
  `CLEAN_CLONE_PRINT_PREFIX=1` prints the prefix and exits, for the tests.
- **Second merge of origin/main (0ae9313, Sprint 10b).** The only conflict was in `ci.yml`: main's
  Plan check N steps and the `clean-clone` job are both kept. Main's new `tests/test_ci_labels.py`
  allows each plan check letter on only one step, so the two setup steps of the `clean-clone` job are
  now named "Clean clone (for plan check M): …". The run step is the one step left named "Plan check M
  (task 20)", and the commands are unchanged.
- **Plan check M** (`.github/workflows/ci.yml`, job `clean-clone`). The branch is checked out into a
  fresh directory (`clean-clone/`) and given an empty `.env`. The venv is created inside the tree by
  a `python:3.11-slim` container, with the network on for pip only. The run step then runs
  `scripts/clean_clone_check.sh` in the same image with `docker run --network none`. It is the
  preferred variant from the issue, not the socket-guard fallback. The step first checks that an
  outside connection really fails inside the container, and prints the script's three lines and
  its exit code. It is a separate job, so the 10-minute limit of the existing `test` job is
  unaffected.

## Left out

- Retrying a model timeout on the same provider. The Meterless timeout is 180 s, so a second try
  could take six minutes. A timeout goes straight to the fallback (as main documents, `FALLBACK_CODES`),
  and without a fallback it is a structured `timeout` error.
- A circuit breaker for Zetaris. When Zetaris is down, every call still tries once and retries once
  (`ZETARIS_RETRY_DELAY_SECONDS`, default 1 s) before using local data. The four schema reads and
  each query pay that cost.
- `run.py` does not refuse a reused `--run-id`. The issue asks for this on `POST /run` only, and CI
  and local habits rerun fixed ids such as `ci-day1`.

## Audit: every failure, its handler, what is recorded, and the test

All tests are under `tests/`. `tfh` is `test_failure_handling.py`.

| Failure | Handled by (on main unless marked new) | Trace records | Query log records | Covered by |
|---|---|---|---|---|
| Query syntax error | `app/data/local.py:LocalDataLayer.query` returns `QueryError(code="failed")`; `app/agents/investigator.py:investigate` repairs once (`MAX_SQL_REPAIRS = 1`, action `repair_sql`); a second failure becomes the outcome "query failed after repair", and the run goes on | `write_sql`, `run_query` (status `failed`, retry 0), `repair_sql` with `previous_error`, `run_query` (retry 1) | both attempts, `status`, `error`, same `query_id` sequence | `tfh::test_first_query_fails_second_is_accepted_after_exactly_one_repair`, `tfh::test_query_failing_twice_is_an_outcome_and_the_run_still_returns_a_result`, `test_loop.py::test_failed_sql_is_repaired_once_and_traced` |
| Unknown column | same path (DuckDB Binder Error → `failed`); through Zetaris a 4xx is `ZetarisRequestError` → `failed`, no fallback (`app/data/zetaris.py:ZetarisDataLayer.query`) | as above | as above | the same `tfh` tests (Binder Error case), `test_loop.py::test_sql_failing_twice_is_reported_not_retried_again`, `test_data_zetaris.py::test_sql_error_is_not_an_outage` |
| Query timeout | local: `LocalDataLayer.query` interrupts at `QUERY_TIMEOUT_SECONDS` → `QueryError(code="timeout")`, then the repair path above; Zetaris: `ZetarisClient._send` → `ZetarisUnavailable(timeout=True)` → retry once → local fallback | `run_query` status `timeout`, then `repair_sql`; for Zetaris the `data_fallback` line (new) | `status: timeout` / Zetaris: `adapter: local (fallback from zetaris)`, `fallback_reason` | `tfh` repair tests (timeout case), `test_data_local.py::test_timeout_interrupts_slow_query`, `test_data_zetaris.py::test_outage_retries_once_then_falls_back_to_local[timeout]` |
| Zetaris connect error | `ZetarisClient._send` → `ZetarisUnavailable`; `ZetarisDataLayer._run_with_retry` (one retry) → `query` / `describe` fall back to local; `app/runner.py:_mark_data_fallback` (new) names the adapter in the result | `data_fallback` per query with `adapter`, `fallback_reason` (new); `run_query` names the `adapter` (new) | `adapter: local (fallback from zetaris)`, `fallback_reason` | `tfh::test_zetaris_connect_error_run_completes_on_the_local_adapter[simple/markovian]`, `test_data_zetaris.py::test_outage_retries_once_then_falls_back_to_local[connect]`, `::test_describe_falls_back_to_local_when_zetaris_is_down` |
| Zetaris 5xx | same as connect error | same | same | `test_data_zetaris.py::test_outage_retries_once_then_falls_back_to_local[5xx]`, `::test_one_failure_then_success_stays_on_zetaris` |
| Zetaris auth refused | `ZetarisClient.run_sql`: a refused key falls back to login (`GET /auth/login`); if that is refused too, `ZetarisAuthError` → `QueryError(code="failed")`, no data fallback (refused credentials are reported, not hidden) | `run_query` status `failed` with "refused the credentials", then `repair_sql` | `status: failed`, `adapter: zetaris`, credentials redacted | `test_data_zetaris.py::test_refused_api_key_falls_back_to_login`, `::test_refused_credentials_are_reported_not_hidden_by_fallback`, `::test_no_credential_reaches_results_or_logs` |
| Model timeout | `app/llm/generator.py:OpenAICompatibleProvider.chat` → `ProviderError("timeout")`; `Generator._complete` falls back to NVIDIA (`FALLBACK_CODES`); without a fallback, a structured `timeout` | `model_call` per provider: `provider`, `model`, `attempt`, `status: timeout`; fallback line with `fallback_reason` (new fields) | — | `tfh::test_timeout_then_the_next_attempt_succeeds`, `tfh::test_never_more_than_three_model_attempts_per_agent_step[timeouts everywhere]`, `test_markovian_review_fixes.py::test_compression_timeout_leaves_no_thread_running` |
| Model 5xx | `chat` retries after `RETRY_DELAYS_SECONDS` (2, 4, 8 s), capped by `MAX_RETRIES` and `MAX_MODEL_ATTEMPTS` (new); then `retries_exhausted` → NVIDIA fallback | as above, `retry_count`; fallback line `fallback_reason: retries_exhausted: …` | — | `tfh::test_5xx_then_retry_then_success_on_the_same_provider`, `tfh::test_5xx_until_retries_are_exhausted_then_nvidia_with_fallback_reason`, `tfh::test_fallback_not_configured_gives_a_structured_error`, `test_generator.py::test_retries_exhausted_falls_back_to_nvidia` |
| Model 429 | same as 5xx | same | — | `test_generator.py::test_429_retry_sequence_then_success`, `tfh::test_never_more_than_three_model_attempts_per_agent_step[429 …]` |
| Model 401 | `chat` → `ProviderError("unauthorized")`, no retry; not in `FALLBACK_CODES`, so no fallback: a structured `unauthorized` error (main documents "reported, not silently bypassed") | one `model_call` line, `status: unauthorized`, `attempt: 1` | — | `tfh::test_401_is_not_retried_and_not_bypassed`, `tfh::test_401_from_nvidia_as_primary_is_a_structured_error`, `test_generator.py::test_unauthorized_meterless_does_not_fall_back` |
| Empty reply | `Generator.__call__`: `parse_json_reply` → "no JSON object" → one repair call → `invalid_json` | `model_call`, then `model_repair_call` | — | `tfh::test_empty_reply_is_repaired_once_then_a_structured_error` |
| Invalid JSON | same; a repair with no attempt left is `invalid_json` naming the cap (new) | `model_call`, `model_repair_call` | — | `test_generator.py::test_invalid_json_triggers_exactly_one_repair`, `::test_second_invalid_reply_returns_structured_error`, `tfh::test_no_attempt_left_for_the_repair_call_is_a_structured_error` |
| Cache miss in sample mode | `Generator._complete` (sample branch) → `{"code": "cache_miss", "message": CACHE_MISS_MESSAGE}`; the Planner's miss ends the run with that error (`app/loop.py`, orchestrator); `run.py` exits 1 with the JSON; `POST /run` answers 409 `cache_miss` | `model_call` with `provider: cache`, `status: cache_miss`; `finish` with the error | no queries (the Planner is first) | `tfh::test_sample_mode_cache_miss_is_the_structured_error[simple/markovian]`, `tfh::test_sample_mode_cache_miss_over_the_api`, `test_generator.py::test_cache_miss_returns_structured_error`, `test_api.py::test_sample_mode_cache_miss_is_409` |

How an agent reports a failed model call: the Planner's or Reporter's error ends the run as a
structured error `Result` with that code. The Investigator's error becomes "Not tested: H…: model
call failed" in `limitations`, and the run goes on. No exception reaches the caller: `generate` never
raises, and both loops catch the rest as `internal`.

Caps and timeouts (criterion 7, `tfh::test_retry_and_fallback_caps_are_fixed`,
`tfh::test_every_external_call_keeps_its_timeout`):

- `MAX_MODEL_ATTEMPTS = 3` per step
- `RETRY_DELAYS_SECONDS = (2, 4, 8)`, `MAX_RETRIES` 0–3
- `MAX_SQL_REPAIRS = 1`
- one Zetaris retry, `ZETARIS_RETRY_DELAY_SECONDS` 0–30
- Meterless 180 s, NVIDIA `MODEL_TIMEOUT_SECONDS`, Zetaris `QUERY_TIMEOUT_SECONDS` with a connect
  timeout of at most 10 s
- every `run.py` call in `clean_clone_check.sh` runs under `with_timeout`

The round, tool-call, chunk and run caps are tested in earlier sprints.

## How it was tested

- `tests/test_failure_handling.py`: 54 tests, one section per acceptance criterion, plus three for
  the macOS prefix of `clean_clone_check.sh` (a fake `uname` and interpreter: Darwin arm64, Darwin
  x86_64 and an unknown answer, and Linux unchanged). Sample-mode tests
  use a `no_network` fixture that makes `socket.connect`, `connect_ex` and `getaddrinfo` raise for
  any non-loopback address, and they assert it blocked nothing. The end-to-end runs (Day 1 on the
  simple loop, the plan check J question on the default loop) run both with an empty environment
  and with live-looking credentials and hosts set: sample mode tries none of them.
- Three existing tests pinned the old uncapped retry counts. They now pin the cap:
  - `test_generator.py::test_429_retry_sequence_then_success`: no fallback configured, 2 retries
  - `::test_retries_exhausted_falls_back_to_nvidia`: 2 Meterless attempts, then NVIDIA
  - `test_markovian_review_fixes.py::test_unbounded_generator_still_retries`: 3 requests
- After merging origin/main (Sprints 8b streaming, 9+10 Critic, 11 eval, 13b web page):
  - `test_generator_streaming.py::test_error_events_exhaust_retries_then_fall_back_to_buffered_nvidia`
    pinned 4 streamed Meterless requests before the fallback; it now pins the cap (1 retry, 3
    requests in all, `attempt` 3 and `fallback_reason` on the NVIDIA line).
  - New `::test_bounded_streamed_calls_keep_the_attempt_cap_and_trace_fields`: the same through
    `with_limits` (the `run_by_deadline` worker), so the cap and trace fields hold for bounded
    streamed calls too.
  - `test_eval_run.py` compared incident-01 with the root `result.json`; that file (unchanged) is
    now `tests/fixtures/day1-sample-result.json` and the test reads it there.
- `pytest -q` under `systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0`: 705 passed
  (650 on origin/main 457cde2: 54 in `test_failure_handling.py`, 1 new streaming test), about
  5 minutes on the Pi.
- Every step of the existing `test` job was rerun locally and passes: A, B, C, D (Zetaris and task 7),
  E, F, G, H, I (a live server on a spare port, including a `run_id_taken` answer for a reused id),
  J, both L steps (the eval prints the same `Score: 0/10 (answered 1, no_cache 9, errors 0)` as
  origin/main; the Critic checks all pass), and the World Model ingest and context. The results of C
  and J are identical to origin/main's
  apart from `execution_time_seconds`. Plan check C's three printed trace
  lines are identical; later `run_query` lines gain `"adapter": "local"`.
- `scripts/clean_clone_check.sh` from a fresh `git clone` with an empty `.env`, run inside
  `unshare -rn` (a network namespace with no outside route, so `connect` to 1.1.1.1 fails with
  "Network is unreachable"):

  ```text
  [PASS] Why did order volume spike on 24 November 2017? | success | determinable=true | top cause=mix_shift
  [PASS] Why did delivery lateness spike for deliveries completed the week of 28 May 2018? | success | determinable=true | top cause=logistics_delay
  [PASS] Why did review scores fall in March 2018? | error cache_miss | determinable=false | top cause=none
  clean clone check: PASS (3 of 3)
  ```

  Exit code 0, 6 s. With `CLEAN_CLONE_TIMEOUT_SECONDS=0.05` every line is `[FAIL] … (exit 124,
  timed out)`, and the script exits 1.
- Revision 2 (macOS prefix): the Pi has no Mac, so the Darwin branch was run end to end with a fake
  `uname` (prints `Darwin`), a fake `arch` (logs its arguments and runs the rest) and a wrapper
  interpreter that reports `arm64`: the same three `[PASS]` lines, exit code 0, and every one of the
  eight commands logged as `arch -arm64 env -i … ARCHPREFERENCE=arm64 arch -arm64 …/py …`. On the
  real Linux path the output is unchanged. The fix itself is confirmed only by a run on the Mac.

## Known limits

- **Recorded answers made with the stub.** The plan check J question (delivery lateness, week of
  28 May 2018) has 12 cache entries, all `recorded_with: stub`, written by the scripted model in
  `app/llm/stub.py`. Its sample-mode answer shows that the agents, queries and orchestrator run.
  It is not a real model's reasoning. The Day 1 question's 15 entries are `recorded_with: meterless`
  (real Nemotron replies through Nightshift). Check before quoting an answer:

  ```sh
  grep -l '"recorded_with": "stub"' data/sample/llm_cache/*.json
  ```

- **The NVIDIA fallback does not count for the Nemotron award.** It calls NVIDIA's hosted API
  directly, and the award counts Nemotron only when it runs through Nightshift (architecture §6).
  A run that used it says so in the trace (`provider: nvidia`, `fallback_reason`). The demo and
  README use Nightshift.
- Plan check M was not run locally in Docker: the build host has no `python:3.11-slim` image, and
  the check was not worth pulling one onto a shared daemon. The same script was run offline with
  `unshare -rn` instead, as above. The CI log of the `clean-clone` job is the evidence for the
  Docker variant.
- The Zetaris fallback note is added by `app/runner.py`, so it appears for `run.py` and
  `POST /run`, the two entry points. A caller that runs `run_investigation` or `run_markovian`
  directly gets only the trace and query-log lines.

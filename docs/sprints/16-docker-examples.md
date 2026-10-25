# Sprint 16 — Dockerfile and three examples with outputs and traces

Build-plan tasks 21 and 22, issue #39. Built on main 0373065 (after #30, #32, #34, #37, #38). No code
under `app/`, no prompt and no recorded cache changed, so every committed cache entry still replays.

## What was built

**Docker (task 21)**

- `Dockerfile` at the repository root: `python:3.11-slim` (the CI Python version), CPU only.
  `requirements.txt` is copied and installed first (its own layer), then the tree. The image runs as
  a normal user (`app`, uid 10001); `logs/` and `.cache/duckdb` are created and owned by it. DuckDB
  keeps the app caps: `DUCKDB_MEMORY_LIMIT` 2GB, `DUCKDB_THREADS` 1, and `DUCKDB_WORK_DIR`
  `.cache/duckdb`, which resolves to `/app/.cache/duckdb` on the container's disk, not `/tmp`. The
  Dockerfile sets no `DUCKDB_*` value, so the defaults in `app/config.py` apply and `docker run -e`
  overrides them. No `ARG`; the only `ENV` values are Python and pip switches.
  `CMD ["python", "-m", "app.api"]` binds `API_HOST` (0.0.0.0) on `API_PORT` (8000); it installs and
  downloads nothing. A `HEALTHCHECK` calls `GET /health` with Python's `urllib` (no curl in the slim image).
- `.dockerignore`: `.git`, `.github`, `.venv`, `venv`, `.env`, `.cache/`, `logs/*` with `!logs/.gitkeep`,
  `__pycache__`, compiled files, tool caches, `browser-check.png` and ad-hoc `result*.json` at the
  root. `data/sample/` (with `llm_cache/` and `query_cache/`), `eval/answer_key.json` and
  `.env.example` stay in the image.
- `.env.example`: the `SAMPLE_MODE` comment now says what sample mode is (the real agent logic on the
  local sample, each model call answered by its recorded reply) and that the organisers accepted it
  if it is highlighted. Commented Docker variants under `METERLESS_BASE_URL`
  (`http://host.docker.internal:8088/v1`) and `ZETARIS_URL`
  (`http://host.docker.internal:8888/api/v1.0`), with when to use them and the Linux
  `--add-host=host.docker.internal:host-gateway` flag. No variable renamed, no active value changed.
- README "Docker" section: build, run and curl commands, the expected answer, full mode with
  `--env-file .env`. `metadata.json` `entrypoints.docker` is the build-and-run command.

**Examples (task 22)**

| Example | Answer-key incident | Loop | Result | Cache entries replayed |
|---|---|---|---|---|
| `example_1` | incident-01, the Day 1 question | markovian | success, rank-1 `volume`; `single_seller` and `data_artefact` ruled out | 19 stub, 0 meterless |
| `example_2` | incident-06, the review-score dip | markovian | success, `product_quality`; the Critic refutes `logistics_delay` | 16 stub, 0 meterless |
| `example_3` | incident-09, a seller's review-score drop | markovian | success, determinable false, no cause (3 records in the window, minimum 30) | 7 stub, 0 meterless |

- The Markovian loop is used for all three because the cache on main holds that loop's replies for
  these questions (decision D-e630b8: Markovian 01/02/06/09/10/no-change plus simple-loop Day 1). It is
  also the API's default, so `POST /run` in the container replays the same entries.
- `input_examples/example_N.json`: `POST /run` bodies, `{"input": {"query": ...}, "options":
  {"sample_mode": true}}`, with the question copied verbatim from `eval/answer_key.json`. No `run_id`,
  so posting the same file twice does not get `409 run_id_taken`.
- `output_examples/example_N.json` (the result) and `output_examples/example_N.trace.jsonl` (its
  trace, `model_requested`, `model_routed` and `recorded_with` on each `model_call` line) are the
  files the app wrote to `logs/` through `app.runner.execute_run`, run id `example_N`, copied as they
  are.
- `output_examples/example_N.meta.json`: input file, incident, loop, number of model calls, the
  replayed cache entries by `recorded_with` (`stub`, `meterless`, `other`), the requested and routed
  models, and a one-line note. Today every entry is stub-recorded, and the note says the output shows
  the agent logic, not a model's answer. The counts live in a separate file because `Result` forbids
  extra fields and the outputs must stay what the app wrote.
- `scripts/make_examples.py`: one command regenerates all three inputs, outputs, traces and meta
  files, in sample mode, with no network. It first drops from its environment every variable named in
  `.env.example`, every `Settings` field name (e.g. `QUERY_CACHE_DIR`, in any case) and every
  `MARKOVIAN_*` variable (so a local `.env` or shell setting cannot change the outputs) and deletes its own
  `logs/*-example_N.*` files from earlier runs (a reused run id would append to the old trace). A file
  whose new content differs only in timestamps and durations is left untouched, so on an unchanged
  cache `git status` stays clean. After the coordinator commits the re-recorded Nightshift caches,
  rerunning it refreshes the outputs and the meta counts show the meterless entries.
- `output_examples/example-result.json` is kept. It is not a copy of example 1: it is the
  hand-written schema example from Sprint 2 that `python -m app.schemas` and `tests/test_schemas.py`
  read.

## Left out

- No push to a container registry; the image is built locally (or in CI).
- No docker-compose file for the app. Nightshift and Zetaris are reached from the container through
  `host.docker.internal`; the image does not run them.
- Docker was never built or run on the build machine (memory limit); it runs only in GitHub Actions.

## How it was tested

- `tests/test_examples.py` (44 tests, run by CI's `pytest -q` step): the three triples and meta files
  exist; inputs validate against the API's own `RunRequest` and carry the answer-key questions
  verbatim; outputs are schema-valid sample-mode successes; example 2's trace has a refuted Critic
  verdict and `logistics_delay` in `ruled_out`; example 3 has determinable false, no cause and a
  "Cannot be determined" summary; each trace names the requested and routed model on every model
  call; the meta counts equal the counts recomputed from the trace; `make_examples.py` run into a
  temp folder, with `QUERY_CACHE_DIR`, `loop`, `SAMPLE_MODE` and a `MARKOVIAN_*` variable set to other
  values in its environment, reproduces the committed files after normalising timestamps, durations
  and the log folder path; `clean_environment` drops those variables and keeps unrelated ones; no `nvapi-`, `sk-` key, bearer token, `@gmail` or IPv4 other than 127.0.0.1/0.0.0.0 in
  the Dockerfile, `.dockerignore`, `.env.example`, `input_examples/` or `output_examples/`; the
  Dockerfile base equals CI's Python version, dependencies come from `requirements.txt` at build time,
  the start command is `python -m app.api`, no `ARG` and no secret `ENV`; `.dockerignore` keeps
  `.env`, `.git`, `logs/*` and caches out and `data/sample/`, `eval/answer_key.json` in; the Docker
  variants in `.env.example`; and the shape of the new workflow.
- `tests/test_docs.py`: the Docker-section test now checks the commands and `entrypoints.docker`
  instead of the Sprint 15 placeholder.
- Local: full `pytest -q` 897 passed; `ruff check .` clean; `python scripts/make_examples.py` run
  twice in a row leaves `output_examples/` byte-identical.
- Plan check P, `.github/workflows/docker-check.yml` (job `docker-check`, 15-minute limit): fresh
  checkout with no `.env`, `docker build -t explain-why-agent .`, `docker run -d -p 8000:8000 -e
  SAMPLE_MODE=true` (no `--env-file`), `GET /health` polled at most 60 times one second apart, then
  `curl POST /run` with each of `input_examples/example_{1,2,3}.json`: HTTP 200 required, the first
  1500 bytes of each response printed, each body validated with the image's own `app.schemas.Result`
  (status success, sample mode, example 3 undeterminable with no cause). A second container started
  with `--network none` answers example 1 too, so the start command needs no network. `docker logs`
  of both containers are printed and the containers stopped in an `always()` step.
- Plan check P result: `docker-check` passed on PR 40
  ([run 40226184252](https://github.com/cprite/explain-why-agent/actions/runs/40226184252), job time
  57 s, head c733d1e). The container was healthy after 4 s (`{"status":"ok","sample_mode":true}`).
  All three `POST /run` calls returned HTTP 200 with a schema-valid success: example_1 causes
  `['volume']`, example_2 causes `['product_quality']`, example_3 determinable false with no causes
  (`[]`). The `--network none` container answered example_1 with HTTP 200, status success, causes
  `['volume']`. The build machine does not run Docker; this run is the only Docker proof.

## Known limits

- Every replayed reply in all three examples is stub-recorded (`recorded_with: stub`, the
  deterministic stand-in in `app/llm/stub.py`); the meta files say so. They show the loop, the SQL,
  the Critic and the branches running for real, not Nemotron's reasoning. The 15 meterless entries in
  the cache are from the 23 Oct Day 1 run and are no longer replayed since the Sprint 11c prompts.
- Zetaris and Nightshift run outside the container. In full mode use the `host.docker.internal`
  variants from `.env.example`; on Linux `host.docker.internal` needs `--add-host`.
- The equality test compares with the Python and DuckDB of the machine running it; outputs were
  generated on Python 3.13 and CI checks them on 3.11 (same pinned DuckDB).
- One run at a time per container (the API's run lock): a second `POST /run` during a run gets 429.

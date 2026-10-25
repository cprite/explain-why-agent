# Sprint 15 — README and metadata.json for judges

Build-plan task 23, issue #33. The submission-facing documents, per architecture §12a and §13 and
the organisers' Submission Requirements §3.3, §3.4, §4 and §8. Launched on 25 Oct before Sprint 16
(Docker and examples) and before the real evaluation recordings, so some parts are placeholders on
purpose (see "Left out"). No code under `app/`, no prompt and no recorded cache changed.

## What was written

- `README.md` at the repository root (there was none on main), with the fourteen sections in the
  order the issue gives: Summary; Quick start (sample mode); Docker; Full mode; Usage; How it works;
  Results; Sponsor technology (Zetaris, Meterless, Meterless Nightshift, NVIDIA, Cursor, and "What
  was unique about our use of the sponsor technologies"); Zetaris USL: reflection; AI and model
  usage; Data; Limitations; Pre-existing components; Third-party code and licences.
  - **Quick start** is one fenced block tagged `bash readme-quickstart`: venv, `pip install -r
    requirements.txt`, then `SAMPLE_MODE=true python run.py "Why did order volume spike on 24
    November 2017?" --loop simple --run-id quickstart`, then `ls -l` of the result, trace and query
    log. `--loop simple` is needed: the Day 1 recording is for the simple loop, and under the default
    Markovian loop the question gets `cache_miss` (checked on 25 Oct, exit 1, `cache_miss`).
  - **Results** is three tables with a Source column; every number names the committed file it
    came from. The live evaluation score and the live run time are "not measured yet".
  - **Full mode** lists every variable name in `.env.example` (names only).
  - **Meterless** names the test command (plan check J: `run.py` on the delivery-lateness question,
    then `scripts/check_markovian_run.py`) and its result line, plus the engine unit tests.
- `metadata.json` at the repository root, in the issue's shape, with a few extra keys
  (`description`, `entrypoints.api_start`, `entrypoints.web`, `sample_mode.quickstart`,
  Zetaris `query_log`, `evidence` lists). `entrypoints.docker` is `null`. The NVIDIA models are the
  two `model_routed` values of the live Nightshift recording in `data/sample/llm_cache/`.
- `scripts/readme_quickstart.py`: prints the quick-start block, or with `--run` runs it with
  `bash -e -x -o pipefail` (each command echoed), with every `.env.example` variable removed from the
  environment and `SAMPLE_MODE=true`, then asserts a new `logs/result-*.json` (success,
  `sample_mode: true`) and a new non-empty `logs/trace-*.jsonl`. Standard library only, because it
  runs before the block installs the dependencies.
- `.github/workflows/ci.yml`: new job `readme-quickstart`, step "Plan check O (task 23)". It checks
  the branch out into a fresh directory (`readme-check/`), writes an empty `.env`, and runs
  `python3 scripts/readme_quickstart.py --run`. A separate job, so the `test` job's 10-minute limit
  is unaffected. O is the next free letter (K browser check, L eval, M PR #30, N Critic).
- `tests/test_docs.py` (run by the existing `pytest -q` step): the fourteen headings in order and
  the six sponsor subsections; one quick-start block, inside its section, that sets only
  `SAMPLE_MODE`, installs with pip and calls no other network tool; the CI job's shape; every
  `python …` command in the README targets an existing script or module and every flag it uses is
  defined there; every `tests/…::test_…` node id exists; every repository path in backticks exists;
  every relative link and `#anchor` resolves; every upper-case variable name is in `.env.example` or
  in `app/`; Full mode lists every `.env.example` name; every `GET`/`POST` route in Usage is an API
  route; every `requirements.txt` pin has a licence row; every number in a Results table appears in
  the file its Source cell names, and the Results prose has no number outside a table; the
  Meterless section's command, result line and paths; `metadata.json`'s shape and that every path
  in it exists; the NVIDIA model ids equal the routed models of the live recording; and the secrets
  grep (`nvapi-`, `sk-`, `@gmail`, any email, token or receipt ids, IPv4 other than 127.0.0.1 and
  0.0.0.0, cloud hostnames) on both files.

## Numbers measured for the README (25 Oct)

Plan check J re-run on the branch (sample mode, the Markovian loop with the Critic, stub-recorded
replies), the source of two Results rows:

```
question: Why did delivery lateness spike for deliveries completed the week of 28 May 2018?
elapsed_seconds: 0.213
chunks: 5/8
stop_reason: completed
status: success; determinable: True; sample_mode: True
top_cause: logistics_delay (confidence 0.75): Deliveries took longer after hand-off to the carrier: transit time rose in the window.
token_report: {'standard_estimate': 7849, 'markovian_actual': 4153, 'saving_percent': 47.1}
[PASS] 5/8 chunks, every chunk input within budget, stop_reason=completed, 0.213 s
```

The token report differs from the Sprint 8 note (5730 / 4043 / 29.4 %) because the Critic
(Sprint 9) now adds a critique to each round, which the standard estimate counts as conversation
growth. The figures are character estimates (`ceil(chars / 4)`), not provider token counts.

## Left out

- **Docker commands.** The section says "Docker: added in Sprint 16" and `entrypoints.docker` is
  `null`; Sprint 16 fills both in.
- **Evaluation score.** No committed evaluation output exists, so the live score is "not measured
  yet". The only committed figure is the sample-mode baseline (`Score: 0/10 (answered 1, no_cache 9,
  errors 0)`, Sprint 11), shown as a baseline with its reason. A follow-up revision fills in the
  real score.
- **Scanner recall** is reported (1/8, from the Sprint 12 note) instead of "not measured yet": the
  issue's launch notes expected none to exist, but the Sprint 12 plan check measured it.
- **Example inputs and outputs.** `input_examples/` is empty and `output_examples/` holds only the
  hand-written schema example from Sprint 2, which the README calls hand-written. The three example
  questions are listed in the README with their commands; Sprint 16 commits the files.
- **Root `result.json` and `result-live.json`** are not cited: PR #30 moves the first and deletes
  the second. No live run time is cited for the same reason ("not measured yet").

## How it was tested

- `pytest -q tests/test_docs.py`, then the whole suite and `ruff check .` (results in the PR).
- Plan check O locally: a fresh `git clone` of the branch into `/tmp`, an empty `.env`, and
  `python3 scripts/readme_quickstart.py --run` (output in the PR description).
- Every command in the README was run once on the build machine in sample mode; the live commands
  (`scripts/live_check.py`, `scripts/zetaris_setup.py`, `scripts/zetaris_parity.py`) were checked
  only for their flags, as this session has no credentials.
- Apple Silicon (owner's review, 25 Oct): on a Mac whose `PATH` bash is an Intel (Rosetta) build, a
  universal python started from that shell runs as x86_64 and `run.py` fails with pydantic_core
  `incompatible architecture (have arm64, need x86_64)`. `scripts/readme_quickstart.py --run` now
  runs the block as `arch -arm64 /bin/bash` when `platform.system()` is Darwin and
  `sysctl -n hw.optional.arm64` is 1; elsewhere the command is unchanged. Unit tests in
  `tests/test_docs.py` pin the command for both cases (platform and sysctl mocked). The README quick
  start has a one-line troubleshooting note. The Mac path itself was not run here (Linux build
  machine); the PR's How to test step 1 includes `arch -x86_64 /bin/bash -c ...` as the proof.

## Known limits

- **`metadata.json` follows our own shape.** The organisers published no schema for it, so it
  follows the shape in issue #33 plus the extra keys above.
- The quick-start check proves the block runs with no credentials and an empty `.env`; it does not
  cut the network inside the block (pip needs it). That sample mode makes no other network call is
  covered by the existing tests (`tests/test_data_zetaris.py`) and by PR #30's plan check M.
- The docs tests check that numbers, paths, commands and flags exist, not that the prose around them
  is right; a claim like "Nightshift routes every call to Nemotron" is checked only through the
  recorded routed models.
- Plan check O installs the full `requirements.txt` (a few minutes), hence its own 20-minute job.

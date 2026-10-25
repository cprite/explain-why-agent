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
    November 2017?" --run-id quickstart` (default Markovian loop), then `ls -l` of the result, trace
    and query log. Since Sprint 11c (main 912862e) this question replays stub-recorded replies on
    both loops; the first version of this README used `--loop simple` for the live 23 Oct recording,
    which no longer replays (see "Revision after review").
  - **Results** is three tables with a Source column; every number names the committed file it
    came from. The live evaluation score and the live run time are "not measured yet".
  - **Full mode** lists every variable name in `.env.example` (names only).
  - **Meterless** names the test command (plan check J: `run.py` on the delivery-lateness question,
    then `scripts/check_markovian_run.py`) and its result line, plus the engine unit tests.
- `metadata.json` at the repository root, in the issue's shape, with a few extra keys
  (`description`, `entrypoints.api_start`, `entrypoints.web`, `sample_mode.quickstart`,
  Zetaris `query_log`, `evidence` lists). `entrypoints.docker` is `null`. The NVIDIA models are the
  two `model_routed` values of the 15 `"recorded_with": "meterless"` entries in
  `data/sample/llm_cache/` (the live Day 1 run of 23 Oct, kept but no longer replayed).
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

## Numbers measured for the README (25 Oct, after merging main 912862e)

Measured with `python run.py "<question>" --sample --run-id <id> > /tmp/r.json` and
`python scripts/check_markovian_run.py /tmp/r.json` (sample mode, the Markovian loop with the
Critic, stub-recorded replies), the source of four Results rows.

Plan check J question:

```
question: Why did delivery lateness spike for deliveries completed the week of 28 May 2018?
elapsed_seconds: 0.205
chunks: 5/8
stop_reason: completed
status: success; determinable: True; sample_mode: True
top_cause: logistics_delay (confidence 0.75): Deliveries took longer after hand-off to the carrier: transit time rose in the window.
token_report: {'standard_estimate': 7948, 'markovian_actual': 4153, 'saving_percent': 47.7}
[PASS] 5/8 chunks, every chunk input within budget, stop_reason=completed, 0.205 s
```

Day 1 question (the quick-start command):

```
question: Why did order volume spike on 24 November 2017?
elapsed_seconds: 0.214
chunks: 6/8
stop_reason: completed
status: success; determinable: True; sample_mode: True
top_cause: volume (confidence 0.75): The rise is broad: many more sellers than usual received orders.
token_report: {'standard_estimate': 9939, 'markovian_actual': 5217, 'saving_percent': 47.5}
```

All 19 model-call lines of that trace read `provider: cache`, `recorded_with: stub`,
`model_routed: scripted-stub`, `receipt_id: null`; ruled out: `single_seller`, `data_artefact`.

The token report differs from the Sprint 8 note (5730 / 4043 / 29.4 %) because the Critic
(Sprint 9) now adds a critique to each round, which the standard estimate counts as conversation
growth. The figures are character estimates (`ceil(chars / 4)`), not provider token counts.

## Left out

- **Docker commands.** The section says "Docker: added in Sprint 16" and `entrypoints.docker` is
  `null`; Sprint 16 fills both in.
- **Evaluation score.** No committed evaluation output with a real model exists, so that score is
  "not measured yet". The README shows the Sprint 11c sample-mode score (`Score: 5/10 (answered 5,
  no_cache 5, errors 0)`, stub-recorded, labelled as plumbing, not a model); re-run here on the
  merged branch with the same line. A follow-up revision fills in the real score from
  `logs/eval-after-*.json` once the coordinator commits it.
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

## Revision after review (25 Oct)

The review ran the branch merged with main 912862e (Sprint 11c) and found the README's sample-mode
claims stale: 11c re-recorded the stub cache and changed the prompts, so the Day 1 question now
replays stub replies (causes `volume`, then on the simple loop also `price_discount`) on both
loops, and the live Nemotron entries no longer replay. Main was merged into the branch (no
conflicts; merge instead of rebase because the branch is already pushed and is never force-pushed),
then:

- Quick start drops `--loop simple` and says plainly that the replies are stub-recorded; the
  Nemotron evidence is the 15 `recorded_with: meterless` cache entries, named in the Nightshift and
  NVIDIA subsections, AI and model usage and Limitations.
- Results cites the 11c sample-mode score and its per-incident outcome, and the run-time and
  token rows are re-measured above; the 23 Oct token total stays, labelled as the live recording that
  sample mode no longer replays. The 1.9 s Day 1 row was dropped (it timed that recording).
- `tests/test_docs.py` gains a check that the README's sample-mode score is the "after"
  cell of the note it cites and that the quick-start text does not claim Nemotron replies while the Day 1
  replay is stub-recorded, so "the number appears in its source" also means "the row is current".

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

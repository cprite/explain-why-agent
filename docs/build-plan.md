# Build plan — 22 to 27 October 2026

Task breakdown for the build window, written 6 October 2026 and re-dated on 7 October when the organisers moved the event a week later. It follows `architecture.md`. Each task
is sized for one Cursor agent session and has a check that can be run, so "done" is not a matter of
opinion. Hours are estimates for a solo build with agent help.

Rules that apply to every task:

- Work happens on a branch and reaches `main` only with passing checks.
- No secrets in the repository; configuration comes from environment variables.
- Every external call has a timeout; every loop has a cap.
- A task is not done until its check passes from a clean clone.

## How a sprint reaches `main` (Nikolay, 19 Oct)

Each task below is one sprint: one issue, one pull request, merged only after Nikolay has tested it.

1. Cursor builds it in the sandbox, with tests for the new behaviour and a sprint note in
   `docs/sprints/NN-<slug>.md` (what was built, what was left out, how it was tested, known limits).
2. CI runs the tests and the task's check below in sample mode; an independent review checks the
   acceptance criteria.
3. We check the pull request's "How to test" steps against the code and the CI log, then send
   Nikolay a sprint report in #general: what it does, how we tested it, and up to five steps for him
   to run on his own computer (under 10 minutes, no credentials).
4. He replies "merge", or describes what is wrong and the sprint goes back for a fix.

His testing adds waiting time between sprints. While a sprint waits, the next one's issue, the README
and the demo material are prepared, so the wait costs as little as possible. Small tasks on the same
day may be grouped into one sprint to keep the number of hand-offs down to two or three a day.

## Day 1 — Thursday 22 October: a thin slice that runs end to end

Goal for the day: one question goes in, a real (if shallow) answer comes out, with a trace, using
local data and a live model.

| # | Task | Check | Hours |
|---|---|---|---|
| 1 | Repository skeleton: layout from the architecture, `requirements.txt`, `.env.example`, `.gitignore`, CI running lint and tests | CI is green on an empty test suite | 1 |
| 2 | Import the prepared data sample and answer key, with `data/sample/README.md` (source, licence, how to regenerate); update `docs/PRE-EXISTING.md` | Row counts match the detectability report | 1 |
| 3 | Local data adapter on DuckDB: `list_sources`, `describe`, `query` with read-only guard, row limit, timeout, query log | Tests: a cross-source join returns rows; a write statement is rejected | 2 |
| 4 | Model generator: OpenAI-compatible, NVIDIA endpoint by default, fallback provider, JSON-schema validation with one repair retry | Test with a stubbed transport; one live call returns valid JSON | 2 |
| 5 | Schemas for question, plan, hypothesis, observation, verdict, result | Schema tests pass; example result validates | 1 |
| 6 | Minimal Planner, Investigator and Reporter wired in a simple loop, plus `run.py` and the trace writer | `python run.py "Why did order volume spike on 24 November 2017?"` returns a result with at least one cause and one evidence item, and a trace file | 4 |

Day total: 11 hours.

## Day 2 — Friday 23 October: World Model and sponsor data layer

| # | Task | Check | Hours |
|---|---|---|---|
| 7 | World Model store: SQLite, content-hash ids, entities, edges, append log | Tests: writing the same observation twice leaves one record | 3 |
| 8 | World Model ingest: query result → observations, effect size against baseline, alerts, edges; idempotent and resumable | Tests: an interrupted ingest resumes without duplicates | 4 |
| 9 | World Model context builder: intent in, structured evidence payload out, within a size budget, with a selection reason per item | Test: payload respects the budget and includes the supporting and refuting evidence for a hypothesis | 2 |
| 10 | Zetaris adapter behind the same data interface, with fallback to the local adapter | The Day 1 question returns the same numbers through Zetaris as through DuckDB | 3 |

Day total: 12 hours. Task 10 depends on Zetaris access; if access is late, move it to Day 3 and
pull task 11 forward.

## Day 3 — Saturday 24 October: the investigation loop and the critic

Organisers' suggested mid-build check: "if the deadline were tomorrow, what would fail?"

| # | Task | Check | Hours |
|---|---|---|---|
| 11 | Markovian config, chunk manager and carryover cascade (four steps) | Tests: carryover stays within budget; each fallback step works when the one before it fails | 3 |
| 12 | Markovian orchestrator replacing the simple loop: chunk 0 from Planner and context builder, one hypothesis round per chunk, caps and abort | A run on the truck-strike question completes in under 10 minutes within `max_chunks` | 4 |
| 13 | Critic agent: disproof checks (alternative cause, concentration, sample size, date basis, data artefact), verdicts, follow-up requests back to the Investigator | On the review-dip question the trace shows the delivery-delay explanation tested and refuted | 4 |
| 14 | Branches: "no significant change", promotion after a refutation, "cannot be determined" | The two undeterminable questions return `determinable: false` with no cause asserted | 2 |

Day total: 13 hours.

## Day 4 — Sunday 25 October: measurement, reliability, interface

| # | Task | Check | Hours |
|---|---|---|---|
| 15 | Evaluation script scoring results against the answer key | `python eval/run_eval.py` prints a score out of 10 and per-incident detail | 2 |
| 16 | Improve prompts and hypothesis coverage from the evaluation failures | Score recorded before and after; no incident-specific wording in prompts | 3 |
| 17 | Token report: projected versus actual per round | Report present in the result and in `logs/` | 1 |
| 18 | HTTP API: `POST /run`, `GET /runs/{id}`, `GET /runs/{id}/trace`, structured errors | `curl` with an example input returns a valid result | 2 |
| 19 | Web page — the workspace: metric board with flagged anomaly cards, "Explain" or a typed question, live trace, answer with expandable evidence, ruled-out list and next checks | Browser check: the demo anomaly is on the board and explains end to end | 4 |
| 19a | Anomaly scanner: metric and segment configuration, STL seasonality removal + robust z-score, ranked cards, `GET /anomalies`, recall in the evaluation | Scanner flags the watches review dip and the Rio freight rise without being told, and does not flag the normal weekly cycle; recall reported by `run_eval.py` | 4 |
| 19b | Attribution (Adtributor-style): explanatory power and surprise per slice, top dimension on each card, exposed to the Investigator as a tool | On a synthetic cube the known slice ranks first; on the data, the Rio freight card names RJ | 2 |
| 20 | Failure handling: query repair retry, model fallback, Zetaris fallback; sample mode with the per-call model response cache | Tests simulate each failure; from a fresh clone with an empty `.env` and the network off, the three example questions run end to end in sample mode | 3 |

Day total: 13 hours.

## Day 5 — Monday 26 October: freeze and package

Feature freeze at midday.

| # | Task | Check | Hours |
|---|---|---|---|
| 21 | Dockerfile, CPU only, dependencies at build time | Clean clone, `docker build`, `docker run`, `curl /run` works | 2 |
| 22 | Three example inputs with outputs and their logs | Files present and regenerable by one command | 1 |
| 23 | README with every section listed in architecture 12a (including AI and model usage, third-party licences, synthetic-data statement) and `metadata.json` | A second person can run it from the README alone | 2 |
| 24 | Demo video, 1–4 minutes | Recorded, uploaded, plays without login | 3 |
| 25 | Slide deck covering the sections the organisers list | Complete and exported | 2 |
| 26 | Final pass: secret scan, pre-existing declaration, decide on the organisers' documents in `docs/`, repository visibility | Checklist in the organisers' overview document answered "yes" throughout | 1 |

Day total: 11 hours.

## Day 6 — Tuesday 27 October: submit

Submit on HackOS by midday London time. The deadline is 23:45 UTC, which is also 23:45 London because the clocks change on 25 October; the
afternoon is reserve, not working time.

## Totals and what gives if time runs short

About 70 hours across five days after adding the anomaly workspace (14 Oct) and the attribution step (19 Oct). Order of cuts, least
damaging first:

1. Web page reduced to the board and the result view without the live trace (saves about 2 hours).
2. Attribution (task 19b) dropped: cards show the flagged slice only (saves about 2 hours).
3. Anomaly scanner limited to three metrics and two segment types (saves about 2 hours).
4. Token report reduced to a single figure in the README.
5. Zetaris used for single-source queries only, with joins done locally.
6. Evaluation run on six incidents instead of ten.

Not to be cut: the critic and its refutation trace, the "cannot be determined" branch, the evaluation
score, a clean run from a fresh clone, and the two required sponsor integrations.

## Before the window opens

- Data sample, injected incidents, answer key and detectability report (in progress, 6 October).
- Build pipeline with Cursor's agent tested on a throwaway repository.
- One live call to an NVIDIA-hosted model from a scratch script.
- A running Zetaris instance and one proven way to register our sources in it (Postgres over JDBC, or
  files in S3-compatible storage as the fallback), tested on throwaway data. This is learning the tool,
  which the organisers encourage before kickoff; no project code comes out of it. See
  `research/zetaris-setup.md`.
- Cursor access steps, once the organisers publish them.
- Demo script and slide outline.

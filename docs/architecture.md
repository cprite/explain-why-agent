# Architecture — "Why did this number change?"

Design document, written 6 October 2026, before the build window. It describes what will be built
between 22 and 27 October (the organisers moved the event a week later on 7 October). Nothing here is implemented yet. Open decisions are listed at the end.

## 1. What the product does

**Product shape (Nikolay's decision, 14 Oct): an "explain this anomaly" workspace.** The user opens
a board of key business metrics on which the system has already flagged unusual movements, clicks
"Explain" on one, watches the investigation run, and gets an answer with what to check next. The
flow is notice → explain → act. A user can also type their own question instead of picking a flagged
card.

The investigation answers why a metric moved, for example "Why did review scores for watches fall
in January 2018?". The system investigates across four separate data sources and returns:

- ranked causes, each with the evidence behind it (source, query, numbers, baseline);
- the explanations it tested and ruled out, and why;
- a confidence level and the limits of the answer, including "this cannot be determined from the
  data" when that is the honest result;
- what to check or do next for each cause.

The user is an operations or commercial analyst at a marketplace. The decision supported is where to
look and what to fix first when a number moves.

Track: 02, "The Agent That Can Explain Why".

The organisers said on 12 Oct that concrete challenge statements are published only at kickoff. The
scenario below (a marketplace, the Olist data) is therefore a working scenario. The engine — the
agents, the evidence record, the investigation loop, the evaluation harness — does not depend on the
Olist schema: sources, metrics and hypothesis families are configuration, so a different statement
means new data and questions, not a new system.

## 2. Design principles

1. **Every claim carries its evidence.** A cause without a query and a number behind it is not
   reported.
2. **The critic's job is to disprove.** The leading explanation survives only if an independent
   agent fails to break it.
3. **Stopping is a valid answer.** The system is scored on refusing to invent causes as much as on
   finding them.
4. **Bounded runs.** Capped rounds, timeouts on every external call, a full run in 5–10 minutes.
5. **Runs without the sponsors' services.** Every external dependency sits behind an adapter with a
   local fallback, so a judge can run it from a clean clone.
6. **The trace is the proof.** Everything an agent does is written as JSONL that a judge can read.

## 3. Data sources

Four sources, kept separate the way a real business keeps them (details in
`research/olist-dataset-and-incident-plan.md`):

| Source | Tables | Typical owner |
|---|---|---|
| Orders and fulfilment | orders, order_items, customers, geolocation | Order management |
| Payments | order_payments | Finance or payment provider |
| Reviews | order_reviews | Customer experience |
| Marketing and catalogue | marketing_qualified_leads, closed_deals, sellers, products | CRM and BI |

Access goes through one interface:

```text
DataLayer
  list_sources() -> [source]
  describe(source) -> tables, columns, row counts
  query(source, sql, limit, timeout) -> rows + query id
```

- **Zetaris adapter (default):** each source is its own Postgres database, registered in Zetaris over
  JDBC (or, as the fallback, as files in S3-compatible storage); one Unified Semantic Layer defined in
  DDL spans the four. The agents query that layer through Zetaris's REST interface, including
  cross-source joins. This is where Zetaris sits in the
  build. Judges will not have our Zetaris instance, so the README says plainly that the default path
  needs one and that sample mode is the path anyone can run. Rules from the tested recipe and
  Zetaris's SQL companion (`research/zetaris-test-2026-10-14.md`,
  `research/zetaris-resources-2026-10-19.md`): every value comes back as a string, so the adapter
  converts types; each statement is sent whole (a multi-table `COMPILE USL` breaks if split on `;`);
  the setup script re-runs `ACTIVATE USL TABLE` after any model change; generated SQL prefers window
  functions to self-joins.
- **Local adapter (sample mode):** the same sample files loaded into DuckDB, one schema per source.

Queries are read-only, row-limited and time-limited. Every query gets an id and is logged with its
SQL, source, duration and row count.

## 4. Agents

Four roles with different jobs and different prompts. They do not run as a fixed pipeline: the
orchestrator decides the next step from the state of the investigation.

| Agent | Job | Reads | Writes |
|---|---|---|---|
| **Planner** | Turn the question into metric, segment, window and baseline; confirm the change is real; propose hypotheses and the tests for each | Question, source schemas | Investigation plan, hypothesis list |
| **Investigator** | Test one hypothesis: write and run queries, measure effect against baseline | Plan, evidence so far | Observations with provenance |
| **Critic** | Try to disprove the leading explanation: alternative causes, concentration, sample size, date basis, data artefacts | Leading hypothesis and its evidence | Verdict (supported, refuted, insufficient) and required follow-up tests |
| **Reporter** | Produce the final structured answer and the readable summary | Final ranking, evidence, ruled-out list | Result JSON |

Interaction patterns the trace must show:

- **Delegation:** Planner assigns hypotheses to the Investigator in priority order.
- **Critique and revision:** Critic sends a hypothesis back with specific tests; Investigator runs
  them; ranking changes.
- **Branching:** if the Planner finds the change is within normal variation, the run branches to a
  "no significant change" answer. If the Critic refutes the leader, the next hypothesis is promoted.
- **Retry and fallback:** a failed query is repaired once from the error message; a failed model
  call is retried, then routed to the fallback model; a failed Zetaris call falls back to the local
  adapter and the result is marked as such.
- **Escalation to "cannot be determined":** when all hypotheses are refuted or the sample is too
  small, the Critic's verdict forces that outcome instead of a best guess.
- **Scored critique:** the Critic scores the leading explanation 0–3 on three points (is it supported
  by the data, does it explain the size and timing of the change, are the alternatives excluded). A
  total under 7 of 9 sends it back for one revision with a specific request; a second failure demotes
  it. The organisers' own learning deck recommends this proposer-and-critic pattern with a 7-of-9
  threshold, and their mentor guide asks for "a critic that can reject, not just review".
- **Evidence versus inference:** every statement in the answer is marked as measured (it has a query
  and a number) or inferred (a conclusion drawn from measurements). Inferences never appear without
  the measurements they rest on.

Hypothesis families the Planner draws from: volume, price or discount, mix shift (payment type,
category, region), single seller or segment, logistics delay, product quality, marketing funnel,
data artefact (duplicates, missing rows), and external cause not present in the data.

## 5. Meterless engines

Two of the three Meterless reference architectures are implemented in Python inside the project.

### 5.1 World Model — shared evidence with provenance

A SQLite store that every agent reads and writes. It is the single record of what the system
believes and why.

- **Entities:** Question, Metric, Segment, Hypothesis, Observation, Query, Source. Ids are content
  hashes, so re-ingesting the same observation does not duplicate it.
- **Edges:** `tests` (query → hypothesis), `supports` and `refutes` (observation → hypothesis),
  `derived_from` (observation → query), `from_source` (query → source). Each edge records the agent
  and run that created it.
- **Services (the minimum set from the guide):**
  - `WorldStore` — persistence, content-hash ids, append-only log.
  - `IngestPipeline` — takes a query result, normalises it into observations, scores effect size
    against baseline, raises an alert when a threshold is crossed, writes edges. Idempotent and
    resumable.
  - `ContextBuilder` — given an intent ("critique hypothesis H3"), selects the relevant evidence
    within a size budget and returns a structured payload with a `selection_reason` per item.
- **Skipped:** enrichment jobs, control plane, supervisor agent, queues.

### 5.2 Markovian — the bounded investigation loop

The investigation is one long task. Instead of a growing conversation, each round runs with a small
fixed context: the goal, a compressed carryover state and the evidence the ContextBuilder selects.

- **Chunk 0:** Planner output plus the World Model context.
- **Each later chunk:** one investigate-and-critique round on one hypothesis.
- **Carryover state:** current ranking, what has been ruled out and why, open questions, rounds
  left. Produced by the four-step compression cascade from the guide (explicit state, model
  compression, heuristic extraction, truncation).
- **Config:** small chunk size and a low `max_chunks` (about 8) to keep the run inside 10 minutes.
- **Report:** projected versus actual token use per round, written to `logs/`. This gives a measured
  figure for the token saving.
- **Skipped:** history analytics across runs, live telemetry tuning.

H-MEM is not implemented: each run is one self-contained investigation, so there is no second
session for memory to carry into.

## 6. Model layer

One injected generator function, OpenAI-compatible, used by every agent and both engines.

**Changed 19 Oct by the organisers' Participant Setup Guide** (`organiser-docs/2026-10-19/`): the
Power rule says the app must support **Meterless Nightshift as a primary AI provider**, and NVIDIA
counts (including the Nemotron award) only when Nemotron runs **through** Nightshift.

- **Primary: Meterless Runtime (Nightshift).** Provider id `meterless`, OpenAI-compatible, default
  base URL `http://127.0.0.1:8088/v1`, implemented to the official "Add Meterless as a provider"
  contract (`research/meterless-power-prompts-2026-10-19.md`): `Authorization: Bearer <runtime
  token>` on every call, `meterless-app: explain-why` on every request, `meterless-scope: user` on
  chat, model ids are routing modes (`meterless/auto`, `meterless/deep`, …) read from
  `GET /v1/models`; status online / unauthorized / offline decided by `/v1/models`, not `/healthz`;
  180 s timeout. Settings: `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`, `METERLESS_MODEL`.
- **Nemotron through Nightshift.** NVIDIA's key lives in Nightshift's Providers tab, never in our
  app. Lanes: fast worker `nemotron-3.5-lightning-30b-a3b` (Investigator, Critic), deep worker
  `nemotron-3.5-super-vl-120b-a12b` (Planner, Reporter), names as listed in Nightshift's picker.
  We pin a Nemotron-backed route rather than relying on `meterless/auto`, and the trace records
  the model Nightshift reports, so the Nemotron award evidence is unambiguous.
- **Where Nightshift runs.** Nightshift ships for Windows, Mac and DGX only, not Linux ARM, so it
  runs on Nikolay's Mac. The demo runs on the Mac (app, Nightshift, and Zetaris reached through its
  tunnel or run locally). During the build, the Pi reaches Nightshift through an SSH reverse tunnel
  from the Mac (`127.0.0.1:8088` on both ends, nothing exposed).
- **Fallback:** NVIDIA's hosted API directly, behind the same interface, selectable in settings and
  used only when Nightshift is unreachable; the README and demo use Nightshift.
- **Sample mode and CI:** recorded responses (the per-call cache), so judges and CI need neither.
- **Engines:** World Model and Markovian stay as implemented in our code (the Build rule asks for at
  least one Meterless Engine in a working feature); both take the generator above.

## 6a. Anomaly scanner

Not an agent: a deterministic job that finds the movements worth explaining.

- **Metrics and segments are configuration:** for example order count, revenue, average review
  score, late-delivery rate, average freight, payment-type share; segmented by state, product
  category, seller and payment type. Each is one SQL template run through Zetaris.
- **Method:** each metric is computed per segment and period. The regular pattern (trend and weekly
  cycle) is removed first, and only what is left over is tested, so a normal weekend dip or seasonal
  peak is not flagged. A movement is flagged when that leftover is large relative to the segment's
  normal variation and the segment has enough volume to trust it. Flagged moves are then attributed
  to the slice that explains them. Both steps follow published practice (see the implementation plan).
- **Output:** up to about ten anomaly cards, ranked by size and volume: metric, segment, period,
  baseline, observed value, and a pre-filled question for the Planner.
- **Integrity:** the scanner knows nothing about the planted incidents. Its recall on them (how
  many of the eight that show a real metric move it flags) is reported by the evaluation, alongside
  any real anomalies it finds that we did not plant.

**Implementation plan (19 Oct):**

1. **Configuration** (`scanner.yaml`): about eight metrics, each a SQL template — daily orders, revenue,
   average order value, average review score, late-delivery rate, average freight, payment-type
   share, revenue by sellers' acquisition channel (joins the marketing source). Segment types:
   whole shop, state, product category, payment type, acquisition channel, and sellers above a
   minimum volume.
2. **Series:** one Zetaris query per metric and segment type, grouped by segment and week (day for
   order counts): about 40 queries at 1–2 s each, run once at start-up and on demand, results cached.
3. **Test — seasonality first, then a robust outlier test** (changed 19 Oct after checking how
   monitoring products do it):
   - decompose each series with STL (`statsmodels`, robust fitting): trend + weekly cycle (period 7)
     for daily series; trend only for weekly series;
   - score the remainder with a robust z-score: (value − median) / (1.4826 × median absolute
     deviation) over a trailing window (28 days or 8 weeks), so one extreme period does not hide the
     next;
   - flag at |z| ≥ 3.5; skip segment-periods below a volume floor (for example 30 orders) so small
     sellers do not flood the board;
   - series shorter than three cycles fall back to the plain trailing-median test.
   Ready-made alternatives were checked and not used: StarTree ThirdEye (closest product, but needs
   Apache Pinot and Kubernetes and would replace Zetaris as the data layer), Salesforce Merlion
   (archived March 2026), ADTK (no release since 2020), Prophet (works, but heavy and slow across
   hundreds of series).
3a. **Attribution (Adtributor-style drill-down):** for each flagged whole-shop or parent-level move,
   compute for every slice of every dimension (state, category, payment type, channel, seller) its
   *explanatory power* (share of the total change it accounts for) and *surprise* (how far its
   share of the metric moved from its expected share, Jensen-Shannon divergence). Per dimension,
   keep the smallest set of slices that explains at least 67% of the change, ranked by surprise;
   rank dimensions by total surprise. The top dimension and slices go on the card ("driven by Rio de
   Janeiro: 72% of the change") and into the Planner's first hypotheses. Method: Bhagwan et al.,
   *Adtributor: Revenue Debugging in Advertising Systems*, NSDI 2014. Fundamental metrics (counts,
   sums) use it directly; ratio metrics (average review score, late rate) are attributed through
   their numerator and denominator, as the paper describes for derived measures. The Investigator
   can call the same function as a tool.
4. **Rank and merge:** consecutive flagged periods become one episode; score = |z| × log(volume);
   when a parent and its child flag the same move (whole shop and one state), keep one card and let
   the attribution name the child. Show the top ten.
5. **Card:** metric, segment, period, baseline, observed, change, and a pre-filled question.
6. **Honesty:** thresholds are fixed before recall is measured and never tuned per incident; the
   scanner never reads `answer_key.json`. The evaluation reports recall on the planted incidents and
   lists unplanted flags separately (real Olist events, such as the May 2018 truckers' strike, may
   appear; incident 09 is a deliberate no-cause case).
7. **Tests:** unit tests on synthetic series (spike, step change, pure noise, low volume, a strong
   weekly cycle that must not be flagged); attribution tests on a synthetic cube where one known
   slice causes the change; and the recall check in CI on sample mode, which runs the same code on
   DuckDB. The README names both methods and links the Adtributor paper.

## 7. Interfaces

- **`run.py`** — command line: one question in, result JSON out, exit code set.
- **HTTP API (FastAPI):** `POST /run` with `{run_id, input: {query}, options: {sample_mode}}`,
  returns the result; `GET /runs/{id}` returns the stored result; `GET /runs/{id}/trace` returns the
  JSONL trace. Bound to `0.0.0.0`.
- **More endpoints:** `GET /anomalies` returns the current anomaly cards; `POST /run` also accepts
  `{anomaly_id}` instead of a free-text query; `GET /runs/{id}/events` streams the trace as it happens.
- **Web page — the workspace:** one page served by the same app, no login, no build step.
  1. The board: metric tiles with small trend lines, flagged anomalies highlighted with their size.
  2. "Explain" on a card (or a typed question) starts a run; the trace arrives live: which agent,
     what it asked Zetaris, what the critic objected to, what changed as a result.
  3. The answer: ranked causes with expandable evidence (query, numbers, baseline), the ruled-out
     list, confidence, and what to check next.

Result shape (abridged):

```json
{
  "run_id": "demo-001",
  "status": "success",
  "question": "...",
  "change": {"metric": "...", "segment": "...", "window": "...", "baseline": 0, "observed": 0, "significant": true},
  "determinable": true,
  "causes": [
    {"rank": 1, "type": "product_quality", "summary": "...", "confidence": 0.82,
     "evidence": [{"observation_id": "...", "source": "reviews", "query_id": "...", "finding": "..."}]}
  ],
  "ruled_out": [{"type": "logistics_delay", "why": "...", "evidence": ["..."]}],
  "limitations": ["..."],
  "agents": [{"name": "Planner", "role": "..."}],
  "trace_id": "...", "log_file": "logs/trace-demo-001.jsonl",
  "token_report": {"standard_estimate": 0, "markovian_actual": 0, "saving_percent": 0},
  "execution_time_seconds": 0
}
```

Run limits are configuration, not code: `MAX_AGENT_ROUNDS`, `MAX_RETRIES`, `MAX_TOOL_CALLS`,
`MAX_OUTPUT_TOKENS` and the model temperature (0.2 by default, for reproducible runs) are read from
the environment with safe defaults, as the organisers' troubleshooting guide recommends.

## 8. Evidence and logs

Written to stdout and to `logs/`, one file set per run:

- `trace-<run>.jsonl` — one line per agent action: timestamp, agent, action, target agent, input and
  output summaries, verdict, retry count, status.
- `queries-<run>.jsonl` — every query with source, SQL, duration, row count, adapter used.
- `world-<run>.jsonl` — the World Model append log: observations, alerts, edges.
- `markovian-<run>.jsonl` — per chunk: hypothesis under test, carryover in and out, token counts.

Nothing in these files is written by hand or post-processed.

## 9. Evaluation

`eval/run_eval.py` runs every question in the answer key and scores the structured result:

- cause type and segment match the planted mechanism;
- the window overlaps the planted window;
- the designated wrong explanation appears in `ruled_out`;
- for the two undeterminable incidents, `determinable` is false and no cause is asserted.

The anomaly scanner is scored separately: how many of the planted incidents with a real metric move
it flags without being told, and how many real, unplanted anomalies it also surfaces.

The headline number is "found N of 10", reported in the README with the run logs behind it. The
answer key is used only by this script and is never visible to the agents.

## 10. Sample mode

`SAMPLE_MODE=true` runs the whole system with no live credentials: the local data adapter replaces
Zetaris, and model calls are served from a response cache. The organisers' checklist requires that
sample mode "still runs real agent logic on cached data, rather than replaying a saved output", so the
cache sits at the level of a single model call, keyed by a hash of the request. The agents, the
engines and the queries all execute; only the model's reply comes from the cache, which is recorded
from real runs of the example questions and committed with the samples. A cache miss returns a
structured error saying that this question needs a model key. Sample mode is labelled as such in the
result, the trace and the README. The default mode always calls the live model.

## 11. Technology

Python 3.11 · FastAPI and uvicorn · DuckDB (local data) · SQLite (World Model) · the `openai` client
for model calls · pydantic for schemas · pytest. No agent framework: the orchestration loop is the
Markovian engine itself, which keeps the Meterless integration real and the dependency list short.
Docker, CPU only, dependencies installed at build time. Developed with Cursor.

## 12. Repository layout

```text
app/
  agents/        planner.py investigator.py critic.py reporter.py prompts/
  engines/
    world_model/ store.py ingest.py context.py
    markovian/   config.py chunks.py carryover.py orchestrator.py report.py
  data/          layer.py zetaris.py local.py
  llm/           generator.py
  api.py         FastAPI app and web page
  schemas.py
data/sample/     four source folders, README with source and licence
eval/            run_eval.py answer_key.json
input_examples/  output_examples/  logs/
web/             index.html
run.py  Dockerfile  requirements.txt  .env.example  metadata.json  README.md
docs/
```

## 12a. What the README must contain

From the organisers' AI usage policy and checklists: setup and run commands from a clean clone; agent
roles; the three examples; limitations stated plainly; a section "AI and Model Usage" (models, the
four partner technologies and what each does here, that AI coding tools were used and the code was
reviewed, how sample mode behaves); a section "Third-Party Code and Licences"; data sources with
licence, the subset used and how to regenerate it; and a clear statement that the planted incidents are
synthetic changes to real public data. `metadata.json` repeats the partner technology record.

## 13. Where each sponsor technology sits

| Sponsor | Role in the build | Evidence in the submission |
|---|---|---|
| Zetaris | Data layer: the four sources are queried and joined through it | Query log shows the adapter and source for each query |
| Meterless | World Model for shared evidence, Markovian for the investigation loop | Engine code, engine logs, token report |
| Meterless Nightshift | Primary model provider: every agent call goes through the Meterless Runtime | Provider settings and run receipts in the demo; trace shows the route |
| NVIDIA | Nemotron lanes inside Nightshift power all agents | Nemotron model id per call in the trace and in `metadata.json`; Nightshift Providers tab in the video (keys hidden) |
| Cursor | Development tool for the whole build | README section and commit history |

## 14. Open decisions

1. **How the data reaches Zetaris — answered** (Data Day workshop, 12 Oct, and Zetaris's
   getting-started repository, `research/zetaris-setup.md`). Zetaris attaches sources with SQL and
   serves them through a Unified Semantic Layer. Two things are settled and two are not:
   - Settled: the agents call Zetaris over its **REST** interface (`POST …/sql-editor/sqls/run` with a
     bearer key created in the Zetaris interface and an `X-Org-ID` header). Zetaris's own guide
     recommends REST when there is no Java runtime, and REST returns every value as a string, so the
     adapter converts types.
   - Settled: a semantic layer can join tables that come from two different sources; their repository
     has a tested example. A foreign key across two separate semantic layers is unconfirmed, so all
     four sources go into one layer.
   - Settled on 14 Oct by testing on our own instance (`research/zetaris-test-2026-10-14.md`):
     **Postgres registration works.** Two separate Postgres databases were registered with
     `CREATE DATASOURCE … jdbcdriver "org.postgresql.Driver"`, joined directly, and joined again
     through a two-table semantic layer whose foreign-key check passed. The four sources will be four
     Postgres containers on the Zetaris Docker network.
   - Settled on 14 Oct: **Zetaris runs on AWS** (m7i-flex.large, Stockholm), reached from the Pi
     through an SSH tunnel. The agents call its REST API with an API key.
2. **Model calls in sample mode — resolved on 7 Oct** from the organisers' disqualification checklist
   and AI usage policy: a per-call response cache, see section 10.
3. **Which Nemotron model.** Depends on the credits and limits NVIDIA announces.
4. **Web page scope.** One page as described, or command line and API only if time runs short.
5. **Repository size.** The planned sample is about 22–24 MB as CSV (5–6 MB gzipped); decide whether
   to commit it compressed or reduce it.

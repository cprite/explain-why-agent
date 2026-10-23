# Sprint 5 — World Model engine: store, ingest and context builder

Build-plan tasks 7–9, issue #11. The three services of the Meterless World Model from
`docs/architecture.md` §5.1, in `app/engines/world_model/`. Agents are not rewired to it yet; that
happens with the Markovian orchestrator (separate PR, `app/engines/markovian/`, untouched here).

## What was built

### Part A — `WorldStore` (task 7), `store.py`

- One SQLite file, `WORLD_DB_PATH` (default `logs/world.db`). No server, no new dependency
  (`sqlite3` from the standard library). WAL mode, a 10 s lock timeout.
- **Entities** Question, Metric, Segment, Hypothesis, Observation, Query, Source. The id is
  `<tag>_<first 16 hex digits of SHA-256(type + ":" + canonical JSON)>` (`obs_49e1a721f0e6deb6`).
  Canonical JSON = sorted keys, no spaces, floats rounded to 12 significant digits, integral floats
  written as ints (so `120`, `120.0` and float-sum noise hash alike). Only the identity fields per
  type go into the hash (`CANONICAL_FIELDS`), for example an observation's query, metric, segment,
  window, baseline window, value and baseline; derived and run-local fields (the per-run query label
  `q001`, effect sizes, the alert flag) are stored but do not change the id.
- **Edges** `tests` (query → hypothesis), `supports` / `refutes` (observation → hypothesis),
  `derived_from` (observation → query), `from_source` (query → source). End types are checked; both
  ends must exist. Edge id = hash of type and both ends. Each edge stores the `agent` and `run_id`
  that first wrote it.
- **Append-only**: every write appends one `log` row (timestamp, agent, run id, operation, target,
  `noop`). Writes are `INSERT … ON CONFLICT DO NOTHING`; a repeat write returns the same id, stores
  nothing and is logged with `noop = 1` (the first writer's agent and run stay on the record).
  Triggers on all four tables (`entities`, `edges`, `log`, `checkpoints`) abort any UPDATE or
  DELETE, so the rule also holds for code that bypasses the class.
- `transaction()` groups writes into one commit (used by the ingest batches).
- Read helpers: `get`, `get_edge`, `entities(type)`, `edges(id, type, direction)`,
  `neighbours(id, type, direction)`, `observations_for(hypothesis)` (supports/refutes edges plus
  observations derived from queries that test it), `latest_checkpoint`, `log_rows`, `counts`, and
  `export_log_jsonl(run_id, path)` for the `world-<run>.jsonl` file of architecture §8.

### Part A — `IngestPipeline` (task 8), `ingest.py`

- `ingest(result, *, run_id, hypothesis, window, baseline_rows, baseline_window, window_column,
  segment_columns, value_columns, direction, sources, agent)` takes a `QueryResult` from
  `DataLayer.query` (a `QueryError` is refused).
- One Observation per (row, value column). Value columns default to every numeric column that is
  not the window or a segment column. Segment = `col=value,…` (or `all`); window = the row's
  `window_column` value (daily rows) or the passed `Window`.
- Baseline per (metric, segment) = median of the matching `baseline_rows`. Effect = absolute change
  and relative change (`value / baseline − 1`, None for a zero baseline). Robust z =
  `(value − median) / (1.4826 × MAD)` when the baseline has ≥ 3 points, the spread floored at 1 % of
  |median| (the scanner's rule, decision D-2ea141).
- Alert when |relative change| ≥ `ALERT_REL_CHANGE` (default 0.25) or |z| ≥ `ALERT_Z` (default 3.5);
  the observation stores `alert` and `alert_reasons`, and the log row of a new alerting observation
  carries `{"alert": true}`.
- Edges: `from_source` for each source (the result's source, or the `<source>.` qualifiers in a
  cross-source statement), `tests` when a hypothesis is given, `derived_from` for each observation.
  `supports` / `refutes` only when the caller passes a direction: a fixed `"supports"` /
  `"refutes"` (or True / False), or a function of the observation's fields.
- **Resumable**: rows are written in batches (`checkpoint_every`, default 100); each batch commits
  together with an append-only checkpoint (rows done, rows total, finished, truncated) keyed by the
  query's content id plus a digest of the ingest inputs (rows, baseline, window, columns, direction,
  cap). An exception rolls back the open batch; the next call resumes after the last committed
  batch. A finished ingest returns `noop=True` without writing anything, not even a log row.
- **Cap**: at most `MAX_INGEST_ROWS` (default 5000) rows; the rest is skipped, the report and the
  final checkpoint say `truncated`. The data layer's own truncation is reported as `source_truncated`.
- Demo, `python -m app.engines.world_model.ingest --sample`: one real cross-source query on the
  sample data through `LocalDataLayer` (daily orders and payment value for SP, RJ and MG, 23 Apr –
  27 May 2018). The last week is the window, the four weeks before are the baseline series; a
  stand-in rule for the Critic marks a fall as `supports` and a rise as `refutes` for the demo
  hypothesis. Prints a `COUNTS {...}` line with entities and edges by type.

### Part B — `ContextBuilder` (task 9), `context.py`

- `ContextBuilder(store).build(Intent(kind, hypothesis_id=None, question_id=None), budget_chars)`.
  Rules only, no model call (a test checks the module imports nothing from `app.llm`, `app.agents`,
  `openai` or `httpx`).
  - `critique H`: H, then every observation tied to H (supports/refutes edge, or derived from a
    query that tests H), strongest effect first (|relative change|, then |z|, then id). The strongest
    refuting observation is protected.
  - `investigate H`: H, the queries that test it (each with observation, alert, supports and
    refutes counts, the strongest effect and the SQL shortened to 160 characters), then the sources
    they used.
  - `plan` / `report`: the question (or all questions), its hypotheses by priority with supports,
    refutes and query counts, then the top 10 observations by effect.
- Payload: `intent`, `items` (`id`, `type`, compact `summary` with numbers rounded to 4 significant
  digits, window, segment, source and query id, and a `selection_reason` such as
  `"refutes H1 (investigator, run sample-world); rel +10.6%, z +0.37; effect rank 39/42; strongest refuting item, always kept"`),
  `candidates`, `over_cap`, `budget_chars`, `used_chars`, `dropped` (`count`, `ids`, `ids_complete`).
- Budget: `used_chars` is exactly `len(serialise(payload))` (sorted-key compact JSON, the field
  included) and never exceeds `budget_chars`. The builder keeps the longest priority prefix that
  fits, plus the protected refuting item, which goes only if a payload holding just it (and no
  dropped ids) does not fit. Items come before the dropped-id list: when the complete list does not
  fit next to the kept items, it lists as many ids as fit (highest priority first, the count stays
  exact) and sets `ids_complete: false` before dropping another item;
  a budget below the empty payload (about 200 characters) raises `ValueError`.
- At most 100 candidates per build (`MAX_CANDIDATES`; the rest is counted in `over_cap`, the
  protected item is kept).
- Demo, `python -m app.engines.world_model.context --sample --intent critique [--budget 4000]`:
  seeds the store with the Part A demo ingest and prints the payload.

### Configuration

New settings in `app/config.py` and `.env.example`: `WORLD_DB_PATH`, `ALERT_REL_CHANGE`, `ALERT_Z`,
`MAX_INGEST_ROWS`.

## Deliberately left out

- Enrichment jobs, control plane, supervisor agent and queues (architecture §5.1 "Skipped").
- Wiring the agents to the World Model: the Investigator still builds `Observation`s itself and the
  loop does not call the ContextBuilder. That comes with the Markovian orchestrator (tasks 11–12) and
  the Critic (task 13), which will also decide supports/refutes instead of the demo's sign rule.
- Live (Zetaris) ingest: the demo is sample mode only (`--sample` is required).
- `world-<run>.jsonl` is not written automatically; `export_log_jsonl` produces it when the
  orchestrator needs it.

## How it was tested

- `ruff check .` → `All checks passed!`; `pytest -q` → `156 passed` on the Pi (42 new tests in
  `tests/test_world_store.py`, `tests/test_world_ingest.py`, `tests/test_world_context.py`).
- What the tests cover: content-hash ids (key order, int/float spelling, float noise, canonical vs
  non-canonical fields, type in the hash) and the same ids from three subprocesses with different
  `PYTHONHASHSEED`; edges with agent and run id, idempotent, wrong end types and missing ends
  refused; read helpers; append-only log (an SQLite trace callback sees no UPDATE/DELETE/REPLACE,
  the log row count only grows, the triggers refuse direct UPDATE/DELETE on all four tables);
  transaction rollback; JSONL export; effect size and alert on both sides of the relative threshold
  (124/125 and 76/75 against 100) and of the z threshold (125/126 and 75/74 against a five-point
  series); thresholds and cap from the environment; normalisation, metric/segment/source entities
  and edges; directions (fixed and function); a Planner `Hypothesis` written and tested; re-ingest
  writes nothing; row cap and truncation; the demo run twice in subprocesses; every ContextBuilder
  intent; budgets from below one item to the full payload (exact fit and one character less);
  protected refuting item at every budget from "it alone, no ids listed" upwards (seeded and sample
  store, including 800–1500 characters on the sample store); incomplete dropped-id lists and the
  minimum-budget error; candidate cap; non-empty `selection_reason`; byte-identical payloads from the
  same store, a reopened store and a store written in reverse order; intent validation; the context
  demo.
- Plan checks, each a CI step with its output in the log:
  - Task 7 (`test_plan_check_task7_same_observation_twice_is_one_record`):
    ```
    plan check task 7: ids obs_49e1a721f0e6deb6 / obs_49e1a721f0e6deb6; entity rows [('obs_49e1a721f0e6deb6', 'investigator', 'run-a')]
      log seq=1 agent=investigator run=run-a op=put_entity noop=False
      log seq=2 agent=critic run=run-b op=put_entity noop=True
    ```
  - Task 8 (`test_plan_check_task8_interrupted_ingest_resumes_without_duplicates`), 25 rows × 2
    metrics, batches of 4, a simulated crash at row 10:
    ```
    plan check task 8: crash after 10 rows (batches of 4); checkpoint rows_done=8; 16 observations committed before the crash
      resumed from row 8: 17 rows, 34 observations; finished=True
      uninterrupted: 57 entities, 102 edges; interrupted+resumed: 57 entities, 102 edges; identical=True
    ```
  - Task 9 (`test_plan_check_task9_critique_has_support_and_refutation_within_budget`): the critique
    payload for a seeded H1 at a 2500-character budget, printed in full; it ends with
    `used_chars=2243 budget_chars=2500 dropped=3` and holds supporting and refuting items.
  - Sample ingest twice (same DB), identical `COUNTS` lines, the second run a no-op:
    ```
    ingest ing_f7abf82e976e6fed: 21 rows from row 0, 42 observations, 34 alerts, truncated=False
    COUNTS {"edges": {"derived_from": 42, "from_source": 2, "refutes": 4, "supports": 38, "tests": 1}, "entities": {"hypothesis": 1, "metric": 2, "observation": 42, "query": 1, "question": 1, "segment": 3, "source": 2}}
    ingest ing_f7abf82e976e6fed: already finished, nothing written (no-op)
    COUNTS {"edges": {"derived_from": 42, "from_source": 2, "refutes": 4, "supports": 38, "tests": 1}, "entities": {"hypothesis": 1, "metric": 2, "observation": 42, "query": 1, "question": 1, "segment": 3, "source": 2}}
    ```
  - Sample context: `intent=critique items=8 {"hypothesis": 1, "observation:refutes": 1, "observation:supports": 6} used_chars=3995 budget_chars=4000 dropped=35`.

## Known limits

- **Changing the hashing scheme orphans stored ids**; a test pins it. Changing `CANONICAL_FIELDS`
  has the same effect.
- **First writer wins** for the non-canonical fields: if the same observation is re-ingested with
  other alert thresholds, the stored `alert` flag stays as first written (the ingest key differs, so
  the rows are processed, but every write is a no-op).
- The ingest key includes a digest of the rows: the same query re-run with different rows is a new
  ingest (new observations where the values differ), which is the intended behaviour; a direction
  function is keyed by its qualified name, so editing its body without renaming it is not detected.
- The baseline is the median of the matching baseline rows; seasonality is not removed (the scanner
  does that; the ingest only scores what the caller passes).
- `plan` / `report` with a `question_id` only include observations tied to that question's
  hypotheses; change-check observations (no hypothesis) appear only without a `question_id`.
- The dropped-id list costs about 23 characters per item; at small budgets it is shortened
  (`ids_complete: false`), so a caller sees the exact count but not every dropped id (the demo
  critique keeps 8 of 43 items at 4000 characters and lists only part of the 35 dropped ids).
- SQLite triggers are row-level, so they guard rows, not schema: `DROP TABLE` is not blocked (no
  code issues one).

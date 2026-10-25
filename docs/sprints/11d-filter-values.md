# Sprint 11d — Ground filter values in the data, handle empty results

Issue #36. This fixes a problem seen in real runs. The Investigator filtered on values that are not
stored in the data. The query matched nothing, and the Critic then reported "the sample is too small
(0 records)". This sprint does two things: it shows the agents the stored values, and it treats an
empty result as an empty filter, not as a small sample. It stays out of Sprint 11c's areas (#35:
change-check spread, Planner hypothesis checklist, the sample-size rule on a drop to zero).
`app/agents/critic.py` and `planner.md` are not touched; `planner.py` has both 11c's checklist and
this sprint's value note.

## Real-run evidence (25 Oct, main 0ae9313, `DATA_LAYER=local`)

4 of 10 incident questions failed for this reason. Investigator SQL from those runs:

| Question | Filter the Investigator wrote | What is stored | Result |
|---|---|---|---|
| Why did the share of boleto payments fall in Minas Gerais in March 2018? | `c.customer_state = 'Minas Gerais'` | two-letter codes such as `MG` | 0 rows -> "sample too small (0 records)" |
| Why did average freight cost for Rio de Janeiro orders rise in August 2018? | `customer_city = 'Rio de Janeiro'` | lower-case cities (`rio de janeiro`); a state question needs `customer_state` | baseline/observed null -> 0 records |
| Why did Rio de Janeiro's total revenue drop in late June 2018 (12-30 Jun, vs 1-11 Jun)? | the same city filter | as above | baseline 0.0, observed null |
| Why didn't the March 2018 paid-search seller cohort's revenue ramp up …? | `marketing.closed_deals WHERE business_segment = 'paid-search'` | the channel is `marketing_qualified_leads.origin` (`paid_search`), joined on `mql_id` | 0 rows |

## What changed

### 1. Value hints next to the schema (`app/data/value_hints.py`)

- The hints are built from the data and nothing is written by hand. For every text column
  (`VARCHAR`, `varchar(n)`, `string`, `text`) of every table, one aggregate query per table gives
  the distinct count, the min and max length, and how many values have upper-case or lower-case
  letters. One query per column then gives the most frequent values.
  - Up to 80 distinct values (`MAX_LISTED_VALUES`), ids excepted: every value is listed, most
    frequent first. This covers states, payment types, order status, categories (71), marketing
    origin, business segment, lead type and similar. The issue suggested about 50. I used 80 so
    the product categories are listed too.
  - Any other text column gets one line: the distinct count, the case or format, and 3 examples
    (most frequent first). The formats are `lower case`, `upper case`, `mixed case`,
    `32-char hex id` and `free text`. Example:
    `customer_city: "2633 distinct, lower case, e.g. 'sao paulo', 'rio de janeiro', 'belo horizonte'"`.
- **Both data layers.** `DataLayer.profile(sql, limit)` runs a profiling statement.
  - The local adapter runs it through the same guard and timeout, but with no query id from the
    run's sequence, no query-log line and no sample-mode replay.
  - The Zetaris adapter sends it through the USL with the same retry and local fallback as `query`,
    also unlogged.
  - So building the hints never shifts the run's query ids (`q001`, …). The prompts, and the
    sample-mode cache keys, are the same whether the hints were already cached or not.
- **Cached:** once per process, keyed by the adapter and the schema (tables, row counts, columns).
  An empty build, for example when the source was down, is not cached. On the sample data the
  build takes about 0.5 s.
- **Size cap:** the JSON is capped at `MAX_HINT_CHARS` = 10000. Past the cap, the longest value
  lists become summaries first, then trailing columns are dropped. On the sample data the hints are
  about 9.5k chars.
- `AgentContext(ground_filters=True)` puts the hints into `source_schemas()`, as `values` on each
  table. That is the payload both the Planner and the Investigator already get.
  - Both prompts then add `prompts/value_hints_note.md`, a short general rule: filter only on stored
    values, and map names in the question to them (a full name to the stored code, a hyphen or
    spaces to the stored spelling, the stored case). Use the column that holds that kind of segment.
  - There is no incident-specific mapping anywhere in `app/`.

### 2. Empty results (`app/agents/investigator.py`, `app/engines/markovian/orchestrator.py`)

- `matched_nothing(result)` decides when a result is empty.
  - Empty: no rows at all, or `value` / `baseline` both NULL or 0 with at least one NULL. The
    late-June case was baseline 0.0 with observed NULL.
  - Not empty: 0 in both windows, which is a measurement. A NULL window against a non-zero baseline
    is a real drop (Sprint 11c's area), so it is not empty either.
- When a measurement or change-check result is empty, the Investigator retries once:
  1. `check_values`: a new prompt, `investigator_check_values.md`. The model writes one
     `SELECT DISTINCT` (LIMIT 50) of the columns the query filtered on.
  2. That query runs, and the model gets its rows as `value_check`.
  3. `rewrite_sql`: the SQL prompt plus `investigator_rewrite_note.md`. The model rewrites the query
     using the stored values.
  4. The rewritten query runs, and `grounded` records whether it has records now.

  Each step is a trace line: `empty_result`, `check_values`, `rewrite_sql`, `grounded` and the
  `run_query` lines. The retry costs at most 2 extra tool calls, within `MAX_TOOL_CALLS`, and
  happens once per measurement. A rewrite that fails to run gets no further repair.
- If the result is still empty, the code writes the observation and makes no observe call. The
  finding reads `Filter matched no records (…), also after checking the stored values of the
  filtered columns; nothing was measured, so this is not a small sample.` It has no value and
  `supports` is empty. The outcome has `no_records`.
- In the orchestrator, a Critic `sample_too_small` with `sample_size` 0 (or missing) is set aside
  when it rests on such an observation: the one under critique, a follow-up result, or the change
  check.
  - The trace gets an `ignore_sample_flag` line.
  - The verdict stays `insufficient`, and its reason starts `Filter matched no records (obs-…)`.
  - The hypothesis is demoted without a revision chunk. The `skip_revision` line says "its filter
    matched no records".
  - The run does **not** end on the small-sample branch, so the other hypotheses are still tested.
  - The answer's limitations say `Not measured: H1 (…): the filter matched no records …` and
    `Change check not measured: Filter matched no records …`, not "Sample too small".
  - A real small sample (records > 0), or a 0-record flag on a result that did match records, is
    flagged as before.

### Scope: Markovian orchestrator only

`ground_filters` is on in the Markovian orchestrator, which is run.py's default and the path the
real runs took. The simple loop (`--loop simple`) keeps byte-identical prompts. That way the live
Meterless Day 1 recording, used by Plan check C, the README quick start and the browser check, stays
valid.

### Stub and sample cache

- `app/llm/stub.py` now answers the retry generically. The value check lists the first column the
  query compared with a literal. The rewrite returns the query unchanged, because the stub cannot
  map names.
- None of the recorded stub questions hits an empty result, so their runs are unchanged apart from
  the prompts.
- After Sprint 11c (#37) landed, main was merged into this branch. The Planner keeps both 11c's
  `hypothesis_checklist` payload and the value note. Neither branch's stub entries matched the
  combined prompts, so every `recorded_with: stub` entry was removed and re-recorded with
  `python scripts/record_stub_cache.py "<question>" --record-queries --run-id record-stub` for the
  questions CI replays, as in 11c:
  - Markovian: incident-01, -02 (Plan check J), -06, -09, -10, and "Why did order volume rise on
    21 September 2017?";
  - simple loop (`--loop simple`): the Day 1 question (plan checks C and I).

  That gives 87 stub entries: 56 have the same key and content as on main, 30 dead keys were removed
  and 31 are new. The 15 `recorded_with: meterless` entries are untouched. 11 query-row files were
  added (rows of the incident-01 and -02 Markovian queries that were not yet recorded; they hold the
  same rows DuckDB returns). The coordinator re-records the real caches after merge.

## Tests

- `tests/test_filter_values.py` (23 tests, no network):
  - **value hints on the sample data**: `MG` is in `orders.customers.customer_state` and
    `paid_search` is in `marketing_qualified_leads.origin`. `business_segment` has neither spelling.
    City is `lower case` with `'rio de janeiro'`, ids are `32-char hex id`, and the total is within
    the cap;
  - profiling takes no query id and writes no query-log line;
  - the hints are built once per schema (counting `profile` calls);
  - the cap logic works;
  - `values` appear only with `ground_filters`;
  - `matched_nothing` on 8 shapes;
  - **the four real-run cases** (parametrised), run on the real sample data with a scripted
    generator. Each one goes: wrong value, then 0 rows or NULLs, then `SELECT DISTINCT`, then the
    corrected query, then numbers. The test checks the exact trace sequence and 3 tool calls. It
    checks that the stored value was already in the first request's `sources`, and that the rewrite
    saw it in the check's rows;
  - still empty after the check: a `Filter matched no records` observation, no observe call,
    3 tool calls;
  - the retry within a tool-call cap of 1;
  - without `ground_filters`, an empty result is read as before;
  - orchestrator: a Day 1 change check with a title-case status filter is corrected, and the
    `Change` has numbers;
  - orchestrator: a change check and H1 that stay empty, with a Critic that reports 0 records. The
    flag is set aside (`ignore_sample_flag`), every hypothesis is still critiqued, and the summary
    does not say "sample". The limitations say "Not measured" and "Change check not measured";
  - orchestrator: a 0-record flag on results that did match records still ends the run as
    "Sample too small".
- `tests/test_answer_key_isolation.py` (2 new tests):
  - no file in `app/` holds an incident id, an answer-key seller id or category, or the question
    names "Minas Gerais", "Rio de Janeiro", "paid-search" / "paid search";
  - the new grounding module and prompts do not name a stored segment value (`MG`, `RJ`,
    `paid_search`, `boleto`).
- `tests/test_data_zetaris.py` (2 new tests, `httpx.MockTransport`): Zetaris `profile` goes through
  the USL with no query id and no log line, rejects a write, and falls back to local profiling on a
  503.
- `tests/test_prompts.py`: the three new prompts have a `Does:` / `Must not:` header (dropped
  before the model sees it) and are in the prompt-size registry with their size when added.
- Whole suite after merging main: `pytest -q` (748 passed). Plan checks C, J, L
  (`Score: 5/10 (answered 5, no_cache 5, errors 0)`, as on main) and N (all four `[PASS]`) were run
  locally in sample mode with the same outcomes as main.

## Known limits

- **The stub cannot show a correction.** In sample mode the stub's rewrite returns the same query.
  The corrected path is shown by the scripted tests, and in live runs by the model.
- **The value check is the model's.** The model chooses which columns to check. If it checks the
  wrong column, the rewrite has nothing to go on and the result is recorded as "filter matched no
  records". There is still only one retry.
- **Empty means NULL.** A wrong filter inside an expression that yields 0 in both windows (for
  example `count(*) FILTER (…)`) is read as a measurement of 0 and is not retried.
- **Hints cost prompt size.** About 9.5k chars are added to every Planner and Investigator request
  in the Markovian loop. The categories account for about 4k of that. Raising `MAX_LISTED_VALUES`
  or the data's cardinality makes the cap summarise lists.
- **The simple loop gets neither feature** (see Scope above).
- **Zetaris profiling was not run live.** There is no tunnel in this session; it is tested with
  mock REST responses only. It uses the same `to_usl_sql`, retry and fallback path as `query`.

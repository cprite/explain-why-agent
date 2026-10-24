# Sprint 9+10 — Critic agent and the three branches

Build-plan tasks 13 and 14, issue #27. The Critic now sits at the critic seam of the Markovian
orchestrator (Sprint 8, PR #22) and is the default there. The orchestrator gains the three branches
from architecture §4: no significant change, promotion after refutation, and cannot be determined.
Two items from the Sprint 8 review are fixed here as well.

## What was built

### The Critic (task 13)

- `app/agents/critic.py` and its prompt `app/agents/prompts/critic.md`. `Critic(settings)` is
  callable as a `CriticHook` and returns a `Verdict`. The other agents (planner, investigator,
  reporter) are modules built on `AgentContext` and `build_messages` in `app/agents/base.py`; there is
  no base class to subclass, so the Critic follows the same pattern. It is its own prompt and its own
  model call on the critic lane (`role="critic"`, so `METERLESS_MODEL_CRITIC`, default
  `meterless/fast`). It calls through the generator in the `CriticRequest`, never through the
  Investigator.
- **Input**:
  - the plan, and the measured change with the change check's result row (`spread`, `n`);
  - the hypothesis and the Investigator's observation;
  - the World Model `critique` payload for the hypothesis, built with the request's
    `context_builder` within `budget_chars` (the payload proved by plan check F);
  - the chunk's investigation state;
  - on a second critique, the follow-up tests with their results.

  The ContextBuilder names the run in its selection reasons, and its `used_chars` counts that name.
  The Critic therefore replaces the run id and passes only the items and the number of items cut.
  This keeps the prompt, and so the sample-mode cache key, the same for every run id.
- **Reply schema** `CritiqueDraft` (in `app/schemas.py`):
  - `checks`: each of the five disproof checks named exactly once (`alternative_cause`,
    `concentration`, `sample_size`, `date_basis`, `data_artefact`), each with `passed` / `failed` /
    `not_checked` and one sentence of detail;
  - `scores`: 0 to 3 on supported by the data, explains size and timing, and alternatives excluded;
  - `contradicted`, `reason`, up to three `follow_up_tests`, `sample_size` and the
    `observation_ids` relied on.
- **The verdict is decided in code, not by the model**:
  - contradicted: `refuted`, with the reason;
  - otherwise a total of 7 or more of 9: `supported`;
  - less than 7: `insufficient`, with the follow-up tests;
  - a reported sample size below `CRITIC_MIN_SAMPLE_SIZE`: `insufficient` with
    `sample_too_small`.

  A failed call, or a reply that does not validate, is asked for once more. A second invalid reply
  gives `insufficient` ("invalid twice"). The Critic never raises.
- **`Verdict`** keeps its four fields and gains optional ones with defaults: `scores`,
  `total_score`, `checks`, `observation_ids`, `query_ids`, `sample_size`, `sample_too_small`,
  `attempt` and `retry_count`. Verdicts that give only a verdict and a reason still validate.
- **Critique and revision** (in the orchestrator):
  - An `insufficient` verdict sends the hypothesis back to the Investigator once, in its own chunk
    (`kind: revision`). The Investigator gets each follow-up test (at most 2) as the hypothesis'
    test description, led by "Follow-up requested by the Critic: ". Its results are ingested into the
    World Model, tied to the hypothesis.
  - The second critique sees those results. A second `insufficient` demotes the hypothesis.
  - Revisions are capped at 1 per hypothesis (`MAX_REVISIONS`), and Critic calls at `max_chunks`
    per run.
- **World Model**: each verdict is stored as a new `verdict` entity, with a `judges` edge to the
  hypothesis and `relies_on` edges to the observations behind it. Those are the observations the
  Critic named, plus those from the queries it cites. Refuted hypotheses go into `ruled_out` with
  "H<n>: <reason>" and the query ids.
- **Default and no-op**: `run_markovian(..., critic=None)` now uses the real Critic.
  `critic=critic_hook` is the no-op and gives exactly the Sprint 8 behaviour (no verdicts,
  Reporter's causes as they are). Any other hook turns the Sprint 9 rules on.

### The branches (task 14)

Every branch decision is one `Orchestrator` / `branch` trace line with `branch`, `why` and `numbers`.

- **No significant change** (`no_significant_change`):
  - In the orchestrator, the change check's SQL request carries one more note
    (`prompts/change_check_note.md`). It asks for a `spread` column: the standard deviation of the
    measure across baseline periods as long as the window. It also asks for an `n` column: the
    records behind the measure in the window. The simple loop's prompts are unchanged.
  - The change is within normal variation when |observed − baseline| ≤ `CHANGE_VARIATION_THRESHOLD`
    × spread (default 2.0). Without a spread, the Investigator's reading of the change check
    decides, as before.
  - Within normal variation the run ends after chunk 1, with no hypothesis rounds and no Reporter
    call. The result has `change.significant: false` (and `change.spread`), `determinable: true`,
    no causes, `stop_reason: no_hypotheses`, and a one-line `summary` with observed, baseline and
    spread.
  - Otherwise a `significant_change` line records the same numbers (`change_not_decided` when the
    change check gave no reading).
- **Promotion after refutation** (`promotion`): when the leader is refuted or demoted, the next
  hypothesis in the Planner's order that is still standing becomes the leader. The line records
  `from`, `to`, `reason` and the total score.
- **Cannot be determined** (`cannot_be_determined`; otherwise `determined`). It applies when any of
  these holds:
  - every judged hypothesis was refuted or demoted;
  - the Critic flagged the sample as smaller than `CRITIC_MIN_SAMPLE_SIZE` (default 30). The flag
    stops the remaining rounds; the untested ones are listed in `limitations`;
  - `max_chunks` or `max_tool_calls` was reached without a supported leader;
  - none of the Reporter's causes is one the Critic supported.

  The result then has `determinable: false` and no causes, with the refuted in `ruled_out`. Each
  demoted or unconfirmed hypothesis is listed in `limitations` with its reason and "Data that would
  decide it: <the Critic's follow-up tests>". The sample flag adds a line naming the record count
  and the minimum.
- **Summary**: `Result.summary` is new and optional. The orchestrator writes it:
  - "Most likely cause (<type>): …" when determinable;
  - "No significant change: …" on that branch;
  - "Cannot be determined from the data: <why> (N tested, M ruled out)." otherwise. This wording
    names no hypothesis family, so it never asserts a cause.

  Like `stop_reason`, `summary` (and `change.spread`) is left out of the JSON when unset, so the
  simple loop's output keeps its Sprint 2 shape.
- The Reporter still writes the answer, but with a Critic only the causes it supported are kept,
  one per hypothesis. `ReportOutcome.cause_hypotheses` carries the hypothesis id behind each cause.

### Carried over from the Sprint 8 review

- **`max_tool_calls`** is a new `StopReason`. Reaching `MAX_TOOL_CALLS` with hypotheses left (before
  a round, or inside one) now stops with `stop_reason: max_tool_calls`, not `completed`. The note
  lists the untested ids.
- **Overall per-call deadline** (`app/llm/generator.py`). httpx timeouts are per phase, so a server
  that trickles its reply could outlast a bounded (`with_limits`) call. A bounded request now runs in
  a short-lived `generator-call` thread that reads the body chunk by chunk, and the caller stops
  waiting at the deadline with a `timeout` error. The thread stops at its next chunk, or by its own
  read timeout, which is never longer than the time that was left. Unbounded calls are unchanged.
  PR #26 (streamed Meterless replies) is still open and edits the same method. `run_by_deadline`
  takes any request function, so after that merge it wraps the streamed `_send` the same way.

## Sample-mode caches and CI

- The builder has no model credentials, so every new cache entry is recorded with the scripted
  stub and marked `recorded_with: stub`. `app/llm/stub.py` gained:
  - the Critic: a fixed, generic rule on the Investigator's reading. Effects of 30 % or more are
    supported; smaller ones are insufficient, with a timing follow-up and a split follow-up after
    it; records below the minimum fail the sample check;
  - two generic question shapes: review scores for a category, a seller or everything in a month
    (or its first half), and average order value declining since a month;
  - `spread` and `n` in every change check.

  It knows nothing about the planted incidents.
- Recorded with the following command (`<question>` as listed below):

  ```
  python scripts/record_stub_cache.py "<question>" --record-queries --run-id record-stub
  ```

  The questions are the plan check J question, the incident-06, -09 and -10 questions (verbatim from
  `eval/answer_key.json`) and "Why did order volume rise on 21 September 2017?". In total that is 61
  stub entries in `data/sample/llm_cache/` (55 new, 6 of the J question unchanged from Sprint 8) and
  15 new query-row files in `data/sample/query_cache/`.
- Six stub entries of the plan check J question that the new prompts no longer use were removed,
  with one stub-recorded query row (the old J change check, now with `spread` and `n`). The 15
  `recorded_with: meterless` Day 1 entries are untouched.
- A coordinator re-records these through Nightshift with
  `SAMPLE_MODE=false RECORD_CACHE=true python run.py "<question>"`.
- **No-op critic pins**: `tests/test_markovian_orchestrator.py` (the Sprint 8 mechanics on the
  Day 1 stub) pins `critic=critic_hook` in its `run()` helper. Its sample-replay test and every CI
  step run the real Critic. Plan checks C and I stay on `LOOP=simple`, as before.
- **Every CI step that existed on main was re-run on this branch and on `origin/main`, and the
  outputs diffed**:
  - plan checks A, B, D–H and the two World Model sample steps: identical;
  - plan check C: identical apart from the trace timestamps;
  - plan check I (HTTP API, on port 8765): identical apart from the generated run id;
  - plan check J: same answer (5/8 chunks, `completed`, top cause `logistics_delay`, `[PASS]`). Its
    size figures grow because the Critic adds one model call per round: `actual_sent` 9.9k–23k
    against 8.7k–12k before; `token_report` 7849 / 4153 / 47.1 % against 5730 / 4043 / 29.4 %. The
    largest chunk input is 5236 chars of the 12000 budget.

## Plan check L (new CI step)

L was the next free letter (J is on main, K is taken by PR #24). `scripts/check_critic_run.py
--question <incident>` prints the question string from the answer key, so CI does not retype it.
`scripts/check_critic_run.py RESULT --expect …` prints the run (status, summary, change, causes,
ruled out, limitations, one line per Critic call and per branch) and fails when the expectation does
not hold. Output on the build machine, shortened:

```
--- (a) incident-06: the Critic judges every hypothesis; delivery delay is refuted ---
question: Why did review scores for watches/gifts (relogios_presentes) fall in 2018-01?
status: success; stop_reason: completed; determinable: True
change: significant=True observed=1.8769 baseline=3.9975 spread=0.1935
causes: ['1. product_quality: Customers rated the products lower: scores fell even on orders delivered on time.']
critic calls: 4
  H1 logistics_delay attempt 1: refuted total 2/9 {... 0, 1, 1}
  H2 product_quality attempt 1: supported total 8/9 {... 3, 3, 2}
  H3 single_seller attempt 1: refuted total 2/9
  H4 data_artefact attempt 1: refuted total 2/9
  branch promotion: H1 refuted: ... purchase to delivery ... 12.8825 in the window against 13.6991 in the baseline (-6.0%). {'from': 'H1', 'to': 'H2', ...}
[PASS] refuted:logistics_delay: determinable=True, 1 causes, 4 Critic calls, stop_reason=completed
--- (b) incident-09: cannot be determined, no cause ---
summary: Cannot be determined from the data: the Critic flagged the sample as too small (3 records in the window, minimum 30) (1 tested, 0 ruled out).
  - Sample too small: 3 records behind the change in the window (CRITIC_MIN_SAMPLE_SIZE=30); more records for this segment, or a longer window, would decide it.
  - Not tested after the Critic flagged the sample as too small: H2, H3, H4.
[PASS] undeterminable: determinable=False, 0 causes, 1 Critic calls, stop_reason=completed
--- (b) incident-10: cannot be determined, no cause ---
summary: Cannot be determined from the data: every tested explanation was refuted or left unconfirmed by the Critic (4 tested, 3 ruled out).
  H1 price_discount attempt 1: insufficient total 5/9 -> follow-up: timing check on the second half of the window
  H1 price_discount attempt 2: insufficient total 5/9 (answered by q003: -8.1 %) -> demoted, promotion H1 -> H2
  H2 mix_shift, H3 single_seller, H4 data_artefact: refuted
  - Unconfirmed: H1 (price_discount) The effect (8%) is too small to explain the change on its own: ... Data that would decide it: Split the price_discount measure by state, category and seller ...
[PASS] undeterminable: determinable=False, 0 causes, 5 Critic calls, stop_reason=completed
--- (c) a change within normal variation: significant false, no causes ---
summary: No significant change: daily order count (distinct orders by purchase date) (all) was 111 in 2017-09-21 to 2017-09-22 against a baseline of 106.9 (spread 17.68), within 2 x the spread.
[PASS] no-change: determinable=True, 0 causes, 0 Critic calls, stop_reason=no_hypotheses
```

**(c), the question picked from the sample data**: "Why did order volume rise on 21 September
2017?". 21 September 2017 had 111 orders. The baseline, 14–20 September, had 121, 100, 82, 90,
133, 109 and 113 orders: mean 106.857, sample standard deviation 17.677. The difference is 4.14
orders, 0.23 spreads, inside the 2-spread threshold. Late September 2017 is one of the densely
sampled stretches of the sample, about 100 orders a day.

## Left out

- **Real-model caches.** Every new entry is a stub recording, so plan checks J and L show the
  mechanics (verdict rule, revision, branches, trace), not a model's critique. The stub's Critic
  marks concentration, date basis and data artefact `not_checked`; a real model fills them from
  the evidence.
- **The Day 1 question under the orchestrator** still has no recording (as in Sprint 8).
- **`summary` comes from the orchestrator, not from the Reporter's model.** Changing
  `reporter.md` would change the cache keys of the simple loop's live Day 1 recording.
- The architecture's "the Critic tries to disprove the *leading* explanation" is implemented as a
  critique of every hypothesis in its round, plus leader tracking for the promotion branch. Each
  round's critique fits in the same chunk, so the chunk cap is not spent on extra critique chunks.

## How it was tested

- `tests/test_critic.py` (37 tests, no network):
  - **the Critic alone**: its own prompt and call on the critic lane; the 7-of-9 rule; refuted on
    contradiction; the sample flag; an invalid reply retried once then insufficient (exactly two
    calls), and a valid retry accepted; every check named once; the follow-up results in the second
    critique; no run id in the prompt;
  - **acceptance criterion 2**: supported; insufficient → follow-up → supported (the revision chunk,
    the follow-up as the Investigator's task, its query in the second critique and the trace);
    insufficient twice → demoted (promotion H1 → H2, "Unconfirmed: H1" with the test that would decide
    it); refuted → next promoted (from, to, reason; `ruled_out` with the query ids); all refuted → no
    cause, and the summary names no ruled-out type;
  - **caps**: at `max_chunks` 2, 3, 4, 6 and 8 with a Critic that is never satisfied, Critic calls
    stay ≤ `max_chunks`, there is at most one revision per hypothesis and at most two critiques each.
    The cap also holds when the Reporter asks for follow-ups every time;
  - **branches**: within variation ends after chunk 1 with no rounds, no Critic and no Reporter call
    (the numbers are in the branch line and the summary). `CHANGE_VARIATION_THRESHOLD` from the
    environment changes the outcome. The defaults are in `.env.example`. A small sample (via
    `CRITIC_MIN_SAMPLE_SIZE`) gives determinable false and stops the rounds; `max_chunks` without a
    supported leader gives determinable false;
  - **trace**: one entry per Critic call with checks, scores, verdict, follow-up tests and the
    queries that answered them; one per branch decision with its numbers; verdicts in the World Model
    log with `judges` / `relies_on` edges by the Critic; the no-op critic keeps Sprint 8's behaviour;
  - **sample mode**: the four plan check L questions replay the committed cache, every call a hit;
  - **Sprint 8 review fixes**: `max_tool_calls` before a round and inside one; a reply trickled one
    byte every 50 ms (about 3.5 s in all) against a 0.5 s deadline returns `timeout` in under 0.9 s,
    and the request thread is gone within a second; a fast bounded reply still parses;
  - **incident wording**: `app/agents/prompts/` and `orchestrator.py` must not contain relogios,
    watches, strike, 1430239a or "average order value". One existing docstring said "the calling
    thread watches"; it now says "monitors".
- Updated tests:
  - `tests/test_markovian_orchestrator.py`: the no-op pin; the J replay runs with the real Critic;
    the no-change test now expects `determinable: true`, as task 14 specifies;
  - `tests/test_world_store.py`: the edge-type set includes the two new edges.
- Whole suite: `pytest -q` gives 442 passed under
  `systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0` (about 200 s on the build machine).
  `ruff check .` is clean.

## Known limits

- **Stub caches until re-recorded.** The verdicts in sample mode come from the scripted rule.
  In particular the "sample too small" outcome for incident-09 relies on the change check returning
  `n`, which the new note asks a real model for but cannot force.
- **Without a spread** (fewer than two baseline periods as long as the window, as for the
  incident-09 seller), significance falls back to the Investigator's reading. The no-change branch
  is then only as good as that reading.
- **The sample flag stops the run.** Architecture §4 says a too-small sample forces "cannot be
  determined". The flag is read from the `n` of the change, not of each hypothesis' sub-measure, so
  one thin sub-measure does not end a run.
- **An abandoned request thread** (deadline passed) can run for at most one more read timeout,
  which is never longer than the time that was left when the request started. Python cannot stop it
  sooner.
- **Critic calls add model calls**: about one per round, plus one per revision. With the defaults,
  `max_chunks` 8 allows at most 7.

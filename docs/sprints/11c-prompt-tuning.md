# Sprint 11c — Change check, hypothesis coverage and sample-size rule from the real Nightshift runs

Build-plan task 16, issue #35. Evidence: the coordinator's real runs of 25 Oct through Meterless
Nightshift (main 0ae9313, Markovian loop, Critic on, `DATA_LAYER=local`). The builder had no model
credentials: the real before and after scores and the re-recorded caches are the coordinator's step
after merge (see "Scores" and "Left out").

## Failed checks and their cause classes

| Incident | Failed check (real run) | Cause class (general) | Fixed in |
|---|---|---|---|
| incident-02 | change check: baseline 0.0301, observed 0.132, spread 0.1699, `significant: false`, stop `no_hypotheses` | **Wrong spread for a share**: the change-check SQL took the standard deviation of the per-record 0/1 flag (≈ sqrt(p(1-p))), not the variation of the period-level share. Applies to any share or rate metric. | code (`app/change_rules.py`, orchestrator) + `change_check_note.md` |
| incident-01 | cause_type: no supported cause; tested data_artefact, price_discount, mix_shift, single_seller; stop `max_chunks` | **Missing hypothesis family in the Planner**: no broad, cross-segment volume hypothesis and no breadth measurement. Applies to any count or revenue metric. | `HYPOTHESIS_CHECKLIST` (`app/agents/planner.py`) + `planner.md` |
| incident-03 | undeterminable: "13 records in the window, minimum 30" | **Critic check applied to the wrong count**: when the change is itself a fall in records, few records in the window are the finding. Applies to any drop in a count, revenue or volume. | code (`app/agents/critic.py` `sample_rule`) + `critic.md` |
| incident-10 | "No significant change … 142.7 … against 109.7 (spread not measured)" | **Branch decided without a measure**: with no spread, the Investigator's reading ended the run even for a 30 % change. Second cause: **wrong window basis** — one month for a question about a whole period ("since …"). | code (orchestrator relative rule) + `planner.md` (window) |

Still correct and kept (tests below): incident-09 (undeterminable, sample too small: 3 records, no fall
in records); "Why did order volume rise on 21 September 2017?" (no significant change, spread 17.68);
data_artefact refuted on Day 1.

## What was built

Every change, with the failed check and the cause class it addresses:

1. `app/change_rules.py` (new, pure functions) — incident-02, -10, -03.
   - `trusted_spread`: for a share (observed and baseline in [0, 1]) a spread larger than the baseline
     is rejected (`spread_rejected` in the branch numbers); it is replaced by the standard error
     sqrt(p(1-p)/n) with p = baseline and n = the change check's `n` (`spread_basis: standard_error`),
     or treated as not measured without `n`. With the incident-02 numbers and 606 deliveries in the
     week: spread 0.00694, the change is 14.7 spreads → significant.
   - Relative rule: without a trusted spread, a change larger than `CHANGE_VARIATION_THRESHOLD` × 10 %
     of the baseline (20 % at the default 2.0) is never read as no change: `significant` is null, branch
     `change_not_decided` with `decided_by: relative_change`, and the hypotheses are tested. Incident-10's
     numbers (142.7 vs 109.7, +30 %) now continue. A small change without a spread still ends as before.
   - `records_fell`: the change is a fall in records when the measure dropped to zero from a positive
     baseline, or when it fell and the window's records per day are below the baseline's by more than
     the same relative amount. A measure that rose is never a fall.
2. Orchestrator `_significance` uses the two rules above; the branch line carries the numbers
   (`spread_rejected`, `spread_basis`, `relative_change`, `relative_floor`). Documented in
   `.env.example` and `app/config.py` next to `CHANGE_VARIATION_THRESHOLD` (no new variable).
3. Critic `sample_rule` (code decides, not the model) — incident-03: when the change is a fall in
   records the rule counts window + baseline (`n` + `n_baseline`), or is not applied when the baseline
   count is unknown; otherwise it counts the window, as before. New optional `Verdict` fields
   `sample_basis` and `sample_counted`, also in the Critic's trace line; the "too small" messages say
   which records were counted.
4. Hypothesis checklist — incident-01: `HYPOTHESIS_CHECKLIST` in `app/agents/planner.py`, sent to the
   Planner as `hypothesis_checklist`: the standard families per kind of metric (count or revenue; share
   or rate; average per record) and the breadth test for `volume` (distinct sellers, categories and
   customer states active per day, window against baseline, and the share of them that moved the same
   way). No dates, no event names, no segment values.
5. Prompt changes (model text):
   - `planner.md` — incident-01: "Start from the `hypothesis_checklist` … For a count or revenue
     metric, always include `volume` … tested by breadth." Incident-10: "When the question names a
     period ('since <month>', 'over <period>'), the window spans all of it, not only its first part."
   - `change_check_note.md` — incident-02: "Compute the measure per period first; never take the
     deviation of per-record values (a share's 0/1 flags)", and a new column `n_baseline` (records in
     the baseline), which the sample rule needs — incident-03.
   - `critic.md` — incident-03: "When the change is itself a fall in records (compare `n` with
     `n_baseline`), few records in the window are the finding, not a weak sample; the code then counts
     the window and the baseline together."
6. Prompt headers (criterion 5): every prompt file starts with a two- or three-line HTML comment,
   "Does: … Must not: …". `load_prompt` drops it, so it never reaches the model and the four prompts
   whose text did not change (`chunk_note`, `investigator_observe`, `investigator_sql`, `reporter`) keep
   their cache keys. Model-text growth against 0ae9313: planner +25 %, change_check_note +31 %,
   critic +8 %, the rest 0 % (all within the 50 % limit; pinned by `tests/test_prompts.py`).
7. The scripted stub (`app/llm/stub.py`) follows the new change-check note (`n_baseline` in every
   change check) and the new Critic wording (a fall in records is not a failed sample check). Its
   planner already proposed the breadth hypothesis for order volume; its windows are unchanged.
8. Evaluation (`eval/run_eval.py`): the eval now runs the loop `run.py` runs (`--loop`, else `LOOP`,
   default `markovian`; before this sprint it always ran the simple loop, which has no Critic and no
   change branch, so none of the four fixes could show in its score). `--label before|after` writes
   `logs/eval-<label>-<timestamp>.json`; each row and the report list the model routes the replies
   came from (`model_routes`, e.g. `meterless:nvidia/…` or `stub:scripted-stub`), so a before/after
   pair can be checked for the same route. `.gitignore` lets `logs/eval-before-*.json` and
   `logs/eval-after-*.json` be committed.
9. CI plan check L now gates: `scripts/check_eval_score.py` fails when the score line is missing or
   differs from the newest committed `logs/eval-after-*.json`; while none is committed it reports the
   score only.
10. Sample cache: the 61 `recorded_with: stub` entries were re-recorded with
    `scripts/record_stub_cache.py`; 86 stub entries now cover the questions CI replays (32 kept the
    same key and content, 29 dead keys were removed, 54 are new) — incident-01, -02, -06, -09, -10 and
    the 21 September no-change question on the Markovian loop, and the Day 1 question on the simple
    loop (plan checks C and I). The 15 `recorded_with: meterless` entries are kept, unchanged; the
    Planner's prompt changed, so they no longer replay.

Changes that are general: all of them (10 of 10). None names an incident, a date, a segment value or
an event; `tests/test_no_incident_terms.py` enforces it for every file under `app/`.

## Scores

| | Before | After |
|---|---|---|
| Real model (Nightshift), `python eval/run_eval.py --label …` | not measured by the builder (no credentials); from the evidence: incident-01, -02, -03, -10 not found | coordinator, after merge |
| Sample mode, stub-recorded cache (`python eval/run_eval.py --sample`) | `Score: 0/10 (answered 1, no_cache 9, errors 0)` (main, simple loop) | `Score: 5/10 (answered 5, no_cache 5, errors 0)` |

The sample-mode numbers measure the plumbing, not a model: the "before" ran the simple loop on one
live Day-1 recording (rank-1 mix_shift, not found); the "after" replays the scripted stub on the
Markovian loop for the five questions it can answer (01, 02, 06, 09, 10 found; 03, 04, 05, 07, 08 have
no recording). Per check, after vs before: incident-01 cause_type FAIL → PASS (segment, window and
wrong-explanation PASS both times); incident-02, -06, -09, -10 no_cache → found; no incident went
from found to not found. The stub's score is not evidence that the prompts are better, and is not the
"after score" of criterion 2: the coordinator's recorded run is.

## How it was tested

- `tests/test_nightshift_fixes.py` — the four fixes with a scripted generator and the real numbers:
  incident-02 (0.0301 / 0.132 / 0.1699: the old rule's "within 2 spreads"; with `n` = 606 the spread
  becomes the standard error and the change is significant; without `n` the relative rule continues the
  run); incident-01 (the Planner receives the checklist with the breadth test; the planner prompt
  requires `volume`; a plan with the breadth hypothesis ends with `volume` supported); incident-03
  (13 records in the window: window + baseline counted, or the rule not applied without a baseline
  count; 2 + 9 records still too few); incident-09 style (3 records, no fall in records: still flagged);
  incident-10 (142.7 vs 109.7 without a spread: hypotheses tested; 111 vs 106.9 without a spread: still
  no change; the relative rule follows `CHANGE_VARIATION_THRESHOLD`).
- `tests/test_change_rules.py` — the pure rules, edge cases included.
- `tests/test_no_incident_terms.py` — criterion 4; terms read from `eval/answer_key.json` at test time.
- `tests/test_prompts.py` — criterion 5: headers and growth.
- `tests/test_eval_score_gate.py` — the CI gate and the `.gitignore` exceptions.
- Existing tests kept green: the sample replays of plan checks C, I, J and N (incident-06 refutes
  delivery delay, incident-09 and -10 undeterminable, the 21 September question no change with
  spread 17.68), the Critic and orchestrator suites.
- See the PR for the full `pytest` and `ruff` results.

## Left out

- Real before/after evaluation and the re-recording of the sample cache through Meterless (criteria
  2, 6, 7): the coordinator's step after merge, e.g.
  `SAMPLE_MODE=false RECORD_CACHE=true python eval/run_eval.py --label after`, then commit
  `logs/eval-after-*.json` and the new `data/sample/llm_cache/` entries; CI then gates on that score.
- Incidents 04–08 evidence (still recording when the issue was written).
- No code check that a plan for a count or revenue metric contains `volume`: classifying a metric from
  its free-text name in code would be a guess; the checklist and the prompt carry it.
- The stub's windows were not changed to follow the new "whole period" rule (its trend question keeps
  one month), so the plan check N replay of incident-10 stays comparable.

## Known limits

- **The prompts were tuned against the same ten incidents they are scored on, so the after score is an
  optimistic estimate.** All 10 changes are general (none names an incident); none was judged
  incident-specific.
- Until the coordinator re-records, the sample cache for every CI question is the scripted stub, not a
  model; the Day 1 question no longer replays the live 23 Oct recording, and the committed `result.json`
  (that recording's answer) is not reproduced in sample mode until then.
- The share guard only catches the per-record spread when it exceeds the baseline (true for any share
  below 0.5 with the per-record deviation); for shares above 0.5 a per-record spread can still slip
  through. The prompt asks for the period-level spread in every case.
- `records_fell` compares records per day; with the sample data's uneven sampling (whole weeks nearly
  empty) a per-day rate can fall for reasons of sampling, not of the business.
- The relative rule (10 % of the threshold) is a convention, not a statistical test.

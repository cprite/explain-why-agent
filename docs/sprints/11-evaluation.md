# Sprint 11 — Evaluation script scoring results against the answer key

Build-plan task 15, issue #17. Nothing under `app/`, `run.py` or the recorded caches changed.

## What was built

- `eval/scoring.py`: `score(result, incident) -> dict`, a pure function (no file, model or data
  access). Per determinable incident four checks, each pass / fail / n/a with a reason:
  - **cause_type**: the rank-1 cause's `type` is in the key's `cause_types`; when the key lists
    more than one (incident-08: `volume` + `price_discount`) every listed type must appear among
    `causes`. A key type missing from `CauseType` fails with `cause_type_not_in_vocabulary: <type>`.
  - **segment**: `change.segment` (a free string) is matched case-insensitively, accents folded,
    `_` read as a space, on whole words: a state by code or name (`RJ`, `Rio de Janeiro`), a seller
    id, a category name; a national incident by words for the whole marketplace (`all`, `overall`,
    `national`, `marketplace-wide`, `multiple states` …); the marketing cohort by its channel
    (`paid_search`).
  - **window**: the first and last ISO date in `change.window` (a free string; one date = one day)
    must overlap `window_start`..`window_end`, both ends inclusive, so touching on one day counts.
    No valid ISO date (`August 2018`, `2018-08`, `2018-02-30`) fails with `unparseable window: …`.
  - **wrong_explanation**: the incident's wrong-explanation type is in `ruled_out`; n/a when no
    `CauseType` fits it.

  Found = cause_type, segment and window pass. Undeterminable incidents (09, 10) are found when the
  result is `determinable: false` with no cause. A `cache_miss` error is `no_cache`, any other error
  result `error`.
- `eval/wrong_explanation_types.json` (eval-only): one `CauseType` (or `null`) per incident with a
  one-line reason: 01 `data_artefact`, 02 `single_seller`, 03 `volume`, 04 `mix_shift` (heavier
  orders = a shift in what is shipped), 05 `volume`, 06 `logistics_delay`, 07 `volume` (seasonal
  demand), 08 `single_seller`, 09 and 10 `null` ("any confident single-cause story", "any
  single-segment explanation" name no single family).
- `eval/run_eval.py [--sample] [--only ID …] [--timeout S] [--total-timeout S]`: each question runs
  in a child process with the `run.py` wiring (`LocalDataLayer` + `Generator` +
  `run_investigation`), so the per-question timeout really stops it. A timed-out, crashed or
  unparseable question is an `error` row with the reason, and the run goes on; questions not
  started before the total cap are `run_cap_reached`. Prints the table (id, status, the four checks,
  undeterminable, run time, tokens summed from the run's trace), a detail block with every check's
  reason, the run id and trace file, the vocabulary gap line, and last
  `Score: N/10 (answered A, no_cache M, errors E)`. Writes the same to `logs/eval-<timestamp>.json`
  with run ids, trace files and query logs. Exit 0 whenever scoring finished; 2 on bad arguments.
- Configuration in `.env.example`: `EVAL_QUESTION_TIMEOUT_SECONDS` (600), `EVAL_TOTAL_TIMEOUT_SECONDS`
  (3600). Read by the eval itself (not `app/config.py`, which this sprint does not touch).
- CI plan check I: `python eval/run_eval.py --sample`, then the last line must match the score
  pattern. The score is reported, not gated.

## Left out

- Scanner recall (how many planted incidents the anomaly scanner flags unprompted) comes with
  task 19a.
- No cause-vocabulary change for `freight_cost`: the planner prompt contains the vocabulary, so a
  change would alter the cache keys and break the recorded Day-1 run.

## How it was tested

- `ruff check .` → `All checks passed!`; `pytest -q` → `167 passed` locally (Python 3.13, arm64).
- `tests/test_eval_scoring.py`: correct cause (found); wrong type; incident-08 answered with only
  `volume` (not found) and with both (found); wrong segment; window outside; wrong explanation
  missing from `ruled_out` (check d fails, still found); undeterminable with a cause (not found),
  with `determinable: false` (found), determinable without cause (not found); `cache_miss` →
  `no_cache` (also for an undeterminable incident); other errors → `error`; a result without
  `change`. Window edges: touching on the first and last key day pass, the day before / after fail,
  one date, a containing window; unparseable strings fail with a reason. Segments: `RJ`, `rj`,
  `customer_state = 'RJ'`, `Rio de Janeiro` in any case pass, `SP`, `BRJ` fail; `São Paulo` with an
  accent; seller id in upper case; category with `_` or spaces; national and cohort rules. The
  vocabulary test lists the key types missing from `CauseType` (today `{'incident-04':
  ['freight_cost']}`) and checks the eval reports exactly those; it does not fail on the gap. The
  mapping file covers every incident with valid types. `scoring.py` opens no file.
- `tests/test_eval_run.py`: crash, timeout and `run_cap_reached` rows with the run continuing; a
  real child process killed at a 0.05 s timeout; timeouts from the environment with defaults and in
  `.env.example`; **incident-01 through the eval equals the committed `result.json` from main**
  except run-specific fields (run id, paths, time); the CLI with `--only incident-01 incident-04
  incident-09` (table, detail, gap line, score line, JSON report with run ids and trace files);
  an unknown id exits 2.
- `tests/test_answer_key_isolation.py`: no file under `app/` mentions `answer_key` or holds a
  path-like string literal under `eval/` (the detector itself is tested on positive and negative
  cases).
- Plan check, `python eval/run_eval.py --sample` (local run, ~20 s):

  ```
  incident-01  not_found  FAIL  PASS  PASS  PASS  -  1.9  129113
  incident-02..10  no_cache
  cause_type: FAIL - rank-1 cause mix_shift not in ['volume']
  cause_type_not_in_vocabulary: freight_cost (incident-04)
  Score: 0/10 (answered 1, no_cache 9, errors 0)
  ```

## Known limits

- Nine of ten questions have no recorded model replies yet, so sample mode answers only
  incident-01. Its recorded answer ranks `mix_shift` first (`volume` is not among the causes), so it
  scores not found on the cause type, while segment, window and the ruled-out `data_artefact` pass.
  The score in sample mode is 0/10 until more runs are recorded.
- `freight_cost` (incident-04) is not in the `CauseType` vocabulary, so incident-04 cannot be found
  until the vocabulary (and the recorded cache with it) changes.
- Segment matching for free-text segments is a heuristic: a national incident accepts any segment
  with a marketplace-wide word, even "all orders in RJ"; the wrong-explanation mapping is a judgement
  call, one type per incident.
- Run time includes the child process start (≈1.5 s of Python and DuckDB loading per question).

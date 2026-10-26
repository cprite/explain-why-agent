# Sprint 17 — Evaluation with replies recorded from Nemotron through Nightshift

Built on main 853304c (after #40). Every model reply the evaluation needs was recorded live on the
Raspberry Pi through Meterless Nightshift (routes `nemotron-3.5-lightning-30b-a3b` and
`nemotron-3.5-super-vl-120b-a12b`), on 25 Oct 2026. The replies are committed so anyone can replay
the run without a key.

## What changed

- `data/recorded/nemotron/llm_cache/`: the 206 cache entries the evaluation replays. Every entry has
  `recorded_with: meterless` and a Nightshift receipt id. They live in their own folder because a
  live recording overwrites a stub-recorded entry with the same key; `data/sample/llm_cache/` (the
  scripted stand-in, used by the quick start and the tests) is unchanged.
- `data/sample/query_cache/`: the 85 query results recorded with those replies (new files only; the
  committed entries are unchanged). Sample mode swaps in the recorded rows, so the model sees the
  rows it saw while recording. Without them the replay depended on DuckDB returning the same rows:
  it did on Linux, but on macOS a few results differed (tie order, one row fewer) and five questions
  missed their Critic replies.
- `logs/eval-after-20261025T235356Z.json`: the scored replay of those entries.
- `app/schemas.py`: `CauseDraft` takes its `observation_ids` from its statements when the model left
  the cause-level list out. Nemotron did this on incident-03 and incident-05 (the ids were on every
  statement, only the cause-level copy was missing), and the Reporter failed with `invalid_json`
  after its repair call. The JSON schema sent to the model is unchanged, so no cache key changed.
  Test: `tests/test_schemas.py::test_cause_draft_takes_ids_from_statements`.
- README Results: the model-recorded score row now has a value and a source.

## Result

| Run | Score |
|---|---|
| Sample mode, Nemotron-recorded replies (`LLM_CACHE_DIR=data/recorded/nemotron/llm_cache`) | Score: 5/10 (answered 10, no_cache 0, errors 0) |
| Sample mode, stub-recorded replies (default cache, unchanged) | Score: 5/10 (answered 5, no_cache 5, errors 0) |

Per incident (Nemotron-recorded replies):

| Incident | Result | What the agent concluded |
|---|---|---|
| incident-01 | found | volume: broad, marketplace-wide spike |
| incident-02 | found | logistics_delay across sellers and categories |
| incident-03 | not_found | cannot be determined: the Critic flagged the window sample as too small |
| incident-04 | not_found | cannot be determined: the Reporter did not report the two supported hypotheses; the answer key's `freight_cost` is not in the cause vocabulary, so this incident cannot pass as the key stands |
| incident-05 | found | mix_shift for Minas Gerais customers |
| incident-06 | not_found | cannot be determined: max_chunks reached without a supported explanation |
| incident-07 | not_found | cannot be determined: the Critic flagged the cohort sample as too small |
| incident-08 | not_found | price_discount found, the volume part of the answer missing |
| incident-09 | found | correctly undeterminable |
| incident-10 | found | correctly undeterminable |

## How it was recorded

`SAMPLE_MODE=false RECORD_CACHE=true RECORD_REUSE_EXISTING=true MODEL_PROVIDER=meterless`, local
DuckDB data, one question per detached worker, three workers. While recording, Nightshift's cloud
fetch deadline was raised from 45 s to 180 s (about 40 % of calls hit it at 45 s on the long
Planner and Critic prompts); it was set back to 45 s afterwards. A question that had a failed model
call does not replay (failed calls are not cached), so incidents 01, 02, 03 and 06 were re-run
until every call on their path was recorded. Each incident was recorded on its own path once the
calls succeeded; no run was repeated to get a better answer.

## How to test

```
LLM_CACHE_DIR=data/recorded/nemotron/llm_cache SAMPLE_MODE=true python eval/run_eval.py --sample
```

Expected: `Score: 5/10 (answered 10, no_cache 0, errors 0)`, with `model_routes` naming the two
Nemotron routes. Without `LLM_CACHE_DIR` the default sample mode still prints
`Score: 5/10 (answered 5, no_cache 5, errors 0)`, and the full test suite passes.

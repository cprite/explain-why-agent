# Sprint 7 — Markovian engine: config, chunk manager and carryover cascade

Build-plan task 11, issue #12. The building blocks of the Markovian engine from architecture §5.2,
in `app/engines/markovian/`. The orchestrator that uses them is task 12; the simple loop in
`app/loop.py` is unchanged.

## What was built

- `config.py` — `MarkovianConfig`, read by `MarkovianConfig.from_env()` from:

  | Variable | Default | Allowed |
  |---|---|---|
  | `MARKOVIAN_MAX_CHUNKS` | 8 | 1–50 |
  | `MARKOVIAN_CHUNK_BUDGET_CHARS` | 12000 | 1000–200000 |
  | `MARKOVIAN_CARRYOVER_BUDGET_CHARS` | 1200 | 200–100000, at most half the chunk budget |
  | `MARKOVIAN_CHUNK_TIMEOUT_SECONDS` | 180 | >0, ≤3600 (enforced by the orchestrator) |
  | `MARKOVIAN_COMPRESSION_TIMEOUT_SECONDS` | 30 | >0, ≤600, ≤ the chunk timeout |

  Unset or blank variables take the default. Anything else invalid raises `MarkovianConfigError`
  listing each bad variable with its value and the rule, e.g.
  `invalid Markovian configuration: MARKOVIAN_MAX_CHUNKS='0': Input should be greater than or equal to 1`.
  Documented in `.env.example`. Budgets are in characters; the token report converts with the
  guide's `ceil(chars / 4)`.
- `chunks.py` — `ChunkManager`:
  - `start_chunk(goal, carryover=, context=, label=)` builds the input for the next chunk: goal
    (clipped to a quarter of the budget on chunk 1, to 300 chars afterwards), the rendered
    carryover, then the ContextBuilder's evidence items in the order given, one line each with id,
    type, summary and selection reason. An item that does not fit in what is left is dropped and
    recorded; smaller items after it are still tried. The input never exceeds
    `chunk_budget_chars` (a final cut guarantees it even though a valid config cannot reach it).
  - Starting chunk `max_chunks + 1` raises `ChunkCapError` (the refused chunk is not recorded);
    `can_start()` and `rounds_left` let the orchestrator stop before that.
  - Per chunk, a `ChunkRecord`: `projected_chars` (the input built here), `standard_chars` (the
    same chunk with a growing conversation: full goal + all selected items + every earlier chunk's
    output), `actual_sent_chars` and `output_chars` (reported back with `finish_chunk`), the
    carryover step, items included and dropped. `report()` adds `ceil(chars/4)` token estimates.
  - `ContextItem` / `ContextPayload` are small Protocols (`items` with `id`, `type`, `summary`,
    `selection_reason`; `budget_chars`; `used_chars`). The World Model sprint's ContextBuilder is
    not on main yet; tests use a stub dataclass and the orchestrator sprint wires the real one.
- `carryover.py` — the state passed between chunks: ranking (id + note), ruled out (id + reason),
  open questions, rounds left; rendered as a few short lines, and `used_chars` is the length of
  that rendering (what the next chunk actually reads). `build_carryover(round_output, config=,
  rounds_left=, generate=, previous=, goal=, run_id=)` runs the cascade; each step runs only if
  the one before failed or came out over `carryover_budget_chars`:
  1. `explicit_state` — the round's structured state validated against `CarryoverDraft`
     (pydantic, extra fields forbidden, ≤6 items per list, not empty);
  2. `model_compression` — one call through the injected `GenerateFn` (role `compressor`,
     schema `CarryoverDraft`) with goal, previous carryover and a preview of the round capped at
     the chunk budget; the reply is re-validated; a wall-clock timeout of
     `compression_timeout_seconds` runs the call in a worker thread. Raising, an error result,
     invalid JSON, a schema mismatch, an empty state or a timeout all move on;
  3. `heuristic_extraction` — deterministic line patterns: rejection words ("ruled out",
     "refuted", "not supported", …) make a ruled-out item (and remove that id from the ranking);
     numbered lines or lines starting "leading", "supported", "cause 1", … make ranking items;
     questions and "open question / follow-up / next check" lines make open questions. Items are
     clipped to 200 chars; trailing items are dropped (open questions first, then ruled out, then
     the ranking tail) until it fits; nothing extractable fails;
  4. `truncation` — the round text (or the previous carryover if the round text is empty) cut at a
     word boundary to fill the budget. Always succeeds.

  The result records `carryover_step` and every `StepAttempt` (step, ok / failed / over_budget,
  detail, size). This package makes no HTTP calls; the generator is injected.
- Sample mode: `python -m app.engines.markovian.carryover --sample` takes the first recorded
  Reporter reply with `complete: false` from `data/sample/llm_cache/` (a real Meterless recording
  for the Day 1 question), turns it into a round (transcript text plus structured state) and runs
  the cascade four times with a stub generator, forcing each fallback: A explicit state, B no
  state → compression, C invalid state + generator raises → heuristic, D invalid state + non-JSON
  reply + no verdict lines → truncation. It prints each step tried and the final carryover.

## Deliberately left out

- The orchestrator (task 12): the loop over chunks, the per-chunk timeout enforcement, abort,
  `logs/markovian-<run>.jsonl` and the token report in the result. The building blocks expose
  what it needs (`ChunkManager.report()`, `Carryover.to_dict()`).
- The round-output format the agents will produce. `RoundOutput(text, state)` is the seam; the
  orchestrator decides how the Investigator/Critic reply maps to `state`.
- Marker protocol (`[STATE_CHECKPOINT]`) from the guide: rounds here return structured JSON, so
  step 1 reads a structured field instead of parsing text after a marker.
- No change to `app/loop.py`, `app/engines/world_model/` or any existing module.

## How it was tested

- `tests/test_markovian_config.py`: defaults, process-environment and mapping overrides, blank
  values, 11 invalid cases (range, type, cross-field) with the variable named in the error, every
  variable documented in `.env.example`.
- `tests/test_markovian_chunks.py`: a payload of ~13,000 chars against a 2,000-char budget (cut,
  drops recorded, ranked order kept), a huge item skipped while smaller ones fit, budgets
  1000–12000 with a 14,000-char goal, a full carryover and 100 items × 500 chars over every chunk,
  continuation goal clipping, the chunk cap error, `finish_chunk` and `report()`.
- `tests/test_markovian_carryover.py` — the plan check. It forces step 1 to fail (missing, wrong
  type, missing reason, unknown field, empty, not an object, over budget), step 2 to fail (stub
  raises, error result, invalid JSON, schema mismatch, empty reply, 1.5 s stall against a 0.2 s
  timeout, no generator, over budget, and the real `Generator` in sample mode with an empty cache),
  step 3 to fail (numbers only, empty text, short lines, nothing fits) and asserts the next step is
  used and the result is within budget; truncation is checked at budgets 200–5000 on 50,000 chars;
  36 parametrised cases × 3 round texts check the budget for every combination of state, generator behaviour and budget. Each case prints one line; CI runs the
  file with `-s` ("Plan check G") and greps them. Output on the build machine:

  ```
  PLAN-CHECK step1 valid explicit state: step=explicit_state used_chars/budget_chars=207/600 tried=[explicit_state:ok]
  PLAN-CHECK step1 fails (wrong type) -> step2: step=model_compression used_chars/budget_chars=70/600 tried=[explicit_state:failed, model_compression:ok]
  PLAN-CHECK step1 over budget -> step2: step=model_compression used_chars/budget_chars=70/200 tried=[explicit_state:over_budget, model_compression:ok]
  PLAN-CHECK step2 fails (generator raises) -> step3: step=heuristic_extraction used_chars/budget_chars=382/600 tried=[explicit_state:failed, model_compression:failed, heuristic_extraction:ok]
  PLAN-CHECK step2 fails (invalid JSON) -> step3: step=heuristic_extraction used_chars/budget_chars=382/600 tried=[...]
  PLAN-CHECK step2 fails (times out) -> step3: step=heuristic_extraction used_chars/budget_chars=382/600 tried=[...]
  PLAN-CHECK step2 over budget -> step3: step=heuristic_extraction used_chars/budget_chars=283/300 tried=[explicit_state:failed, model_compression:over_budget, heuristic_extraction:ok]
  PLAN-CHECK step3 fails (numbers only) -> step4: step=truncation used_chars/budget_chars=114/600 tried=[..., heuristic_extraction:failed, truncation:ok]
  PLAN-CHECK step3 nothing fits -> step4: step=truncation used_chars/budget_chars=200/200 tried=[...]
  PLAN-CHECK step4 truncation of 50k chars at budget 1200: step=truncation used_chars/budget_chars=1187/1200 tried=[...]
  ```

  (27 lines in all; abridged here.)
- Sample mode runs in CI ("Plan check H") and in a test; it exits non-zero if any case does not end
  on its expected step or exceeds the budget.
- Whole suite: `pytest -q` 214 passed; `ruff check .` clean.

## Known limits

- Budgets are characters, not tokens; the token figures are the guide's `chars/4` estimate.
- The compression timeout abandons the worker (daemon) thread rather than killing it (Python cannot stop a
  thread); the generator's own HTTP timeouts end the call later. The cascade itself returns on time.
- The heuristic is English-pattern based and line-oriented; prose that states a verdict without
  those words is not picked up and falls through to truncation.
- Truncation keeps the head of the round text, so a verdict at the end of a long round is lost at
  that step.
- In sample mode the compressor is a stub with a fixed reply: step 2's prompt has not yet been run
  against a live model. A recorded compressor reply belongs with the orchestrator's cache recording
  in task 12.
- `ContextPayload` is a guess at the ContextBuilder's shape (from the issue); if task 9 names
  fields differently, an adapter in the orchestrator is needed.

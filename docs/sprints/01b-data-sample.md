# Sprint 1b — Data sample README and row-count check

## What was built

- `data/sample/README.md`: documents the four source folders, every CSV with its
  data-row count, Kaggle sources, CC BY-NC-SA 4.0 attribution, planted incidents
  (8 synthetic + 2 real) pointed at `eval/answer_key.json`, the no-extra-PII note,
  and regenerate steps via `data-prep/` plus the research plan.
- `tests/test_sample_data.py`: stdlib-only checks for exact CSV row counts, answer
  key shape (10 incidents with `id` and `question`), and the Black Friday premise
  (1176 orders on 2017-11-24; 20–23 Nov daily average between 230 and 240).
- This sprint note.

## Deliberately left out

- No changes to CSVs under `data/sample/`, to `eval/answer_key.json`, or to
  `data-prep/` (scripts still land via open PR #4).
- No DuckDB adapter, agents, or evaluation runner (later sprints).
- No update to `docs/PRE-EXISTING.md` (already declares the sample and answer key;
  standing rule: only add this sprint note under `docs/`).

## How it was tested

- Local: `python3 -m venv /tmp/ewa-venv && source /tmp/ewa-venv/bin/activate`,
  `pip install -r requirements.txt`, `ruff check .` → `All checks passed!`,
  `pytest -q` → `8 passed in 1.47s` (local; CI timing may differ). New tests:
  `test_sample_csv_row_counts`, `test_answer_key_has_ten_incidents_with_id_and_question`,
  `test_black_friday_order_volume_premise`.
- Plan check (build-plan task 2): row counts match the README table; incident-1
  premise reproduced in `test_black_friday_order_volume_premise`.

## Known limits

- `data-prep/` may not be on `main` until PR #4 merges; the README still points at
  those scripts as the regeneration path.
- Review text contains embedded newlines; row counts must use the CSV module, not
  raw line counts.
- The agent must not read `eval/answer_key.json` during investigation; that
  constraint is documented, not enforced in code yet.

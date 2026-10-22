# Sprint 1 — Repository skeleton and CI

## What was built

- Package layout under `app/` (`agents/`, `agents/prompts/`, `engines/world_model/`,
  `engines/markovian/`, `data/`, `llm/`) each with `__init__.py`, plus empty
  `data/sample/`, `eval/`, `input_examples/`, `output_examples/`, `logs/`, `web/`
  kept with `.gitkeep`.
- `app/config.py`: settings from environment variables via pydantic-settings, with
  the defaults listed in the sprint issue; missing keys do not raise at import;
  empty env values are ignored (`env_ignore_empty=True`) so they fall back to defaults.
- Pinned `requirements.txt` (Python 3.11), `.env.example`, `.gitignore`, MIT
  `LICENSE` (copyright Nikolay).
- Placeholder `run.py` that prints JSON
  `{"status": "not_implemented", "sample_mode": <bool>, "question": "..."}` and
  exits 0.
- GitHub Actions workflow `.github/workflows/ci.yml`: Python 3.11, install deps,
  `ruff check .`, `pytest -q`, 10-minute job timeout, on push and pull_request.
- Tests for config defaults/overrides/empty-env fallback, import without env keys,
  and `run.py` behaviour with settings vars cleared.

## Deliberately left out

- Data import and `data/sample` contents (sprint 2).
- DuckDB / Zetaris adapters (sprint 3 / 10).
- Model generator, schemas, agents, and a real `run.py` loop (sprints 4–6).
- README, Dockerfile, `metadata.json`, and product modules named in architecture §12
  (later sprints).

## How it was tested

- Local: `python3.11 -m venv .venv && source .venv/bin/activate`,
  `pip install -r requirements.txt`, `ruff check .` (prints `All checks passed!`),
  `pytest -q` (prints `5 passed in …s`),
  `python run.py "Why did order volume spike?"` prints the placeholder JSON.
- Plan check (build-plan task 1): CI green with lint and the skeleton test suite;
  the CI log shows `All checks passed!` from ruff and the pytest summary line
  `5 passed in …s`.

## Known limits

- `run.py` does not investigate; it only reports settings and the question.
- No data, model calls, or HTTP API yet.
- `SAMPLE_MODE` defaults to `true` for this skeleton; live-default behaviour arrives
  with the model/data layers.

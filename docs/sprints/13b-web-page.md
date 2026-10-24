# Sprint 13b — Web page: anomaly board and result view

Build-plan task 19, issue #23. Build-plan cut #1 is in force (applied 22 Oct 23:17Z): no live trace on
the page; the full trace is a download link.

## What was built

- `GET /anomalies` (`app/api/main.py`, cache in `app/api/anomalies.py`):
  - without parameters: `{"generated_at", "timed_out", "episodes_found", "cards": [overall top ten
    AnomalyCard], "by_metric": [MetricBoard, config order, top 3 each]}`, straight from the scanner's
    `ScanReport`.
  - `?metric=KEY&limit=N` (N from 1, capped at 25, default 10): one `MetricBoard` with that metric's
    flagged episodes ranked within the metric. The list is the scanner's own merged ranking cut per
    metric family, with cards built by the scanner's `build_card` (rank within the metric,
    `overall_rank` kept), computed at scan time from `ScanResult.candidates`. Its first cards are
    the board's cards. Cards beyond the board's top 3 that were not among the 40 attributed episodes
    have `top_attribution: null`; no extra attribution query is run for them.
  - The scan runs on first use and is cached in memory; `?refresh=true` recomputes. A scan takes the
    API's run lock without waiting, so it never runs next to an investigation (one DuckDB instance at
    a time): `busy` (429) when a run or another scan holds it. The cached board is still served while
    a run goes on. `app.scanner.db.default_database().close()` runs after every scan, so the
    scanner's connection and its DuckDB file are gone until the next scan. A scan that raises
    releases the lock, is not cached and answers `run_failed` (500, exception type only).
  - Unknown metric: `not_found` (404); `limit` below 1 or not a number: `invalid_input` (422).
- `POST /run` also takes `{"anomaly_id": "<card id>", "options": {...}}`. The id is looked up in the
  cached board (top ten, per-metric board and the expanded per-metric lists; a scan runs first if
  none is cached), and the card's pre-filled `question` goes through the same `execute_run` as a
  typed question. Unknown id: `not_found` (404); both `anomaly_id` and `input`: `invalid_input`
  (400); neither: `invalid_input` (422) as before; `input.anomaly_id` is still rejected (422).
- `GET /` serves `web/index.html`; `GET /web/app.js` and `GET /web/style.css` its two assets. The
  page's client-side run wait is `API_RUN_TIMEOUT_SECONDS`, written into a `<meta>` tag when `/` is
  served. No login, no build step, no CDN, no request to another host.
- The page (`web/index.html`, `web/app.js`, `web/style.css`, vanilla JS, inline SVG spinner):
  1. Board: the overall top ten, then one tile per configured metric with its flagged-episode count
     and its top cards. "Show more" on a tile loads `?metric=KEY&limit=25` into the tile. Each card
     shows metric, segment, period, baseline → observed, signed change and %, the top attribution
     when present, and an "Explain" button. A text box and "Ask" for a typed question. While the
     first scan runs the board says so; a busy answer is retried every 3 s, at most 40 times.
  2. While a run goes: the Explain and Ask buttons are disabled; a spinner and elapsed seconds
     show. Structured errors become one readable line: `cache_miss` → "No recorded answer for this
     question in sample mode (cache_miss).", `busy` → "Another run is in progress…", any other
     code → its message and code; a non-JSON answer → "The server answered HTTP n without a
     readable message."; the client gives up after `API_RUN_TIMEOUT_SECONDS`. Never a stack trace.
  3. Result view: the change (metric, segment, window, baseline, observed, significant);
     `determinable: false` shows "Cannot be determined from the data" with the limitations and no
     cause section (even if a payload carried causes); ranked causes with confidence, each with its
     evidence as `<details>` (source, query id, finding); the ruled-out list with why and query
     ids; limitations; next checks (per cause); run id, mode and time; "Download trace" →
     `GET /runs/<id>/trace`.
  - All card and result data goes in through `textContent` (`el()` in `app.js`); the file contains
    no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write`.
- `eval/browser_check.py` (Playwright, headless Chromium) and `.github/workflows/browser-check.yml`
  ("Plan check K"; J is reserved for the Markovian orchestrator check). Playwright is in
  `requirements-dev.txt` only. Chromium is never run on the build machine.

No scanner setting, threshold or default was changed, and nothing the model sees was changed. The
recorded sample cache still matches. Sprint 8 (Markovian orchestrator, default `LOOP=markovian`) was
merged into this branch from `main`; the Day-1 sample cache is recorded for the simple loop only, so
the browser-check server runs with `SAMPLE_MODE=true` and `LOOP=simple`, like main's Day-1 CI steps.

## Left out

- Live trace on the page and `GET /runs/{id}/events` (build-plan cut #1). The page offers the full
  trace as a download instead.
- Recorded model answers for scanner cards: sample-mode replies exist only for the Day-1 question
  (incident-01), so "Explain" on any card in sample mode ends in `cache_miss` (409). Recording them
  needs live model runs, which would also change the cache; not done here.
- Trend lines on the tiles (architecture §7): the cards carry no series. Each card shows baseline →
  observed and its change instead.

## How it was tested

- `tests/test_api_anomalies.py` (22 tests, FastAPI `TestClient`, no network). One real scan of the
  committed sample per module, with an empty environment and `socket.connect` patched to fail.
  - ≤ 10 overall cards and a `by_metric` list, all validating against `app.scanner.models`.
  - Incident-06 (avg review score, relogios_presentes, January 2018) is not in the top ten and not
    in the default top 3, but `?metric=avg_review_score&limit=10` contains it (rank 6, overall 37).
  - The expanded list starts with the board's cards; `limit` is capped at 25 and checked.
  - `config.yaml` thresholds, windows, attribution settings and `ranking` (`per_metric_top: 3`) are
    unchanged.
  - The cache computes once until `?refresh=true`; the scan holds the run lock; `?refresh=true` or a
    first scan while the lock is held → 429 while the cached board is still served; a failing scan
    releases the lock; the scanner connection is closed after the real scan.
  - `anomaly_id` from the top ten and from the expanded list passes the card's question to
    `execute_run` (stub), also before any board load. The real sample cache gives a structured 409
    `cache_miss` for incident-06, with the stored result carrying the card's question. Unknown id →
    404 with no run; both → 400; neither, empty, non-string or over-long id → 422; a second
    anomaly run or a refresh during a run → 429.
- `tests/test_web_page.py` (10 tests). `GET /` and both assets are served and the run-timeout meta
  follows `API_RUN_TIMEOUT_SECONDS`. `web/` holds only the three files. No `http://` or `https://`
  appears in any of them, and the CSS has no `url(` or `@import`. HTML references are same-origin
  paths with no inline script or `on*` attribute, and every JS request goes through one `fetch` to a
  `/…` path. No markup APIs are used.
- `tests/web/render_check.js`, run by the test above with `node` (required when `CI` is set).
  `web/app.js` is loaded in node with a small DOM shim whose `innerHTML` / `outerHTML` /
  `insertAdjacentHTML` throw. It checks:
  - `determinable: false` → "Cannot be determined from the data", no cause, limitations and
    ruled-out shown;
  - causes with expandable evidence and the trace link;
  - an `<img src=x onerror=…>` in the summary, question, evidence, ruled-out and limitations, and in
    card fields, comes out as text with no `img` element;
  - the run id in the trace link is URL-encoded;
  - card fields and signed change, tile count and Show more, and the error messages.
- Full suite: `pytest -q` → 385 passed (353 before); `ruff check .` clean. Existing CI steps are
  unchanged. One existing test case changed: in `tests/test_api.py`'s traversal test, the path
  `/runs/..` is sent by the client as `/` (dot-segment removal), so it only ever tested "unknown
  route → 404". With the page now at `/`, that case got 200. It is replaced by `/runs/%2E%2E`,
  which does reach the run route with the id `..` and is rejected with 400 without any file being
  opened.
- Local smoke test against `python -m app.api` (sample mode, port 8765). `/` and `/web/app.js` 200;
  `/anomalies` 10 cards and 8 metric boards after 25 s; `?metric=avg_review_score&limit=10` has
  `avg_review_score|category|relogios_presentes|2018-01-15`; `POST /run {"anomaly_id": that id}` →
  409 `cache_miss`; the Day-1 question → 200.
- Browser check (CI job "Browser check"). The job starts `python -m app.api` with
  `SAMPLE_MODE=true` and `LOOP=simple`, waits for `/health` (30 s cap) and runs
  `eval/browser_check.py` (whole job capped at 600 s). The script:
  - opens `/` and asserts 1–10 overall cards and the review-score tile;
  - clicks "Show more" on that tile and asserts the incident-06 card appears;
  - clicks its "Explain" and asserts the cache_miss message with no stack trace;
  - types the Day-1 question, clicks "Ask" and waits (120 s cap) for the result view;
  - asserts at least one ranked cause, an evidence item that expands to its finding, the ruled-out
    section, limitations and next checks, and a "Download trace" link whose target is the run's
    NDJSON trace (start…finish) and which downloads;
  - renders a stub `determinable: false` result and an `<img onerror>` summary in the real browser;
  - checks for no page JavaScript errors and no request to another host.

  Each assertion prints `[PASS]` or `[FAIL]` to the CI log. The full-page screenshot
  `browser-check.png` is uploaded as the `browser-check` artifact. It runs only in CI, so its first
  output is in the CI run of this PR, not here.

## Known limits

- One run or scan at a time per process (shared lock, no queue). The first board load takes about
  25 s (one scan), and an Explain before any board load waits for that scan first.
- Cards are cached until `?refresh=true` or a restart. The page has no refresh button.
- Incident-06 is not in the overall top ten (overall rank 37) and not in the default per-metric
  top 3 (6th of 25 in average review score). You reach it with "Show more" on the review-score
  tile. The default was not changed.
- Sample mode answers only the recorded Day-1 question. Explaining any card in sample mode gives
  the readable `cache_miss` message.
- The page runs the Day-1 question under `LOOP=simple` until the sample cache is recorded for the
  Markovian loop; with the default `LOOP=markovian`, sample mode gives `cache_miss` for it too.
- Cards reached only through "Show more" usually have no attribution line: the scanner attributes
  its top 40 episodes and the board's cards only.
- Single uvicorn worker assumed (the lock and the cache are per process).

# Sprint 12 — Anomaly scanner and Adtributor attribution (build-plan tasks 19a + 19b)

Status: built and tested. **The plan check still fails** after the disclosed revision of 23 Oct
(see "Revision (23 Oct)" below). It was run unchanged, and nothing was tuned after either run.

## What was built

- `app/scanner/` (new package, no existing module edited):
  - `config.yaml`: eight metrics as SQL templates (daily orders, weekly revenue, average order value,
    average review score, late-delivery rate, average freight per item, payment-type share — one
    series per payment type — and revenue of funnel-acquired sellers), the segment types (whole
    shop, state, product category, payment type, acquisition channel, sellers with at least 100
    orders), the fixed thresholds and the loop caps. Plain SQL (`CAST`, `CASE`, `COALESCE`,
    `DATE_TRUNC`, `COUNT(DISTINCT)`); table names are the CSV file stems.
  - `db.py`: `run_sql(sql) -> rows`, the only data access. The CSVs are loaded once into a DuckDB
    file under `.cache/duckdb/`, which is reopened read-only with external access disabled.
    `memory_limit=1GB`, `threads=2`, `temp_directory=.cache/duckdb/tmp` (on disk, not `/tmp`).
    Every query has a timeout (`QUERY_TIMEOUT_SECONDS`, interrupted with `cursor.interrupt`).
  - `detect.py`: robust STL + trailing robust z-score, volume floor, episodes.
  - `attribution.py`: `attribute(cube, ratio=...)`, the Adtributor step as a plain function.
  - `scan.py`: series queries, scoring, ranking, attribution of the top 40 episodes,
    parent/child merge, cards. Wall-clock cap `SCANNER_TIMEOUT_S` (default 300) and a query /
    series / episode cap on every loop.
  - `models.py`: `AnomalyCard` and `ScanReport` (pydantic; separate from the result schemas of PR #8).
  - `python -m app.scanner` prints the ranked cards as a table plus the pre-filled questions;
    `--json [PATH]` writes the report (default `logs/anomalies-<timestamp>.json`). Exit code 2
    when a cap stopped the run.
- `eval/scanner_check.py`: the plan check (the only new code that reads `eval/answer_key.json`).
- `.github/workflows/scanner-check.yml`: runs the plan check on every push / PR (Python 3.11,
  same install as `ci.yml`, 10-minute timeout).
- `requirements.txt`: appended `statsmodels==0.15.0`, `numpy==2.4.6`, `pandas==3.1.0`,
  `pyyaml==6.0.3` (cp311 wheels checked for manylinux x86_64 and aarch64; numpy 2.5 has no
  Python 3.11 wheels, hence 2.4.6). `.env.example`: `SCANNER_TIMEOUT_S`. `.gitignore`: `.cache/`.

## Deliberately left out

`GET /anomalies` and the web board; the Investigator tool wiring of `attribute()`; scanner recall
inside `eval/run_eval.py`; Zetaris execution. No code from PR #8 is used or touched.

## How it works

Each metric is computed per segment and period (day for order counts, week otherwise). Because
the repository sample is stratified (see the revision below), counts are scanned as the segment's
share of the period's sampled orders and sums as per-order means; a full extract
(`sample_design: full`) would use raw totals. Daily
series are decomposed with **STL** (Seasonal-Trend decomposition using LOESS, `statsmodels`,
robust fitting, period 7) and the weekly cycle is removed; weekly series have no cycle to remove at
this data length. What is left is scored with a **robust z-score**,
`(x − median) / max(1.4826 × MAD, 0.01 × |median|)` over a strictly trailing window of 28 days or
12 weeks, and a period
is flagged at |z| ≥ 3.5 when at least 30 orders back it. Consecutive flagged periods form an
episode, ranked by |z| × ln(volume). The biggest episodes are then attributed with **Adtributor**
(Bhagwan et al., *Adtributor: Revenue Debugging in Advertising Systems*, NSDI 2014,
<https://www.usenix.org/conference/nsdi14/technical-sessions/presentation/bhagwan>): for each
slice of each other dimension, its explanatory power (share of the change it accounts for) and its
surprise (Jensen-Shannon divergence between expected and observed share); per dimension the
smallest set of slices explaining at least 67% of the change, listed by surprise; dimensions ranked
by total surprise. Ratio metrics are attributed through their numerator and denominator. A
whole-shop card absorbs the flagged child cards its attribution names, and the top ten cards are
shown with a pre-filled question.

## Choices made before the plan check (synthetic data and bugs only)

All of these were fixed and committed before `eval/scanner_check.py` was first run; none looks at
an incident. Incidents 04 and 06 are weekly series and do not go through STL at all.

1. **STL per stretch.** The committed sample is window-sampled (whole-shop orders: 140 in
   July 2017, 2958 in August, 453 in December, 6805 in May 2018; SP has ~1 order a day on
   1–19 Nov 2017 and ~90 on 20–27 Nov). Interpolating across the near-empty days put the
   24 Nov spike into the seasonal component (+743). STL now runs on each unbroken stretch of
   periods above the volume floor that is at least three cycles long; shorter stretches use the
   trailing-median fallback (the plan's "shorter than three cycles" rule, applied per stretch).
2. **STL seasonal span 53 cycles** (statsmodels default 7). On synthetic noise the default
   overfits (seasonal std 2.9 on N(0, 6)) and shrinks the trailing MAD: 10 false flags per 337
   points with span 7, 2.4 with span 53, 1.9 with a fixed ("periodic") pattern.
3. **Minimum history** before a period is scored: 14 valid days / 6 valid weeks.
4. **Merge rule:** a whole-shop card absorbs a same-metric, same-direction, overlapping child
   card when the child's slice is in the explaining set of any returned attribution dimension (a
   one-state spike also lifts every category in proportion; with top-dimension-only merging the
   synthetic test produced four cards for one move).
5. **Adtributor set selection:** slices are taken by explanatory power (largest first, each ≥ 10%)
   until 67% is reached, so the set is the smallest one; the set is then listed by surprise. The
   paper walks slices in surprise order instead; the issue asks for the smallest set.

## How it was tested

`ruff check .` → `All checks passed!`; `pytest -q` → `51 passed` (local, arm64; 43 new tests
plus the 8 existing ones; 11 of them were added in the 23 Oct revision).

- `tests/test_scanner_detect.py` (criterion 2): one-day spike flagged as one episode on that day;
  step change flagged once, as one episode starting at the step; pure noise (120 days) not
  flagged; false-flag rate on noise bounded (30 seeds); low-volume spike skipped (never scored);
  Sundays at 30% of a normal day not flagged with STL, and flagged in the control without it;
  15-day series uses the trailing-median fallback; STL per stretch; episode cap; thresholds are
  the fixed plan values.
- `tests/test_scanner_attribution.py` (criterion 3): the planted slice (RJ) ranks first and state
  ranks first; explanatory powers sum to 1 per dimension; smallest set listed by surprise;
  diffuse change gives no explanation; ratio metric through numerator (score collapse) and through
  denominator (mix shift); ratio surprise = numerator + denominator terms.
- `tests/test_scanner_pipeline.py` (criterion 4): synthetic Olist-shaped CSVs through the real
  SQL path; a whole-shop spike caused by RJ gives one card, rank 1, "driven by state RJ: …", with
  the RJ card merged; two state spikes on different days give two whole-shop cards each naming its
  state; query cap and time cap stop the run and mark it `timed_out`.
- `tests/test_scanner_guards.py` (criteria 1, 5, 6): DuckDB reports `memory_limit` 953.6 MiB
  (1GB), 2 threads, temp directory under the cache dir, external access off; default cache is
  `<repo>/.cache/duckdb`, not `/tmp`; writes and `read_csv` are refused; a long query is
  interrupted and the connection stays usable; `SCANNER_TIMEOUT_S` parsing; no file under `app/`
  contains `answer_key` or an `eval/` path; `python -m app.scanner --json` on the committed sample
  exits 0 and writes ≤ 10 cards that validate against `ScanReport`.
- `tests/test_scanner_design.py` (revision): `stratified` is the default; every count or sum
  metric has a sampling-robust form; counts become period shares (denominator = the period
  total, no whole-shop series) and sums become per-order means; `full` keeps raw totals and leaves
  ratio metrics unchanged; unknown designs and a normalised ratio are rejected; the share SQL
  divides by the period total; share attribution EPs sum to 1. In `tests/test_scanner_pipeline.py`,
  a synthetic sample whose sampling rate triples on day 60 is flagged with raw counts but not as
  shares, and one state's real spike still shows up as a share rise. The pipeline tests that
  check raw-count merging run with `sample_design: full`, because their synthetic sample is
  drawn uniformly. `tests/test_scanner_detect.py`: a MAD-floor test (a near-constant series with
  a 2% dip gives z −2, not infinity; a 20% fall is still flagged).
- `tests/test_scanner_check.py`: the plan check's answer-key mapping, card matching and
  weekly-cycle test, on hand-made cards.

## Plan check (criterion 7), first run on 22 Oct: fails

`python eval/scanner_check.py` (25 s; identical output on repeated runs):

- 213 series, 246 flagged episodes (226 after merging), 235 queries.
- **Recall 1/8** (segment + window; also 1/8 with the metric required): only incident-01
  (Black Friday, card 2, whole-shop revenue 20–26 Nov 2017, z +30.5).
- **(a) incident-06 — FAIL.** Flagged by the detector, not in the top ten: avg review score,
  relogios_presentes, weeks 2018-01-15..2018-02-04, **z −6.42** (baseline 3.87 → 2.04), score 25.2,
  rank 104 of 226 (89 of 180 among ratio metrics).
- **(b) incident-04 — FAIL.** Flagged by the detector, not in the top ten: avg freight, RJ,
  weeks 2018-08-06..2018-08-19, **z +4.44** (24.87 → 32.83), score 24.2, rank 110 of 226 (93 of
  180 among ratio metrics). No top-ten card names RJ for freight.
- **(c) no weekly-cycle-only card — PASS.**
- Unplanted flags: 8 of the 10 cards. The 10th card scores 104.5. The top of the board is
  revenue / order-count jumps that follow the sample's month-by-month sampling rate (late
  April–May 2018, Black Friday week) and small-segment ratio moves with very large z (debit-card
  share in brinquedos, late-delivery rate in MG and in relogios_presentes in June 2018, voucher
  share in beleza_saude).
- Other incidents without an own episode at |z| ≥ 3.5: 02 (whole-shop late rate), 03 (seller
  below the floor in-window), 05, 07, 08.

## Revision (23 Oct): sampling-aware metrics and a calmer detector

**This change was decided after seeing the first plan-check result.** The owner chose option C
from the result of the first run: fix the data side openly, then re-run the *unchanged* plan
check. `eval/scanner_check.py` and its top-ten criterion were not edited. The new settings were
chosen once from first principles and committed before the check was re-run. They were not
compared against the check.

**Why.** The repository sample is not drawn uniformly. `data-prep/build_sample.py` keeps
incident windows at close to 100% and the background at 2% (`config.BACKGROUND_SAMPLE_RATE`).
The raw Kaggle files are not in the repository, so per-order sampling weights cannot be
reconstructed. Sampled orders per month (`orders.csv`, by purchase month):

| 2017-01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 60 | 90 | 84 | 145 | 117 | 140 | 2958 | 2943 | 3123 | 3519 | 453 |

| 2018-01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 505 | 917 | 901 | 2732 | 6805 | 2857 | 927 | 942 |

A 20-fold jump from July to August 2017 is the sampling design, not the shop. So absolute
counts and sums are not comparable across periods. They filled the first board: whole-shop
revenue +567% in late April–May 2018 was card 1.

**What changed.**

1. `config.yaml` has a top-level `sample_design: stratified | full` (default `stratified` for
   this repository). Each count or sum metric has a `normalise` option. Under `stratified`:
   - `daily_orders` (`normalise: period_share`) becomes the segment's share of that day's sampled
     orders. The whole-shop series is dropped, because its share is 1 by definition. Attribution
     goes through numerator and denominator: a slice's denominator is all of that slice's orders
     in the period, across every segment, so the slice denominators add up to the period total.
   - `revenue` and `channel_revenue` (`normalise: per_order`) become per-order means: the sum
     divided by the segment's sampled order count in that period.
   - Under `full` (a complete extract) all three keep their raw totals. Ratio metrics are the
     same under both designs.

   The count and sum incidents **01, 03, 07 and 08 are now measured as shares and per-order
   means**, not raw totals.
2. Detector: the weekly trailing window is **12 weeks instead of 8**, and the robust MAD z is
   kept. A MAD taken from 8 values is itself very noisy: on pure Gaussian noise |z| ≥ 3.5 is
   crossed on 4.6% of points with 8 weeks and on 2.6% with 12 weeks (400 synthetic series).
   The daily window stays at 28 days.
3. A **MAD floor**: the robust spread is at least 1% of |trailing median|. The value was chosen
   from what is worth explaining, not from the data: with z ≥ 3.5, a move under 3.5% of a
   metric's level is never an anomaly. A near-constant series (for example a review score of
   5.0 for weeks) then no longer gives an infinite z for a 2% dip. When the median is 0 (for
   example a payment type never used in a segment) the floor is 0, so the old zero-spread
   fallback and the z cap of 50 still apply.

**Re-run of the unchanged check** (`python eval/scanner_check.py`, 24 s, exit 1): 212 series,
219 flagged episodes (206 after merging), 231 queries.

| | first run (22 Oct) | after revision (23 Oct) |
|---|---|---|
| incident-06 (avg review score, relogios_presentes) | z −6.42, rank 104 of 226 | z −8.43 (3.94 → 2.04, 2018-01-15..02-04), **rank 37 of 206** |
| incident-04 (avg freight, RJ) | z +4.44, rank 110 of 226 | **no own episode**: peak z +3.38 (week of 2018-08-13), below 3.5 |
| (a) / (b) / (c) | FAIL / FAIL / PASS | **FAIL / FAIL / PASS** |
| recall, segment + window | 1/8 | 2/8 (01 is out; 02 and 06 are in via cards 7 and 10, both with another metric) |
| recall, segment + window + metric | 1/8 (incident-01) | **0/8** |
| unplanted flags | 8 of 10 cards | 8 of 10 cards |

What moved, and why (diagnosis only; nothing was changed after it):

- incident-06 rises because the longer window keeps more pre-dip weeks in the baseline. With 8
  weeks the dip's own first week already weighed on the baseline of the second; with 12 weeks the
  three dip weeks score −6.0, −8.4 and −4.8 (they were −6.4, −4.5 and −3.7).
- incident-04 drops out because the 12-week baseline for RJ freight takes in a wider spread of
  earlier weeks: the same weeks score +2.53, +3.18, +3.38 and +3.07 (they were +2.84, +3.53,
  +4.44 and +1.88 with 8 weeks). The MAD floor changes neither incident; their z values are the
  same with and without it.
- incident-01 (Black Friday) was card 2 as whole-shop revenue. Under the stratified design no
  whole-shop count exists, and whole-shop revenue per order does not reach |z| ≥ 3.5 that week.
  On this sample a whole-shop volume spike cannot be told apart from a change in the sampling
  rate.
- Incidents 03, 07 and 08 still have no own episode as shares or per-order means.
- The board is now led by late-delivery-rate rises in December 2017 (MG, SP, boleto,
  cama_mesa_banho, whole shop) and the whole-shop review-score fall that goes with them. These
  are ratio metrics, so the sampling rate does not drive them. They are not planted incidents.
  The debit-card share in brinquedos (median 0, z capped at 50) is still card 2.

As agreed, there was no further tuning. The result is reported as is.

## Known limits

- **MAD on short windows is heavy-tailed.** Without any STL, the robust z of pure Gaussian noise
  crosses 3.5 on 0.63% of points with a 28-point window and on 2.6% with a 12-point window
  (4.6% with 8); a normal distribution would give 0.05%. With ~200 weekly series this is still
  the main source of flags.
- On the stratified sample, whole-shop volume (order counts, total revenue) cannot be scanned:
  without the raw files and their sampling weights it cannot be separated from the sampling rate.
  A full extract with `sample_design: full` restores it.
- The share and per-order forms change what a card says ("share of the day's orders", "revenue
  per delivered order"), and they overlap with the average-order-value metric.
- When a move is broad, attribution still returns the dimension whose set has the highest
  surprise, which can be a near-empty statement such as "acquisition channel none: 88%" (97% of
  orders come from sellers outside the marketing funnel).
- A zero-variance baseline (e.g. a payment type never used in a segment) gives an infinite z,
  capped at 50 for ranking; one such episode reaches the top ten (card 4).
- Explanatory power can exceed 100% for one slice when others move the opposite way.
- Order-level dimensions use the first item's category and seller and the first payment's type.
- Weekly series are tested against their trailing level only (no annual cycle at this length).

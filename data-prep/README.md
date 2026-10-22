# data-prep — Olist sample + planted incidents

> In this repository the scripts' output folder `out/` is committed as `data/sample/` (data) and
> `eval/answer_key.json` (answer key). Paths below that mention `out/` or `../research/` refer to the
> layout the scripts were written in; the research plan is `docs/research/olist-dataset-and-incident-plan.md`.

Builds the small, repo-sized data sample and the 10 planted incidents for the "why did
this number change?" agent, per the design in
`../research/olist-dataset-and-incident-plan.md` (Revision 1).

This is a **declared pre-existing component**, built before the build window (22 Oct 2026)
with Nikolay's approval, for exactly that reason -- see `out/README_PROVENANCE.md` if
one exists in the submission repo, or declare it in the submission form/README per the
rules.

## Source and licence

- **Olist Brazilian E-Commerce** (`olistbr/brazilian-ecommerce` on Kaggle) and
  **Olist Marketing Funnel** (`olistbr/marketing-funnel-olist` on Kaggle).
- Licence: **CC BY-NC-SA 4.0** (confirmed by the Kaggle API's own license field on
  download for both datasets). Non-commercial, share-alike -- fine for a hackathon
  submission, cite the source and licence in the final project's README too.
- No personal data: checked every column header and regex-scanned all review comments
  in the raw data for emails/phone numbers (0 and 1 hits respectively, out of 99,224 --
  see `research/olist-dataset-and-incident-plan.md` Part 1.3). Standard, already-scrubbed
  public release.

## What's in `out/`

Four source folders, matching how a real business would actually keep this data apart
(see the plan's Part 1.4):

- `orders/` -- orders, order_items, customers, products, sellers, geolocation
  (deduped to one row per zip prefix), category translation. The commerce/fulfillment
  system.
- `payments/` -- order_payments. A separate payments processor.
- `reviews/` -- order_reviews. A separate CX/reviews tool.
- `marketing/` -- marketing_qualified_leads, closed_deals. A separate CRM.

Plus `out/answer_key.json` (one entry per incident -- `id`, question, metric, `segment`
as `{type, value}`, ISO `window_start`/`window_end`, `cause_types` enum list, expected
mechanism, sources, wrong explanation to rule out, whether a cause is determinable) and
`../detectability_report.md` (measured pass/fail for all 10 incidents, plus a leakage
section, against the finished sample).

**No column anywhere flags an injected row.** Every incident is applied by perturbing a
real, already-existing field (`order_status`, `freight_value`, `payment_type`,
`payment_value`, `payment_installments`, `review_score`, `review_comment_title`,
`review_comment_message`, `price`, delivery-date fields) or by removing whole order
rows -- never by adding a marker. Verified by inspecting every output file's header, and
by the four cross-field consistency checks in `detectability_report.md`'s leakage
section (payments reconcile with items, canceled orders have no delivery date, review
text matches review score, relabeled payments have a real installment spread).

## Regenerate from scratch

Raw Kaggle files are **not** in this folder or any repository -- they live in a scratch
directory (`/tmp/olist-scratch` by default; this machine already had working Kaggle
credentials under `~/.kaggle/`). To rebuild everything from zero:

```bash
# 1. Get the raw data (skip if /tmp/olist-scratch already has it)
mkdir -p /tmp/olist-scratch
kaggle datasets download -d olistbr/brazilian-ecommerce -p /tmp/olist-scratch --unzip
kaggle datasets download -d olistbr/marketing-funnel-olist -p /tmp/olist-scratch/marketing-funnel --unzip

# 2. Build the sample, snapshot it (so the leakage tests have a "before" to compare
#    against), apply the incidents, then measure everything
cd data-prep
python3 build_sample.py          # deterministic, seed=42 (config.py)
mkdir -p /tmp/oah_preinject_snapshot && cp -r out/* /tmp/oah_preinject_snapshot/
python3 inject_incidents.py      # deterministic, seed=43; --incidents 3,4,5,6,7,8,9,10 by default
python3 detectability_report.py  # writes ../detectability_report.md (skips the leakage
                                  # section if the snapshot above wasn't taken)
```

Override the raw-data location with `--raw-dir` / `--marketing-dir` on `build_sample.py`,
or the `OLIST_RAW_DIR` environment variable (see `config.py`).

To rebuild with only some incidents switched on (incidents 1 and 2 are the real,
unperturbed events and are always present once their retention windows are kept by
`build_sample.py` -- they can't be individually disabled since they're not injected):

```bash
python3 inject_incidents.py --incidents 3,4,6   # only these three
```

Requires Python 3 with `pandas` and `numpy` (both already present on this machine --
no other dependencies).

## Files

- `config.py` -- every window, ID, and threshold used by both scripts (single source of
  truth, so the sample always has enough density where the incidents need it).
- `build_sample.py` -- raw Kaggle files -> `out/` sample. No injection.
- `inject_incidents.py` -- applies incidents 3-10 to `out/`, writes `out/answer_key.json`.
- `detectability_report.py` -- measures all 10 incidents against the finished sample,
  writes `../detectability_report.md`.

## What changed from the original design (Revision 1 plan) during the real build

Three corrections, made because the real downloaded data didn't match a planning-time
assumption -- each is also noted inline in `config.py` next to the affected constant:

1. **Incident 8's month.** The raw dataset's `order_purchase_timestamp` effectively ends
   in August 2018 (September has 16 orders nationwide, October has 4) -- the planned
   September 2018 window for incident 8 had almost no data. Moved to 12-30 June 2018
   (after the strike closes, so it doesn't stack with incident 2's real signal).
2. **Incident 6's months.** February/March 2018 turned out to have a real, naturally
   elevated delivery-lateness for the `relogios_presentes` category (20.7% / 27.3%,
   unrelated to anything injected) that would have contaminated the "delivery delay is
   a normal decoy" check. Moved one month earlier to Dec 2017 / Jan 2018 / Feb 2018,
   where the incident month's natural late-rate is a clean 5.6%.
3. **Incidents 4, 8, 10 sizing.** First-pass multipliers (1.25x freight, 1.12x freight,
   ~1-5%/month price drift) were invisible against natural month-to-month variance once
   measured (RJ freight naturally differs ~12% between some month pairs; item price has
   a very high natural CV of ~1.3). Increased to 1.5x / 1.25x / ~5-20% cumulative
   respectively, and incident 10's per-segment retention floor from 150 to 300/month,
   dropping four low-volume states (PR, SC, BA, DF -- their whole natural population is
   under 300/month in this quarter) from the "top states" check since they can't carry a
   confident per-state signal at any sample size this dataset provides. See
   `detectability_report.md` for the measured, passing result and the honest limitation
   note on category-level noise.

### Revision 2 -- leakage fixes (found by Nikolay's independent check of `out/` against the raw files)

The first build passed all 10 detectability tests but left four cross-field tells that
an agent comparing sources could use to spot a touched row, none caught by the
detectability tests above (those check whether a *signal* is visible, not whether a
*row* looks internally consistent). Fixed, and now covered by `detectability_report.md`'s
leakage section with measured before/after numbers:

1. **Payments didn't move with price/freight changes.** Incidents 4, 8 and 10 changed
   `price`/`freight_value` but left `payment_value` alone, so 10,172 orders' payments no
   longer summed to their item total (vs a ~0.2% mismatch rate on untouched orders).
   Added `reconcile_payments()`: after all incidents run, for every order whose item
   total actually changed, every payment row for that order is scaled by the same ratio
   -- proportional, so a split/installment payment keeps its relative shares.
2. **Canceled orders kept a delivery date.** Incident 3 flipped `order_status` but left
   `order_delivered_carrier_date`/`order_delivered_customer_date` untouched, so all 18
   affected orders looked "delivered" despite being canceled -- real canceled/unavailable
   orders are null there 88-100% of the time. Incident 3 now nulls both fields for the
   orders it flips.
3. **Review text didn't move with review score.** Four incidents (3, 6, 8, 9) lower
   `review_score` but left the original comment text in place, so a 1-star review could
   still read "Super recomendo o produto e a loja!" -- 269 reviews had this problem
   across all four incidents combined before the fix (145 for the scores actually
   checked below). Added `fix_review_text()`: for any review whose score lands at <=2,
   the comment title is blanked and the message is either blanked or replaced with a
   genuine low-score comment drawn from the raw dataset, in the real measured
   proportions by score (score 1: 83.6% title blank, 23.5% message blank; score 2:
   84.8% / 31.9%).
4. **Relabeled payments all had 1 installment.** Incident 5 flips some MG `boleto`
   payments to `credit_card`, but boleto is always 1 installment in the real data, so
   leaving `payment_installments` at 1 made every relabeled row look identical -- a real
   credit_card payment has a spread. Now draws from MG's real credit_card installment
   distribution (measured from the raw data) for each relabeled row.
5. **Answer key.** Rewrote with a stable `id` per incident, ISO `window_start`/
   `window_end` (previously three different formats across entries), a `cause_type`
   enum, and `segment` as a `{type, value}` object instead of a prose string. Also fixed
   incident 6's question, which said February when the actual dip (after the Revision 1
   month correction above) is in January.

### Revision 3 -- premise bug + smaller fixes (found by Nikolay's independent premise check)

1. **Incident 8's premise didn't hold.** The question asked why RJ *revenue* dropped,
   but the design only touched `freight_value` (+25%, which if anything raises gross
   payment totals) and `review_score` (which doesn't mechanically move the current
   period's revenue at all) -- RJ weekly revenue across June was flat (22.6k/28.7k/
   21.3k/21.9k). Redesigned: `INCIDENT_8_CANCEL_FRACTION` (20% of delivered RJ orders in
   -window canceled, spread across many sellers -- not one, unlike incident 3) +
   `INCIDENT_8_PRICE_DISCOUNT` (15% off the orders that still complete). Measured result:
   delivered-order daily revenue $3,972/day (1-11 Jun baseline) -> $2,789/day (12-30 Jun),
   **-29.8%**, two causes, neither alone sufficient.
2. **Premise tests added for all 10 incidents.** New `premise_tests()` in
   `detectability_report.py`, run before the existing per-incident "signal" checks:
   computes the literal metric named in each answer-key question, in its stated segment/
   window, against a baseline, and fails if it hasn't moved as claimed. This is stricter
   than (and separate from) the signal checks, which can pass by confirming a mechanism
   component without checking whether the question's own metric moved -- the exact gap
   that let incident 8 through originally.
3. **Incident 3's "revenue" definition.** Order_items rows for a canceled order still
   exist (we never delete rows for a status change), so a naive `sum(price)` over all
   rows would not fall to zero. Standardized on `cfg.REVENUE_DEFINITION =
   "sum(payment_value) where order_status == 'delivered'"` everywhere "revenue" appears
   in the key (incidents 3, 7, 8) and stated it explicitly in each entry's `metric` field,
   rather than reword the questions.
4. **cause_type -> cause_types (list), + `freight_cost` added.** A freight surcharge is
   a cost change, not a time delay, so incident 4 (and the old incident 8) were tagged
   `logistics_delay` incorrectly. Added `freight_cost` to the vocabulary, used it for
   incident 4, and changed every entry's field to a list (`cause_types`) so incident 8
   can hold both of its causes (`["volume", "price_discount"]`).
5. **Comment pool was too small.** 29 hardcoded texts reused ~8x each across 232
   replacements (~97% duplicate rate vs the real dataset's natural ~3.7%). Replaced the
   hardcoded list with `load_comment_pool()`, which reads the full real pool (~7,300
   distinct low-score comments, 15-140 chars) from the raw dataset at run time. Measured
   after the fix: 4.7% duplicate rate among all low-score comments in the finished
   sample -- close to the real dataset's 3.7%.

### Revision 4 -- metric/scoring-key fidelity (found by Nikolay's independent read of the answer key against the report)

This sample is scored against the answer key on submission day, so every entry has to
name the metric the data actually supports -- three fixes:

1. **Incident 10 named the wrong metric.** The question asks about average *order
   value*; the key's metric and the premise test measured average *item price*
   (`order_items.price`) -- those differ whenever items-per-order shifts. Chose to
   measure the literal thing: average order value as `sum(payment_value)` per order.
   Measured: **AOV Aug->Oct 2017: $142.69 -> $130.96, -8.2%** (smaller than item price's
   -11.8%, since only item price was perturbed and freight -- untouched -- dilutes the
   per-order figure). Also discovered AOV is noisier per-state than item price (it
   includes untouched, independently-variable freight); the per-state signal check now
   gates on the national figure plus a clear majority of states, not every single one,
   and reports the one exception (RS, +11.4%) rather than hide it.
2. **Leakage test 2 only covered incident 3.** Extended to incident 8's canceled RJ
   orders (12-30 Jun 2018): of 88 orders canceled/unavailable (out of 441 candidates),
   **0/88 still have a delivery date** and **0/87 reviews still read like a delivered
   order** (score >2 or exact pre-injection text). Also added RJ's canceled+unavailable
   share for every month of 2018 for context: 12.4% in June (the incident month, n=716)
   vs 0.0-1.7% every other month -- the window is the obvious outlier, not an arbitrary
   assertion.
3. **`injected` was hardcoded true for everything.** Now computed mechanically:
   `inject_incidents.py` snapshots every table before and after each incident call
   (plus its `reconcile_payments()` pass, scoped per-incident so attribution stays
   correct), counts rows added/removed/changed via `count_changed_rows()`, and sets
   `injected = rows_changed > 0`. Result: incidents 1-2 (real events) are `injected:
   false, rows_changed: 0` as expected. **Incident 9 comes out `injected: true,
   rows_changed: 3`** -- its 3 review scores genuinely are script-modified (that's how
   the unexplained dip exists at all), even though no *causal mechanism* is planted in
   any other source. `injected` tracks row mutation, not whether a findable cause
   exists; `cause_types: ["none"]` + `determinable: false` already carry the latter.
   Flagged explicitly in case a different convention was intended for incident 9.

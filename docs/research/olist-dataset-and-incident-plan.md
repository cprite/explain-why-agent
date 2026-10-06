# Olist dataset + incident plan — research note

Written by Alan (researcher), 2026-10-06. Research and planning only — nothing here was
committed to any submission repository and no project code was written. All measurements
below are from the **real, downloaded dataset** (see Part 1.3 for how), not estimates.

The task message that generated this note was cut off at "Output: write the full plan
to ___" — no destination path arrived. I'm saving this to `research/` in this
coordination workspace (not a submission repo; this workspace already holds `BRIEF.md`
and `platform-resources/` as shared reference material), and posting a summary to
#intel. If a different destination was intended, say so and I'll move it.

---

## Part 1 — The dataset

### 1.1 Tables and row counts

Downloaded via Kaggle CLI (credentials were already configured on this machine) to
`/tmp/olist-scratch/` — a scratch folder, not the project repo, per the constraint.

**Core dataset — `olistbr/brazilian-ecommerce`** (CC-BY-NC-SA-4.0, confirmed by the
Kaggle API's own license field on download):

| File | Rows | Size |
|---|---:|---:|
| `olist_orders_dataset.csv` | 99,441 | 17.7 MB |
| `olist_order_items_dataset.csv` | 112,650 | 15.4 MB |
| `olist_order_payments_dataset.csv` | 103,886 | 5.8 MB |
| `olist_order_reviews_dataset.csv` | 99,224 | 14.5 MB |
| `olist_customers_dataset.csv` | 99,441 | 9.0 MB |
| `olist_products_dataset.csv` | 32,951 | 2.4 MB |
| `olist_sellers_dataset.csv` | 3,095 | 0.17 MB |
| `olist_geolocation_dataset.csv` | 1,000,163 | 61.3 MB |
| `product_category_name_translation.csv` | 71 | 2.6 KB |

Total zipped download: 42.6 MB. Unzipped: ~121 MB — the geolocation file alone is
61 MB (roughly 53 rows per zip-code prefix; it's a repeated lat/lng sample, not
one row per prefix) and is the one file worth shrinking hard for a repo (see 1.4).

**Marketing funnel — `olistbr/marketing-funnel-olist`** (also CC-BY-NC-SA-4.0):

| File | Rows | Date range |
|---|---:|---|
| `olist_marketing_qualified_leads_dataset.csv` | 8,000 | 2017-06-14 to 2018-05-31 |
| `olist_closed_deals_dataset.csv` | 842 | 2017-12-05 to 2018-11-14 |

Zipped download: 278 KB — negligible, keep it whole.

### 1.2 Date range and join keys

Core order date range (`order_purchase_timestamp`): **2016-09-04 to 2018-10-17**
(measured directly). Status breakdown: 96,478 delivered, 1,107 shipped, 625 canceled,
609 unavailable, 314 invoiced, 301 processing, 5 created, 2 approved.

Join keys (all verified against the live files, not assumed):

- `orders.order_id` → `order_items.order_id`, `order_payments.order_id`, `order_reviews.order_id`
- `orders.customer_id` → `customers.customer_id`
- `order_items.product_id` → `products.product_id`
- `order_items.seller_id` → `sellers.seller_id`
- `customers.customer_zip_code_prefix` / `sellers.seller_zip_code_prefix` → `geolocation.geolocation_zip_code_prefix`
- `products.product_category_name` → `product_category_name_translation.product_category_name`
- `closed_deals.seller_id` → `sellers.seller_id` — **verified**: only 380 of 842 closed-deal
  sellers ever appear in the core sellers table, i.e. ~55% of "won" marketing deals never
  converted to an actual selling seller in this window. That gap is itself useful raw
  material for incident design (see 7 below).
- `marketing_qualified_leads.mql_id` → `closed_deals.mql_id`

### 1.3 Personal data check

Scanned every column header across all 11 files and regex-scanned all 99,224 review
comments for email- and phone-like patterns:

- No names, emails, phone numbers, or street addresses in any structured column.
  `customer_unique_id` is a pre-hashed value (Olist's own anonymization); zip fields are
  5-digit **prefixes** (not exact addresses); geolocation rows are zip-prefix-level
  lat/lng, not per-customer.
- Free-text `review_comment_message`/`review_comment_title`: 0/99,224 matched an
  email pattern, 1/99,224 matched a loose phone-number regex (almost certainly a false
  positive from an unrelated number sequence — not independently verified by reading
  the row, deliberately, to avoid pulling up a review I haven't confirmed is actually PII).
- Conclusion: this is the standard, already-scrubbed public Kaggle release. Under the
  organisers' rule ("no real personal data"), it reads as compliant as downloaded — the
  one residual risk is free-text reviews, which is a known, widely-discussed property of
  this dataset, not something found here. Not a legal opinion — flag this at the Zetaris/
  rules workshop if there's any doubt before using full review text verbatim in a demo.

### 1.4 Splitting into separate sources

A real business would not keep these in one database. Proposed 4-way split, matching
how Olist itself would realistically segment systems:

1. **Orders & fulfillment** (OMS/WMS) — `orders`, `order_items`, `customers`,
   a trimmed `geolocation` (see below). Holds purchase/approval/carrier/delivery
   timestamps, price, freight, product/seller linkage.
2. **Payments** (payments processor / finance) — `order_payments` only. Type,
   installments, value. In reality this is often a genuinely separate vendor
   (e.g. a payment gateway), not even the same company's database.
3. **Reviews / CX** (customer support or a CSAT tool) — `order_reviews` only.
4. **Marketing & seller acquisition** (CRM/marketing automation) — `marketing_qualified_leads`,
   `closed_deals`, plus `sellers` and `products` as the catalog/seller directory
   a marketing or BI team would reference but not own transactionally.

**Questions that genuinely need more than one source** (this is the test for a good
incident — if one source answers it alone, it's not exercising the "across sources" part
of the project):

- *"Why did average order value drop in a given week?"* — needs **Orders** (price/volume)
  **and Payments** (installment mix) to tell "it was a discount" from "it was a shift to
  installment plans that changed effective revenue timing."
- *"Why did customer satisfaction fall?"* — needs **Reviews** (the score drop) **and
  Orders/fulfillment** (delivery delay) to confirm or rule out the obvious cause —
  this is the single most useful cross-source link in the whole dataset (see incidents
  2 and 6).
- *"Why did a seller's revenue change?"* — needs **Marketing** (did they come from a
  particular lead cohort, are they still "closed" in CRM) **and Orders** (are they
  actually transacting) — the 55% non-conversion gap in 1.2 means this question has
  real texture, not a synthetic one.
- *"Why did freight cost rise in a region?"* — needs **Orders/fulfillment** (freight_value)
  **and** a geography signal (state, from the trimmed geolocation/customer state) —
  weaker as a multi-source question since both halves live in the same source table
  once geolocation is folded in; treat this as borderline single-source unless freight
  policy data is modeled as a separate "carrier contracts" source (not in this dataset,
  so this particular question would need a synthetic fifth source — not recommended,
  adds a source with no real data behind it).

### 1.5 Real events — measured, not estimated

**Black Friday 2017 (24 Nov) → order volume spike.** Daily order counts, measured from
`order_purchase_timestamp`:

- Baseline (1–16 Nov 2017 daily average): **166 orders/day**
- 24 Nov 2017 (Black Friday): **1,176 orders** — **~7.1x baseline**
- 25 Nov 2017: 499 orders, 26 Nov: 391, tapering to ~275–400/day through 1 Dec
- Average item price, Black Friday weekend (24–25 Nov) vs baseline (1–16 Nov):
  **$109.75 vs $120.05 — an 8.6% drop**, consistent with promotional discounting rather
  than a data artifact (a logging glitch wouldn't move price).

**Verified: confirms the organisers' hint.** This is a clean, dramatic, easy incident.

**Truck drivers' strike, 21 May – 1 Jun 2018 → delivery disruption.** The signal is only
visible if you group by **delivery week**, not purchase week (grouping by purchase week
hides it, because purchases made during the strike mostly weren't *delivered* until after).
Measured by week of `order_delivered_customer_date`:

| Week of delivery | % orders late vs estimate | Avg carrier→customer transit (days) | Deliveries completed |
|---|---:|---:|---:|
| 2018-05-14 | 4.4% | 8.0 | 2,073 |
| 2018-05-21 | 5.8% | 8.8 | 1,494 |
| **2018-05-28** | **15.9%** | **11.6** | **634** (volume collapse) |
| **2018-06-04** | **16.6%** | **12.3** | 1,772 (backlog clearing) |
| 2018-06-11 | 10.0% | 8.4 | 1,514 |
| 2018-06-18 | 2.9% | 7.6 | 1,678 |

Second, independent confirming signal in **Reviews**: average review score (by delivery
week) dips from 4.26 (week of 14 May) to 4.10 (week of 28 May) — real but modest, n=629
that week (small-sample caveat, worth noting in the answer key itself).

**Verified: confirms the organisers' hint**, but it's a **medium**, not easy, incident —
an agent that only groups by purchase date will miss it entirely, which is exactly the
kind of wrong-turn a critic should catch.

### 1.6 Sampling plan (small repo, events intact)

Full core dataset is 121 MB unzipped — too big for a hackathon repo per the technical
requirements doc's "a judge cloning a multi-gigabyte repo is a judge who stops"
(`rules-and-requirements-technical-execution-requirements.md` §7; ours isn't gigabytes,
but still far more than needed).

Proposed sample, built from the real downloaded data:

- **Keep 100%** of orders (and their joined items/payments/reviews) in two windows:
  - 20–27 Nov 2017 (8 days bracketing Black Friday) — **5,297 orders** at the wider
    15–30 Nov window measured above; narrowing to 20–27 Nov keeps the spike and a few
    clean baseline days on each side at roughly half that count.
  - 14 May – 11 Jun 2018 (4 weeks bracketing the strike) — covers two baseline weeks,
    the two disrupted weeks, and one recovery week.
- **Random 2% sample**, stratified by calendar month, of all orders outside those
  windows — preserves seasonality (e.g. the Oct 2016 launch ramp, year-end patterns)
  without keeping the full 99k rows.
- **Geolocation**: dedupe to one row per `zip_code_prefix` (the file has ~53 near-duplicate
  lat/lng samples per prefix) — cuts it from 1,000,163 rows / 61 MB to roughly 19,000
  rows / ~1 MB. We don't need street-level precision for any planned incident, only
  state/city-level grouping.
- **Products/sellers**: filter to only the IDs referenced by the sampled `order_items`.
- **Marketing funnel**: keep both files whole — already under 1 MB combined and small
  numbers (8,000 / 842 rows) matter for incident 7's cohort comparison.

This keeps both real events fully intact with clean before/after baselines, keeps the
repo in the low single-digit MB range, and documents the sampling method in the README
as the technical requirements doc asks (source + licence + subset + regenerate method).

---

## Part 2 — The incident plan

Ground rule applied throughout: every incident must be **visible in the data itself**
(a metric shift + corroborating detail in a second source), not flagged by a hidden
label — consistent with "judges discount hardcoded demo paths." The two real events
above are incidents 1 and 2; the rest are synthetic perturbations layered onto the
sampled CSVs by a small injection script (not yet written — this is the design only).

**1. Order volume spike — Black Friday** *(real, easy)*
Metric: daily order count. Cause: Black Friday promotion, 24 Nov 2017. Window: 24–26 Nov
2017, ~7x baseline. Evidence in ≥2 sources: Orders (volume spike) + Orders/items
(avg item price down 8.6%, i.e. a real sale, not a duplicate-record glitch). Wrong
explanation to rule out: "a logging error double-counted orders" — disproved by checking
order_ids are unique and price genuinely dropped (a duplication bug wouldn't change price).
Difficulty: **easy**.

**2. Delivery delay spike — truck drivers' strike** *(real, medium)*
Metric: % orders late vs estimate, grouped by delivery week. Cause: national strike,
21 May–1 Jun 2018. Window: deliveries completed 28 May–4 Jun 2018 (late% 5%→16%,
transit +3–4 days). Evidence: Orders/fulfillment (the delay itself) + Reviews (score dip
4.26→4.10 same week). Wrong explanation to rule out: "one seller or region stopped
shipping" — disproved by showing the delay is broad across many sellers/states, not
concentrated. Difficulty: **medium** (invisible if grouped by purchase date instead of
delivery date — a real trap for a naive agent).

**3. Single-seller revenue collapse** *(synthetic, easy)*
Metric: weekly revenue for one seller. Cause (injected): that seller's `order_items` rows
removed for a 2-week window, simulating a suspension. Window: 2 weeks, ~100% drop for
that seller, total marketplace revenue barely moves. Evidence: Orders (seller-level
revenue to zero) + Marketing (no matching reactivation/new-deal event for that seller in
closed_deals). Wrong explanation to rule out: "marketplace-wide demand fell" — disproved
by showing every other seller's revenue that week is normal. Difficulty: **easy**.

**4. Regional freight surcharge** *(synthetic, easy)*
Metric: avg freight_value for orders shipped to Rio de Janeiro (RJ) — chosen because it
has real volume (12,852 customers) without RJ dominating the national total the way São
Paulo does, so a regional move doesn't also show up as a national one. Cause (injected):
freight_value for RJ-bound orders scaled up ~25% for one month. Evidence: Orders/items
(freight_value by customer state). Wrong explanation to rule out: "orders got heavier/
bigger" — disproved by checking `products.product_weight_g` for the same orders is
unchanged. Difficulty: **easy**.

**5. Payment-mix shift** *(synthetic, medium)*
Metric: % of payments via `boleto` in one state. Cause (injected): a chunk of boleto
payments re-labeled as credit_card for 3 weeks in one state, simulating a processing
change. Evidence: Payments (type mix) + Orders (confirm total order *volume* in that
state is flat — only the mix changed). Wrong explanation to rule out: "overall demand in
that state changed" — disproved by the flat volume. Difficulty: **medium** (requires
normalizing by volume, not raw counts, or the mix shift reads as a demand shift).

**6. Review-score dip with a delivery-delay decoy** *(synthetic, medium–hard)*
Metric: avg review_score for one product category. Cause (injected): a product-quality
problem in category C (simulated by injecting a batch of low scores tied only to that
category) for one month — **while delivery times for category C orders in that window
are deliberately left normal**. Evidence: Reviews (score drop, joined via order_items →
product_category) + Orders/fulfillment (delivery timing for those same orders, which
must be checked and found normal). Wrong explanation to rule out: **the delivery-delay
story from incident 2** — the critic must actively check delivery timing for this
category in this window and find it unremarkable before accepting the product-quality
explanation. This is the one incident purpose-built to catch an agent that over-applies
incident 2's pattern. Difficulty: **medium–hard**.

**7. Marketing funnel break (lead surge, no revenue follow-through)** *(synthetic, hard)*
Metric: revenue from a marketing-sourced seller cohort. Cause (injected): a spike in
`marketing_qualified_leads` (origin=paid_search) in one month, but the injected
`closed_deals`→actual-selling conversion for that cohort is held artificially low (using
the real 55% non-conversion gap found in 1.2 as the realistic baseline to perturb from),
so the expected revenue bump never appears in Orders. Evidence: Marketing (lead spike +
closed_deals) + Orders (seller revenue by cohort, via the verified
`closed_deals.seller_id → sellers.seller_id → order_items.seller_id` chain). Wrong
explanation to rule out: "seasonal demand" — disproved by checking organic-origin
sellers' revenue the same month is normal. Difficulty: **hard** — a genuine 3-source,
3-hop chain.

**8. Compounding two-cause revenue drop** *(synthetic, hard)*
Metric: total weekly revenue in one state. Cause (injected): **two independent, smaller
causes overlapping** in the same week — a regional freight surcharge (like incident 4,
smaller magnitude) **and** a coincidental dip in that state's marketing leads — together
explaining the drop, with neither alone sufficient. Evidence: all four sources. This
incident has no single "wrong explanation" to rule out; instead it tests whether the
agent **ranks multiple partial causes** instead of stopping at the first plausible one —
directly matching the scoring rubric's reward for agents that "critique, retry, branch"
rather than produce a single linear answer. Difficulty: **hard**.

**9. Unexplained small-seller dip — genuinely indeterminate** *(synthetic, medium)*
Metric: avg review_score for one low-volume seller (n=3–4 reviews) drops over 2 weeks.
Cause: **none planted anywhere** — no delivery delay, no product issue, no payment
issue, no marketing event in any source. This simulates real-world noise (an off-platform
problem, or just a small, unlucky sample) that the data cannot explain. Correct answer:
"insufficient evidence across all four sources; sample size (n≤4) is too small to
distinguish a real cause from noise." Tests whether the agent will say "cannot be
determined" instead of inventing a plausible-sounding story. Difficulty: **medium** (the
hard part is resisting a false-positive explanation, not finding one).

**10. Macro-level AOV drift — genuinely indeterminate** *(synthetic, hard)*
Metric: average order value declines gradually (~5%) over a full quarter nationally.
Cause: **none planted** — no concentration in any seller, state, category, payment type,
or marketing cohort; the drift is broad-based and small per-segment. Correct answer:
"every internal hypothesis we can check (seller, region, category, payment mix, marketing
cohort) comes back flat or inconclusive; the cause is most likely outside these four
sources (e.g. macroeconomic) and cannot be confirmed from this data." Tests the agent's
ability to systematically rule out every internal hypothesis **and then stop**, rather
than reaching for an external cause it has no evidence for. Difficulty: **hard** — this
is the incident most likely to tempt an agent into confident hallucination.

### Mix check
Easy: 1, 3, 4 (3). Medium: 2, 5, 9 (3). Hard: 6 (medium-hard), 7, 8, 10 (4, one borderline).
Indeterminate-by-design: 9, 10 (2, as required).

### Proposed demo questions (3)

1. **"Why did order volume spike on 24 November 2017?"** — incident 1. Fast, clean,
   dramatic (7x), and immediately checkable against public knowledge of Black Friday.
   Good opener: proves the agent works at all before the harder cases.
2. **"Why did review scores for [category C] fall in [month]?"** — incident 6. The
   single best showcase of the critic actually disproving a plausible wrong answer
   (the delivery-delay story it just confirmed in a different question), not just
   confirming the first guess.
3. **"Why has average order value been declining this quarter?"** — incident 10. Shows
   the agent ruling out every hypothesis it can check and then correctly stopping instead
   of fabricating a cause — the most distinctive, hardest-to-fake behavior for judges to
   see, and it directly demonstrates "what it ruled out," which is in the project's own
   one-line description.

---

## Scratch data location

Downloaded CSVs are in `/tmp/olist-scratch/` (core dataset) and
`/tmp/olist-scratch/marketing-funnel/` (funnel dataset) on this machine — not in any
git repository. `/tmp` is cleared on reboot; re-download with:
`kaggle datasets download -d olistbr/brazilian-ecommerce --unzip` and
`kaggle datasets download -d olistbr/marketing-funnel-olist --unzip` (Kaggle
credentials are already configured on this machine under `~/.kaggle/`).

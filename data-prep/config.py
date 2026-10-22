"""Shared constants for build_sample.py and inject_incidents.py.

Single source of truth for every window, ID and threshold used by both scripts, so the
sample built in step 1 always has enough density in exactly the rows step 2 needs to
perturb. Nothing in here is written into the sample itself -- it's build-time config,
not data.
"""
import os

# Raw Kaggle files. Override with OLIST_RAW_DIR if you've put them somewhere else.
RAW_DIR = os.environ.get("OLIST_RAW_DIR", "/tmp/olist-scratch")
RAW_CORE = RAW_DIR
RAW_MARKETING = os.path.join(RAW_DIR, "marketing-funnel")

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

SEED = 42

# Standard convention used wherever "revenue" appears in the answer key or the
# detectability/premise checks: sum(payments.payment_value) for orders.order_status ==
# 'delivered' only. A canceled/unavailable order's item rows still exist (we never
# delete rows just for a status change), so a naive sum(price) over all order_items
# would not reflect what the business actually collected -- this definition is what
# the premise tests use, and the agent's own metric should use it too. (Revision 2,
# after Nikolay's independent check found incident 3's and 8's premises didn't hold
# under a naive all-orders revenue sum.)
REVENUE_DEFINITION = "sum(payment_value) where order_status == 'delivered'"

# ---------------------------------------------------------------------------
# Retention windows (all dates inclusive, as 'YYYY-MM-DD' strings).
# Each window is kept at (near-)100% so the incident placed there is detectable.
# See research/olist-dataset-and-incident-plan.md Revision 1 for the sizing math.
# ---------------------------------------------------------------------------

# Incident 1 (real, untouched) -- Black Friday 2017
WINDOW_BLACK_FRIDAY = ("2017-11-20", "2017-11-27")

# Incident 2 (real, untouched) -- truck drivers' strike, widened for in-transit orders
WINDOW_STRIKE = ("2018-04-23", "2018-06-11")

# Incident 3 -- single seller forced to canceled/unavailable for 2 weeks
INCIDENT_3_SELLER_ID = "f8db351d8c4c4c22c6835c19a46f01b0"
WINDOW_INCIDENT_3 = ("2018-01-08", "2018-01-21")

# Incident 4 -- RJ freight surcharge (baseline month, incident month)
INCIDENT_4_STATE = "RJ"
MONTH_INCIDENT_4_BASELINE = (2018, 7)
MONTH_INCIDENT_4_INCIDENT = (2018, 8)
INCIDENT_4_FREIGHT_MULTIPLIER = 1.5  # bumped from 1.25: RJ Jul/Aug naturally differ by
# ~12% even unperturbed (seasonal item mix), so 1.25x alone produced only a +9.3%
# measured change -- see detectability_report.md revision note

# Incident 5 -- MG payment-mix shift (boleto -> credit_card), 3 baseline + 3 incident weeks
INCIDENT_5_STATE = "MG"
WINDOW_INCIDENT_5_BASELINE = ("2018-02-12", "2018-03-04")
WINDOW_INCIDENT_5_INCIDENT = ("2018-03-05", "2018-03-25")
INCIDENT_5_BOLETO_FLIP_FRACTION = 0.55  # fraction of boleto rows in-window flipped to credit_card

# Incident 6 -- review-score dip for one category, 3 months (baseline / incident / after)
# NOTE (build-time correction): Feb/Mar 2018 have a real, naturally elevated delivery
# lateness for this category (20.7% / 27.3%, measured from raw unperturbed data) that
# would contaminate the "delivery-delay decoy should look normal" check. Moved one month
# earlier -- Dec 2017 (7.5% late) / Jan 2018 (5.6% late) / Feb 2018 (after) -- where the
# incident month is genuinely clean of that confound.
INCIDENT_6_CATEGORY = "relogios_presentes"  # watches_gifts
MONTH_INCIDENT_6_BASELINE = (2017, 12)
MONTH_INCIDENT_6_INCIDENT = (2018, 1)
MONTH_INCIDENT_6_AFTER = (2018, 2)
INCIDENT_6_SCORE_CAP = 2  # scores in-window capped at this value

# Incident 7 -- marketing cohort (paid_search deals closed in Mar 2018) whose order
# follow-through is suppressed in the two months after close
INCIDENT_7_ORIGIN = "paid_search"
MONTH_INCIDENT_7_COHORT_CLOSE = (2018, 3)
WINDOW_INCIDENT_7_SUPPRESS = ("2018-04-01", "2018-05-31")
INCIDENT_7_SUPPRESSION_FRACTION = 0.70  # fraction of this cohort's order_items dropped

# Incident 8 -- RJ compounding revenue drop: two partial, independently-insufficient
# causes on the metric the question actually names (total delivered-order revenue).
# NOTE (build-time correction, Revision 2): the original design (freight +25%, review
# score -1) never moved total revenue -- a freight *increase* raises payment_value if
# anything, and a review-score dip doesn't mechanically move the current period's
# revenue at all. Nikolay's independent premise check caught this (RJ weekly revenue
# was flat/non-dropping across June). Redesigned with two causes that both genuinely
# pull revenue down: a volume cut (cancellations spread across many sellers, not one --
# distinct from incident 3) and a price discount on the orders that still complete.
# NOTE (earlier correction): the raw dataset's order_purchase_timestamp effectively
# ends in Aug 2018 (Sep 2018 has 16 orders nationwide, Oct has 4) -- Sep 2018 is unusable.
# Window stays 12-30 Jun 2018: after the strike window closes (11 Jun) so it doesn't
# stack with incident 2's real delivery-disruption signal.
WINDOW_INCIDENT_8 = ("2018-06-12", "2018-06-30")
WINDOW_INCIDENT_8_BASELINE = ("2018-06-01", "2018-06-11")  # immediately prior, for the premise test's daily-rate comparison
INCIDENT_8_CANCEL_FRACTION = 0.20  # of delivered RJ orders in-window, spread across sellers
INCIDENT_8_PRICE_DISCOUNT = 0.85  # applied to items.price for orders that still complete

# Incident 9 -- tiny seller, genuinely unexplained dip (no other field touched)
INCIDENT_9_SELLER_ID = "1430239a858e7682bbc43b20758af153"
WINDOW_INCIDENT_9 = ("2017-12-01", "2017-12-15")
INCIDENT_9_SCORE_MAP = {0: 2, 1: 1, 2: 2}  # positional remap of this seller's in-window review scores

# Incident 10 -- macro, broad-based AOV drift, no segment concentration
# NOTE (build-time correction): the original 1%/3.5%/5% cumulative drift was invisible
# at state/category granularity -- natural month-to-month price-mix noise at n~150 is far
# bigger than a 5% move (measured per-state spread of 53 percentage points with the old
# settings). Two changes: bigger drift (now ~20% cumulative by October, still a gradual
# multi-month trend, not a single-day event) and more rows per segment (300, not 150) to
# shrink the noise floor. This raises incident 10's retention cost -- see
# detectability_report.md for the final measured size.
MONTHS_INCIDENT_10 = [(2017, 8), (2017, 9), (2017, 10)]
INCIDENT_10_MONTHLY_MULTIPLIERS = {(2017, 8): 0.95, (2017, 9): 0.88, (2017, 10): 0.80}

# Stratified background retention for incident 10's "rule out every segment" requirement.
# NOTE (build-time correction): PR/SC/BA/DF never reach 300/month naturally (their whole
# population in this quarter is only ~170-250/month) -- the stratified sampler just took
# everything available, which was still too thin to separate the injected drift from
# natural price-mix noise for those four states (one of them read as flat, another as a
# much bigger drop than the national average). Restricted to the four states whose
# natural volume reliably clears 300+/month in this quarter: SP, RJ, MG, RS. The honest
# reading is that this dataset only supports confident per-state detection for its
# higher-volume states -- not a result to hide.
INCIDENT_10_TOP_STATES = ["SP", "RJ", "MG", "RS"]
INCIDENT_10_MIN_PER_STATE_MONTH = 300
INCIDENT_10_TOP_CATEGORIES = [
    "cama_mesa_banho", "beleza_saude", "esporte_lazer", "informatica_acessorios",
    "moveis_decoracao", "utilidades_domesticas", "relogios_presentes", "telefonia",
    "automotivo", "brinquedos",
]
INCIDENT_10_MIN_PER_CATEGORY_MONTH = 300

# General background sample for everything else (seasonality / realism, not tied to
# any incident)
BACKGROUND_SAMPLE_RATE = 0.02

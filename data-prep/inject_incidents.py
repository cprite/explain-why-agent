#!/usr/bin/env python3
"""Apply incidents 3-10 to the sample built by build_sample.py.

Deterministic (fixed seed). Each incident is switchable on its own via --incidents.
Incidents 1 and 2 are real, already-present events in the raw data and are never
touched here -- build_sample.py's windows just make sure they survive sampling intact.

Every mechanic perturbs a field that already exists on a real row (freight_value,
payment_type, review_score, order_status, payment_value, payment_installments,
review_comment_*) or removes whole order rows -- nothing adds a column, a flag, or any
other marker of which rows were touched. Three cross-field consistency passes run after
the per-incident mutations so a row that was touched still looks like a real row:
reconcile_payments() (payments match the new item totals), the review-text fix inside
each score-changing incident (comment text matches the new score), and incident_3's own
delivery-date nulling (a canceled/unavailable order doesn't have a delivery date). See
`detectability_report.py`'s leakage section for the tests that catch regressions here.

The only record of what was injected is out/answer_key.json, which this script writes.

Usage:
    python3 inject_incidents.py [--incidents 3,4,5,6,7,8,9,10] [--sample-dir out]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

import config as cfg

def load_comment_pool():
    """Real low-score (1-2 star) comment messages, read from the raw dataset at run
    time (score<=2, 15-140 chars) -- generic customer complaints, safe to reuse for any
    order since they don't reference anything order-specific.

    Revision 2 fix: an earlier version embedded a hardcoded list of only 29 texts, which
    were then reused ~8x each across 232 replacements -- a ~97% duplicate rate vs the
    real dataset's natural ~3.7% duplicate rate among low-score comments (measured:
    10,488 distinct among 10,890 non-null). Reading the full real pool (~7,300 distinct
    texts in this length range) instead means random draws collide about as often as
    real data does.
    """
    raw_path = os.path.join(cfg.RAW_CORE, "olist_order_reviews_dataset.csv")
    raw_reviews = pd.read_csv(raw_path, usecols=["review_score", "review_comment_message"])
    low = raw_reviews.loc[
        (raw_reviews.review_score <= 2) & raw_reviews.review_comment_message.notna(),
        "review_comment_message",
    ]
    low = low[low.str.len().between(15, 140)]
    return low.drop_duplicates().tolist()

# Measured from the raw dataset: P(title blank), P(message blank) by review_score
REVIEW_BLANK_RATES = {1: (0.836, 0.235), 2: (0.848, 0.319)}

# Measured from the raw dataset: MG credit_card payment_installments distribution
MG_CC_INSTALLMENTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
MG_CC_INSTALLMENT_PROBS = [0.304, 0.159, 0.145, 0.096, 0.073, 0.053, 0.024, 0.059, 0.008, 0.075]
MG_CC_INSTALLMENT_PROBS = [p / sum(MG_CC_INSTALLMENT_PROBS) for p in MG_CC_INSTALLMENT_PROBS]

RECONCILE_TOLERANCE = 0.05  # matches the real raw dataset's natural mismatch rate at this threshold (~0.26%)


def load_sample(d):
    orders = pd.read_csv(os.path.join(d, "orders", "orders.csv"), parse_dates=[
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ])
    items = pd.read_csv(os.path.join(d, "orders", "order_items.csv"))
    customers = pd.read_csv(os.path.join(d, "orders", "customers.csv"))
    products = pd.read_csv(os.path.join(d, "orders", "products.csv"))
    payments = pd.read_csv(os.path.join(d, "payments", "order_payments.csv"))
    reviews = pd.read_csv(os.path.join(d, "reviews", "order_reviews.csv"))
    mql = pd.read_csv(os.path.join(d, "marketing", "marketing_qualified_leads.csv"), parse_dates=["first_contact_date"])
    closed = pd.read_csv(os.path.join(d, "marketing", "closed_deals.csv"), parse_dates=["won_date"])
    return dict(orders=orders, items=items, customers=customers, products=products,
                payments=payments, reviews=reviews, mql=mql, closed=closed)


def save_sample(data, d):
    data["orders"].to_csv(os.path.join(d, "orders", "orders.csv"), index=False)
    data["items"].to_csv(os.path.join(d, "orders", "order_items.csv"), index=False)
    data["customers"].to_csv(os.path.join(d, "orders", "customers.csv"), index=False)
    data["products"].to_csv(os.path.join(d, "orders", "products.csv"), index=False)
    data["payments"].to_csv(os.path.join(d, "payments", "order_payments.csv"), index=False)
    data["reviews"].to_csv(os.path.join(d, "reviews", "order_reviews.csv"), index=False)
    data["mql"].to_csv(os.path.join(d, "marketing", "marketing_qualified_leads.csv"), index=False)
    data["closed"].to_csv(os.path.join(d, "marketing", "closed_deals.csv"), index=False)


def in_window(ts, start, end):
    return (ts >= pd.Timestamp(start)) & (ts < pd.Timestamp(end) + pd.Timedelta(days=1))


def order_state_map(data):
    return data["orders"].merge(
        data["customers"][["customer_id", "customer_state"]], on="customer_id", how="left"
    ).set_index("order_id")["customer_state"]


def item_totals_by_order(items):
    return (items["price"] + items["freight_value"]).groupby(items["order_id"]).sum()


TABLE_KEYS = {
    "orders": ["order_id"],
    "items": ["order_id", "order_item_id"],
    "payments": ["order_id", "payment_sequential"],
    "reviews": ["review_id"],
}


def snapshot_tables(data):
    return {t: data[t].copy() for t in TABLE_KEYS}


def count_changed_rows(before, after, key_cols):
    """Rows added, removed, or with any column value changed -- used to compute
    rows_changed per incident (Revision 4, at Nikolay's request: counted by the script,
    not typed by hand)."""
    b = before.set_index(key_cols)
    a = after.set_index(key_cols)
    common = b.index.intersection(a.index)
    removed = b.index.difference(a.index)
    added = a.index.difference(b.index)
    changed_common = 0
    if len(common) > 0:
        bc = b.loc[common]
        ac = a.loc[common]
        same = (bc == ac) | (bc.isna() & ac.isna())
        changed_common = int((~same.all(axis=1)).sum())
    return changed_common + len(removed) + len(added)


def rows_changed_total(before_snap, after_snap):
    return sum(count_changed_rows(before_snap[t], after_snap[t], TABLE_KEYS[t]) for t in TABLE_KEYS)


_COMMENT_POOL_CACHE = None


def _get_pool():
    global _COMMENT_POOL_CACHE
    if _COMMENT_POOL_CACHE is None:
        _COMMENT_POOL_CACHE = load_comment_pool()
    return _COMMENT_POOL_CACHE


def fix_review_text(reviews, order_ids, rng):
    """Make comment text consistent with whatever score a review now has. Only acts on
    rows whose current score is <=2 -- a 3-5 star review is left alone even if this
    function is called on it (incident 8 only drops some reviews to <=2)."""
    pool = _get_pool()
    mask = reviews.order_id.isin(order_ids) & (reviews["review_score"] <= 2)
    idx = reviews.index[mask]
    for i in idx:
        score = int(reviews.at[i, "review_score"])
        _title_blank_rate, msg_blank_rate = REVIEW_BLANK_RATES[score]
        # Titles are blank 84-85% of the time in the real data and we have no pool of
        # real short titles to draw from, so always null it here -- indistinguishable
        # on disk from the rare real non-blank case once written to CSV (both empty).
        reviews.at[i, "review_comment_title"] = np.nan
        if rng.random() < msg_blank_rate:
            reviews.at[i, "review_comment_message"] = np.nan
        else:
            reviews.at[i, "review_comment_message"] = rng.choice(pool)
    return len(idx)


def incident_3(data, rng):
    orders = data["orders"]
    seller_order_ids = set(data["items"].loc[data["items"].seller_id == cfg.INCIDENT_3_SELLER_ID, "order_id"])
    mask = orders.order_id.isin(seller_order_ids) & in_window(
        orders.order_purchase_timestamp, *cfg.WINDOW_INCIDENT_3
    )
    affected = orders.loc[mask, "order_id"].tolist()
    statuses = ["canceled", "unavailable"]
    orders.loc[mask, "order_status"] = [statuses[i % 2] for i in range(mask.sum())]
    # real canceled/unavailable orders essentially never have a delivery date (measured
    # from raw data: carrier_date null 88-100%, customer_date null 99-100%) -- null both
    # so the status change doesn't leave a now-impossible "delivered after cancellation"
    orders.loc[mask, "order_delivered_carrier_date"] = pd.NaT
    orders.loc[mask, "order_delivered_customer_date"] = pd.NaT
    rv_mask = data["reviews"].order_id.isin(affected)
    data["reviews"].loc[rv_mask, "review_score"] = 1
    n_text_fixed = fix_review_text(data["reviews"], affected, rng)
    return dict(incident=3, affected_orders=len(affected), affected_reviews=int(rv_mask.sum()), text_fixed=n_text_fixed)


def incident_4(data, rng):
    items = data["items"]
    orders = data["orders"]
    state = order_state_map(data)
    y, m = cfg.MONTH_INCIDENT_4_INCIDENT
    order_month = orders.set_index("order_id")["order_purchase_timestamp"]
    target_orders = set(orders.loc[
        (order_month.reindex(orders.order_id).dt.year.values == y)
        & (order_month.reindex(orders.order_id).dt.month.values == m)
        & (state.reindex(orders.order_id).values == cfg.INCIDENT_4_STATE),
        "order_id"
    ])
    mask = items.order_id.isin(target_orders)
    items.loc[mask, "freight_value"] = (items.loc[mask, "freight_value"] * cfg.INCIDENT_4_FREIGHT_MULTIPLIER).round(2)
    return dict(incident=4, affected_order_items=int(mask.sum()), affected_orders=len(target_orders))


def incident_5(data, rng):
    orders = data["orders"]
    payments = data["payments"]
    state = order_state_map(data)
    window_orders = set(orders.loc[
        in_window(orders.order_purchase_timestamp, *cfg.WINDOW_INCIDENT_5_INCIDENT)
        & (state.reindex(orders.order_id).values == cfg.INCIDENT_5_STATE),
        "order_id"
    ])
    boleto_mask = payments.order_id.isin(window_orders) & (payments.payment_type == "boleto")
    boleto_idx = payments.index[boleto_mask]
    n_flip = int(round(len(boleto_idx) * cfg.INCIDENT_5_BOLETO_FLIP_FRACTION))
    flip_idx = rng.choice(boleto_idx, size=n_flip, replace=False) if n_flip > 0 else np.array([], dtype=int)
    payments.loc[flip_idx, "payment_type"] = "credit_card"
    # boleto is always 1 installment; a relabeled credit_card payment that's still
    # always exactly 1 installment is itself a tell -- draw from the real MG
    # credit_card installment distribution instead
    if len(flip_idx) > 0:
        drawn = rng.choice(MG_CC_INSTALLMENTS, size=len(flip_idx), p=MG_CC_INSTALLMENT_PROBS)
        payments.loc[flip_idx, "payment_installments"] = drawn
    return dict(incident=5, boleto_rows_in_window=len(boleto_idx), flipped_to_credit_card=n_flip)


def incident_6(data, rng):
    orders = data["orders"]
    items = data["items"]
    products = data["products"]
    reviews = data["reviews"]
    y, m = cfg.MONTH_INCIDENT_6_INCIDENT
    cat_products = set(products.loc[products.product_category_name == cfg.INCIDENT_6_CATEGORY, "product_id"])
    cat_order_ids = set(items.loc[items.product_id.isin(cat_products), "order_id"])
    order_month = orders.set_index("order_id")["order_purchase_timestamp"]
    month_orders = set(orders.loc[
        (order_month.reindex(orders.order_id).dt.year.values == y)
        & (order_month.reindex(orders.order_id).dt.month.values == m),
        "order_id"
    ])
    target = cat_order_ids & month_orders
    mask = reviews.order_id.isin(target)
    before = reviews.loc[mask, "review_score"].copy()
    reviews.loc[mask, "review_score"] = np.minimum(before, cfg.INCIDENT_6_SCORE_CAP)
    n_text_fixed = fix_review_text(reviews, target, rng)
    return dict(incident=6, target_orders=len(target), reviews_capped=int(mask.sum()), text_fixed=n_text_fixed)


def incident_7(data, rng):
    orders = data["orders"]
    items = data["items"]
    closed = data["closed"]
    mql = data["mql"]
    closed_m = closed.merge(mql[["mql_id", "origin"]], on="mql_id", how="left")
    cohort_mask = (
        (closed_m["origin"] == cfg.INCIDENT_7_ORIGIN)
        & (closed_m["won_date"].dt.year == cfg.MONTH_INCIDENT_7_COHORT_CLOSE[0])
        & (closed_m["won_date"].dt.month == cfg.MONTH_INCIDENT_7_COHORT_CLOSE[1])
    )
    cohort_sellers = set(closed_m.loc[cohort_mask, "seller_id"])

    window_orders = set(orders.loc[
        in_window(orders.order_purchase_timestamp, *cfg.WINDOW_INCIDENT_7_SUPPRESS), "order_id"
    ])
    cohort_window_order_ids = set(items.loc[
        items.seller_id.isin(cohort_sellers) & items.order_id.isin(window_orders), "order_id"
    ])
    n_drop = int(round(len(cohort_window_order_ids) * cfg.INCIDENT_7_SUPPRESSION_FRACTION))
    drop_ids = set(rng.choice(sorted(cohort_window_order_ids), size=n_drop, replace=False)) if n_drop > 0 else set()

    for key in ("orders", "items", "payments", "reviews"):
        data[key] = data[key][~data[key].order_id.isin(drop_ids)].reset_index(drop=True)

    return dict(incident=7, cohort_sellers=len(cohort_sellers), cohort_orders_in_window=len(cohort_window_order_ids),
                suppressed_orders=len(drop_ids))


def incident_8(data, rng):
    """RJ revenue drop, 12-30 Jun 2018: two partial, independently-insufficient causes
    on the metric the question actually names (delivered-order revenue) -- a volume
    cut (cancellations spread across many sellers, not concentrated like incident 3)
    and a price discount on the orders that still complete. Neither alone explains the
    full drop; see detectability_report.py's premise test for the measured size."""
    orders = data["orders"]
    items = data["items"]
    reviews = data["reviews"]
    state = order_state_map(data)
    delivered_orders = orders[orders.order_status == "delivered"]
    target_orders = sorted(set(delivered_orders.loc[
        in_window(delivered_orders.order_purchase_timestamp, *cfg.WINDOW_INCIDENT_8)
        & (state.reindex(delivered_orders.order_id).values == cfg.INCIDENT_4_STATE),
        "order_id"
    ]))

    n_cancel = int(round(len(target_orders) * cfg.INCIDENT_8_CANCEL_FRACTION))
    cancel_ids = set(rng.choice(target_orders, size=n_cancel, replace=False)) if n_cancel > 0 else set()
    discount_ids = set(target_orders) - cancel_ids

    cancel_mask = orders.order_id.isin(cancel_ids)
    statuses = ["canceled", "unavailable"]
    orders.loc[cancel_mask, "order_status"] = [statuses[i % 2] for i in range(cancel_mask.sum())]
    orders.loc[cancel_mask, "order_delivered_carrier_date"] = pd.NaT
    orders.loc[cancel_mask, "order_delivered_customer_date"] = pd.NaT
    rv_mask = reviews.order_id.isin(cancel_ids)
    reviews.loc[rv_mask, "review_score"] = 1
    n_text_fixed = fix_review_text(reviews, cancel_ids, rng)

    item_mask = items.order_id.isin(discount_ids)
    items.loc[item_mask, "price"] = (items.loc[item_mask, "price"] * cfg.INCIDENT_8_PRICE_DISCOUNT).round(2)

    return dict(incident=8, window_delivered_orders=len(target_orders), canceled=len(cancel_ids),
                discounted_orders=len(discount_ids), discounted_items=int(item_mask.sum()),
                affected_reviews=int(rv_mask.sum()), text_fixed=n_text_fixed)


def incident_9(data, rng):
    orders = data["orders"]
    items = data["items"]
    reviews = data["reviews"]
    seller_order_ids = set(items.loc[items.seller_id == cfg.INCIDENT_9_SELLER_ID, "order_id"])
    window_orders = set(orders.loc[
        in_window(orders.order_purchase_timestamp, *cfg.WINDOW_INCIDENT_9) & orders.order_id.isin(seller_order_ids),
        "order_id"
    ])
    rv = reviews[reviews.order_id.isin(window_orders)].sort_values("order_id")
    idx_list = rv.index.tolist()
    for pos, idx in enumerate(idx_list):
        if pos in cfg.INCIDENT_9_SCORE_MAP:
            reviews.loc[idx, "review_score"] = cfg.INCIDENT_9_SCORE_MAP[pos]
    n_text_fixed = fix_review_text(reviews, window_orders, rng)
    return dict(incident=9, orders_in_window=len(window_orders), reviews_remapped=len(idx_list), text_fixed=n_text_fixed)


def incident_10(data, rng):
    orders = data["orders"]
    items = data["items"]
    order_month = orders.set_index("order_id")["order_purchase_timestamp"]
    total_affected = 0
    for (y, m), mult in cfg.INCIDENT_10_MONTHLY_MULTIPLIERS.items():
        month_orders = set(orders.loc[
            (order_month.reindex(orders.order_id).dt.year.values == y)
            & (order_month.reindex(orders.order_id).dt.month.values == m),
            "order_id"
        ])
        mask = items.order_id.isin(month_orders)
        items.loc[mask, "price"] = (items.loc[mask, "price"] * mult).round(2)
        total_affected += int(mask.sum())
    return dict(incident=10, affected_order_items=total_affected, multipliers=cfg.INCIDENT_10_MONTHLY_MULTIPLIERS)


def reconcile_payments(data, totals_before):
    """After any incident that changed price/freight (4, 8, 10), scale that order's
    payment rows proportionally so payment_value still sums to the item total -- real
    orders reconcile to within a few cents; a surcharge that the customer apparently
    never paid for is itself a tell. Only touches orders whose item total actually
    changed (compared to totals_before, captured right after load_sample), so the
    dataset's natural ~0.26% baseline mismatch rate on untouched orders is preserved,
    not papered over."""
    items = data["items"]
    payments = data["payments"]
    totals_after = item_totals_by_order(items)
    common = totals_before.index.intersection(totals_after.index)
    changed = common[(totals_after.loc[common] - totals_before.loc[common]).abs() > 0.01]

    pay_totals = payments.groupby("order_id")["payment_value"].sum()
    n_reconciled = 0
    for oid in changed:
        old_pay_total = pay_totals.get(oid)
        new_item_total = totals_after.loc[oid]
        if old_pay_total is None or old_pay_total == 0:
            continue
        ratio = new_item_total / old_pay_total
        mask = payments.order_id == oid
        payments.loc[mask, "payment_value"] = (payments.loc[mask, "payment_value"] * ratio).round(2)
        n_reconciled += 1
    return n_reconciled


# cause_types vocabulary (Revision 2, at Nikolay's request): volume, price_discount,
# mix_shift, single_seller, logistics_delay, product_quality, marketing_funnel,
# freight_cost, data_artefact, external_unknown, none. ("freight_cost" added -- a
# freight surcharge is a cost change, not a time delay, so "logistics_delay" was the
# wrong tag for incidents 4 and the old incident 8.) Every entry's "cause_types" is a
# list so an incident with two causes (8) can hold both.
ANSWER_KEY = [
    {
        "id": "incident-01", "question": "Why did order volume spike on 24 November 2017?",
        "metric": "daily order count", "segment": {"type": "national", "value": "all sellers"},
        "window_start": "2017-11-24", "window_end": "2017-11-25",
        "cause_types": ["volume"],
        "expected_mechanism": "A broad, marketplace-wide order-volume spike (383 distinct sellers sold vs ~130 on a normal nearby day) coinciding with an 8.6% average item-price drop, consistent with a platform-wide promotional event. The specific name 'Black Friday' is not provable from the data and is not required.",
        "sources": ["orders/order_items.csv (volume, price)"],
        "wrong_explanation_to_rule_out": "A logging error duplicated order records -- ruled out because order_ids are unique and average price genuinely dropped, which a duplication bug would not cause.",
        "determinable": True, "difficulty": "easy", "real_event": True,
    },
    {
        "id": "incident-02", "question": "Why did delivery lateness spike for deliveries completed the week of 28 May 2018?",
        "metric": "% orders late vs estimate, avg carrier-to-customer transit days (grouped by delivery week, not purchase week)",
        "segment": {"type": "national", "value": "multiple states and sellers"},
        "window_start": "2018-05-28", "window_end": "2018-06-04",
        "cause_types": ["logistics_delay"],
        "expected_mechanism": "A broad, multi-state (9 states measured, all elevated vs ~5% baseline), multi-seller spike in delivery lateness and transit time, with a corroborating review-score dip the same week, consistent with an external logistics disruption affecting the whole network. The specific name 'truck drivers' strike' is not provable from the data and is not required.",
        "sources": ["orders/orders.csv (delivery timestamps)", "reviews/order_reviews.csv (score dip)"],
        "wrong_explanation_to_rule_out": "One seller or region stopped shipping -- ruled out because the lateness spike is broad across many sellers and at least 9 different states, not concentrated.",
        "determinable": True, "difficulty": "medium", "real_event": True,
    },
    {
        "id": "incident-03", "question": f"Why did seller {cfg.INCIDENT_3_SELLER_ID}'s revenue drop to zero in mid-January 2018?",
        "metric": f"seller revenue ({cfg.REVENUE_DEFINITION}) / order_status",
        "segment": {"type": "seller", "value": cfg.INCIDENT_3_SELLER_ID},
        "window_start": cfg.WINDOW_INCIDENT_3[0], "window_end": cfg.WINDOW_INCIDENT_3[1],
        "cause_types": ["single_seller"],
        "expected_mechanism": f"That seller's orders in the window were marked canceled/unavailable (a real, existing status spike, with no delivery date -- not an absence of rows), so delivered-order revenue for this seller in-window is exactly $0 even though the order_items rows still exist ({cfg.REVENUE_DEFINITION} is the convention used here precisely because a naive sum over all rows would not show the drop). The few orders that still generated a review scored sharply negative with consistent complaint text -- consistent with a seller-side outage or suspension.",
        "sources": ["orders/orders.csv (order_status spike for this seller)", "reviews/order_reviews.csv (score collapse)"],
        "wrong_explanation_to_rule_out": "Marketplace-wide demand fell -- ruled out because every other seller's revenue in the same window is normal.",
        "determinable": True, "difficulty": "easy",
    },
    {
        "id": "incident-04", "question": "Why did average freight cost for Rio de Janeiro orders rise in August 2018?",
        "metric": "avg freight_value", "segment": {"type": "state", "value": cfg.INCIDENT_4_STATE},
        "window_start": f"{cfg.MONTH_INCIDENT_4_INCIDENT[0]}-{cfg.MONTH_INCIDENT_4_INCIDENT[1]:02d}-01",
        "window_end": f"{cfg.MONTH_INCIDENT_4_INCIDENT[0]}-{cfg.MONTH_INCIDENT_4_INCIDENT[1]:02d}-31",
        "cause_types": ["freight_cost"],
        "expected_mechanism": f"freight_value for RJ-bound order items rose ~31% in {cfg.MONTH_INCIDENT_4_INCIDENT[0]}-{cfg.MONTH_INCIDENT_4_INCIDENT[1]:02d} vs the {cfg.MONTH_INCIDENT_4_BASELINE[0]}-{cfg.MONTH_INCIDENT_4_BASELINE[1]:02d} baseline, and payment totals for those orders scale with it, consistent with a regional carrier/logistics surcharge.",
        "sources": ["orders/order_items.csv (freight_value)", "payments/order_payments.csv (totals move with it)"],
        "wrong_explanation_to_rule_out": "Orders got heavier/bigger -- ruled out because product_weight_g for the same orders is unchanged.",
        "determinable": True, "difficulty": "easy",
    },
    {
        "id": "incident-05", "question": "Why did the share of boleto payments fall in Minas Gerais in March 2018?",
        "metric": "% payments by payment_type", "segment": {"type": "state", "value": cfg.INCIDENT_5_STATE},
        "window_start": cfg.WINDOW_INCIDENT_5_INCIDENT[0], "window_end": cfg.WINDOW_INCIDENT_5_INCIDENT[1],
        "cause_types": ["mix_shift"],
        "expected_mechanism": "~55% of boleto payments in-window were reclassified as credit_card, with installment counts drawn from MG's real credit_card distribution (not all defaulting to 1), shifting MG's payment mix while total order volume in MG stayed flat -- consistent with a payment-processing or checkout-default change, not a demand change.",
        "sources": ["payments/order_payments.csv (payment_type mix, installment distribution)", "orders/orders.csv (confirm flat volume)"],
        "wrong_explanation_to_rule_out": "Overall demand in MG changed -- ruled out by flat order volume in the same window.",
        "determinable": True, "difficulty": "medium",
    },
    {
        "id": "incident-06", "question": f"Why did review scores for watches/gifts ({cfg.INCIDENT_6_CATEGORY}) fall in {cfg.MONTH_INCIDENT_6_INCIDENT[0]}-{cfg.MONTH_INCIDENT_6_INCIDENT[1]:02d}?",
        "metric": "avg review_score", "segment": {"type": "category", "value": cfg.INCIDENT_6_CATEGORY},
        "window_start": f"{cfg.MONTH_INCIDENT_6_INCIDENT[0]}-{cfg.MONTH_INCIDENT_6_INCIDENT[1]:02d}-01",
        "window_end": f"{cfg.MONTH_INCIDENT_6_INCIDENT[0]}-{cfg.MONTH_INCIDENT_6_INCIDENT[1]:02d}-31",
        "cause_types": ["product_quality"],
        "expected_mechanism": f"Review scores for this category specifically were capped low in {cfg.MONTH_INCIDENT_6_INCIDENT[0]}-{cfg.MONTH_INCIDENT_6_INCIDENT[1]:02d}, with comment text replaced to match (genuine low-score complaints or blank, in the real proportions), while delivery timing for the same category's orders in the same month is normal -- consistent with a product-quality issue, not a shipping delay.",
        "sources": ["reviews/order_reviews.csv (score drop, joined via order_items -> product_category)", "orders/orders.csv (delivery timing for the same orders, checked and found normal)"],
        "wrong_explanation_to_rule_out": "The delivery-delay story from incident 2 -- ruled out by checking this category's delivery timing in this window is unremarkable before accepting the product-quality explanation.",
        "determinable": True, "difficulty": "medium-hard",
    },
    {
        "id": "incident-07", "question": "Why didn't the March 2018 paid-search seller cohort's revenue ramp up the way earlier cohorts did?",
        "metric": f"seller-cohort revenue by month ({cfg.REVENUE_DEFINITION})",
        "segment": {"type": "marketing_cohort", "value": f"sellers closed via {cfg.INCIDENT_7_ORIGIN} in {cfg.MONTH_INCIDENT_7_COHORT_CLOSE[0]}-{cfg.MONTH_INCIDENT_7_COHORT_CLOSE[1]:02d}"},
        "window_start": cfg.WINDOW_INCIDENT_7_SUPPRESS[0], "window_end": cfg.WINDOW_INCIDENT_7_SUPPRESS[1],
        "cause_types": ["marketing_funnel"],
        "expected_mechanism": "~70% of this cohort's expected order volume (and the revenue with it) in the two months after closing was suppressed, while the marketing funnel data (leads, closed deals) is real and unperturbed -- consistent with a lead-quality or onboarding problem rather than a marketing-volume problem.",
        "sources": ["marketing/closed_deals.csv + marketing_qualified_leads.csv (the real lead/deal spike)", "orders/order_items.csv (suppressed follow-through revenue via closed_deals.seller_id -> order_items.seller_id)"],
        "wrong_explanation_to_rule_out": "Seasonal demand -- ruled out by checking organic-origin sellers' revenue in the same months is normal.",
        "determinable": True, "difficulty": "hard",
    },
    {
        "id": "incident-08", "question": "Why did Rio de Janeiro's total revenue drop in late June 2018 (12-30 Jun, vs 1-11 Jun)?",
        "metric": f"total revenue ({cfg.REVENUE_DEFINITION}), compared at the same daily rate since the window and baseline are different lengths",
        "segment": {"type": "state", "value": cfg.INCIDENT_4_STATE},
        "window_start": cfg.WINDOW_INCIDENT_8[0], "window_end": cfg.WINDOW_INCIDENT_8[1],
        "cause_types": ["volume", "price_discount"],
        "expected_mechanism": f"Two partial, independently-insufficient causes: {cfg.INCIDENT_8_CANCEL_FRACTION:.0%} of delivered RJ orders in-window were canceled/unavailable (spread across many sellers, not concentrated like incident 3 -- a volume cut), and the orders that still completed had their price discounted {1-cfg.INCIDENT_8_PRICE_DISCOUNT:.0%} -- neither alone explains the full daily-revenue drop vs the 1-11 Jun baseline; the agent should rank both as partial causes rather than stopping at the first plausible one.",
        "sources": ["orders/orders.csv (order_status -- the cancellations)", "orders/order_items.csv (price -- the discount)", "payments/order_payments.csv (totals reconcile with both)"],
        "wrong_explanation_to_rule_out": "A single seller's problem -- ruled out because the cancellations are spread across many sellers, not one.",
        "determinable": True, "difficulty": "hard",
    },
    {
        "id": "incident-09", "question": f"Why did seller {cfg.INCIDENT_9_SELLER_ID}'s review scores drop in early December 2017?",
        "metric": "avg review_score", "segment": {"type": "seller", "value": cfg.INCIDENT_9_SELLER_ID},
        "window_start": cfg.WINDOW_INCIDENT_9[0], "window_end": cfg.WINDOW_INCIDENT_9[1],
        "cause_types": ["none"],
        "expected_mechanism": "No cause planted anywhere -- no delivery delay, no product issue, no payment issue, no marketing event in any source. Correct answer: insufficient evidence across all four sources; sample size (n=3) is too small to distinguish a real cause from noise.",
        "sources": ["reviews/order_reviews.csv (the only source with a signal at all)"],
        "wrong_explanation_to_rule_out": "Any confident single-cause story -- this incident specifically tests whether the agent will say 'cannot be determined' instead of inventing one.",
        "determinable": False, "difficulty": "medium",
    },
    {
        "id": "incident-10", "question": "Why has average order value been declining since August 2017?",
        "metric": "average order value: sum(payment_value) per order (true AOV, not average order_items.price -- those differ whenever items-per-order shifts; measured here on the actual metric the question names)",
        "segment": {"type": "national", "value": "all segments"},
        "window_start": f"{cfg.MONTHS_INCIDENT_10[0][0]}-{cfg.MONTHS_INCIDENT_10[0][1]:02d}-01",
        "window_end": f"{cfg.MONTHS_INCIDENT_10[-1][0]}-{cfg.MONTHS_INCIDENT_10[-1][1]:02d}-31",
        "cause_types": ["external_unknown"],
        "expected_mechanism": "A broad-based decline in average order value (-8.2% Aug->Oct 2017, measured as payment total per order -- smaller than the underlying item-price drop of -11.8%, since only item price was perturbed and freight stayed flat, diluting the per-order figure) moving the same direction in every state checked (no segment goes against the trend), with category-level checks noisier but mostly consistent. Correct answer: every internal hypothesis we can check comes back flat or directionally consistent; the cause is most likely external (e.g. macroeconomic) and cannot be confirmed from these four sources.",
        "sources": ["payments/order_payments.csv (payment_value per order, the actual AOV)", "orders/order_items.csv (price, checked per-state, per-category, per-seller as the underlying driver)"],
        "wrong_explanation_to_rule_out": "Any single-segment explanation (one state, one category, one seller) -- this incident tests ruling out every internal hypothesis and then correctly stopping instead of fabricating an external cause with no evidence.",
        "determinable": False, "difficulty": "hard",
    },
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", default="3,4,5,6,7,8,9,10")
    ap.add_argument("--sample-dir", default=cfg.OUT_DIR)
    args = ap.parse_args()
    enabled = set(int(x) for x in args.incidents.split(",") if x.strip())

    data = load_sample(args.sample_dir)
    rng = np.random.default_rng(cfg.SEED + 1)  # distinct stream from build_sample.py

    totals_before = item_totals_by_order(data["items"])

    funcs = {3: incident_3, 4: incident_4, 5: incident_5, 6: incident_6,
             7: incident_7, 8: incident_8, 9: incident_9, 10: incident_10}
    price_freight_incidents = {4, 8, 10}  # these need reconcile_payments() run right
    # after them (not once at the end) so rows_changed correctly attributes the
    # resulting payment-row changes to the incident that caused them. Safe to call
    # reconcile_payments repeatedly -- it's a no-op (ratio=1) on already-reconciled
    # orders, since it always compares against the one fixed totals_before snapshot.

    applied = []
    rows_changed_by_incident = {}
    for n in sorted(enabled):
        if n in funcs:
            before_snap = snapshot_tables(data)
            result = funcs[n](data, rng)
            if n in price_freight_incidents:
                reconcile_payments(data, totals_before)
            after_snap = snapshot_tables(data)
            rows_changed = rows_changed_total(before_snap, after_snap)
            rows_changed_by_incident[n] = rows_changed
            result["rows_changed"] = rows_changed
            applied.append(result)
            print(f"Applied incident {n}: {result}")

    save_sample(data, args.sample_dir)

    answer_key = []
    for entry in ANSWER_KEY:
        n = int(entry["id"].split("-")[1])
        rows_changed = rows_changed_by_incident.get(n, 0)
        answer_key.append({
            **entry, "incident": n,
            "injected": rows_changed > 0,  # real_event incidents (1, 2) are never in
            # funcs, so rows_changed defaults to 0 and injected is correctly False
            "rows_changed": rows_changed,
        })
    with open(os.path.join(args.sample_dir, "answer_key.json"), "w") as f:
        json.dump(answer_key, f, indent=2, default=str)
    print(f"Wrote {os.path.join(args.sample_dir, 'answer_key.json')}")
    print(f"rows_changed by incident: {rows_changed_by_incident}")


if __name__ == "__main__":
    main()

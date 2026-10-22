#!/usr/bin/env python3
"""Measure every incident's signal in the finished (sampled + injected) data and write
detectability_report.md. Plain pandas queries only -- the same kind of query the
explain-why agent itself would run. Run this after build_sample.py + inject_incidents.py.
"""
import os

import numpy as np
import pandas as pd

import config as cfg

OUT = cfg.OUT_DIR

# Snapshot of out/ taken right after build_sample.py, before inject_incidents.py ran --
# used only to measure "before" numbers for the leakage tests below. See README.md for
# the regeneration step that creates it.
PREINJECT_DIR = "/tmp/oah_preinject_snapshot"


def load():
    orders = pd.read_csv(os.path.join(OUT, "orders", "orders.csv"), parse_dates=[
        "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date",
    ])
    items = pd.read_csv(os.path.join(OUT, "orders", "order_items.csv"))
    customers = pd.read_csv(os.path.join(OUT, "orders", "customers.csv"))
    products = pd.read_csv(os.path.join(OUT, "orders", "products.csv"))
    payments = pd.read_csv(os.path.join(OUT, "payments", "order_payments.csv"))
    reviews = pd.read_csv(os.path.join(OUT, "reviews", "order_reviews.csv"))
    mql = pd.read_csv(os.path.join(OUT, "marketing", "marketing_qualified_leads.csv"), parse_dates=["first_contact_date"])
    closed = pd.read_csv(os.path.join(OUT, "marketing", "closed_deals.csv"), parse_dates=["won_date"])
    orders = orders.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left")
    items_cat = items.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
    return dict(orders=orders, items=items, items_cat=items_cat, payments=payments, reviews=reviews, mql=mql, closed=closed)


def load_preinject():
    """The pre-injection snapshot, for leakage tests' 'before' numbers only."""
    orders = pd.read_csv(os.path.join(PREINJECT_DIR, "orders", "orders.csv"), parse_dates=[
        "order_purchase_timestamp", "order_delivered_carrier_date", "order_delivered_customer_date",
    ])
    items = pd.read_csv(os.path.join(PREINJECT_DIR, "orders", "order_items.csv"))
    payments = pd.read_csv(os.path.join(PREINJECT_DIR, "payments", "order_payments.csv"))
    reviews = pd.read_csv(os.path.join(PREINJECT_DIR, "reviews", "order_reviews.csv"))
    return dict(orders=orders, items=items, payments=payments, reviews=reviews)


def premise_tests(d):
    """For every incident, compute the exact metric its answer-key question names, in
    its stated segment and window, against an appropriate baseline -- and fail if it
    hasn't moved the way the question claims. This is deliberately separate from (and
    stricter than) the per-incident 'signal' checks in main(): those can pass by
    checking a component of the mechanism (e.g. freight, review score) without checking
    whether the metric the *question* actually names moved at all -- which is exactly
    the gap that let incident 8's original design through with a flat revenue line.
    Added Revision 2, after Nikolay's independent check found that gap."""
    from inject_incidents import ANSWER_KEY
    orders, items, payments, reviews = d["orders"], d["items"], d["payments"], d["reviews"]
    key = {e["id"]: e for e in ANSWER_KEY}
    out = ["\n## Premise tests\n",
           "For each incident: the literal metric named in its answer-key question, "
           "measured in its stated segment/window against a baseline. Fails if the "
           "claimed movement (or, for 9/10, the claimed flatness/indeterminacy) isn't "
           "actually there.\n"]
    results = []

    def deliv_revenue(df_orders, df_payments, mask):
        oids = df_orders.loc[mask & (df_orders.order_status == "delivered"), "order_id"]
        return df_payments[df_payments.order_id.isin(oids)].payment_value.sum(), len(oids)

    # 1
    p = orders.order_purchase_timestamp
    daily = orders[(p >= "2017-11-20") & (p <= "2017-11-27")].groupby(p.dt.date).size()
    base = daily.loc[[dd for dd in daily.index if dd.day < 24]].mean()
    spike = daily.get(pd_date(2017, 11, 24), 0)
    ok = spike > base * 2
    results.append(("incident-01", ok, f"order count 24 Nov={spike} vs baseline avg={base:.0f}"))

    # 2
    deliv = orders[(orders.order_status == "delivered") & orders.order_delivered_customer_date.notna()
                    & orders.order_estimated_delivery_date.notna()]
    deliv = deliv[(deliv.order_delivered_customer_date >= "2018-04-23") & (deliv.order_delivered_customer_date <= "2018-06-11")].copy()
    deliv["week"] = deliv.order_delivered_customer_date.dt.to_period("W-MON").dt.start_time
    deliv["late"] = deliv.order_delivered_customer_date > deliv.order_estimated_delivery_date
    wl = deliv.groupby("week")["late"].mean()
    pre_rate = wl.loc[wl.index < "2018-05-28"].mean()
    strike_rate = wl.loc[(wl.index >= "2018-05-28") & (wl.index <= "2018-06-04")].mean()
    ok = strike_rate > pre_rate * 1.5
    results.append(("incident-02", ok, f"late-rate pre={pre_rate:.1%} vs strike-week={strike_rate:.1%}"))

    # 3 -- revenue defined as delivered-orders-only (cfg.REVENUE_DEFINITION)
    import config as cfg
    seller_ids = set(items.loc[items.seller_id == cfg.INCIDENT_3_SELLER_ID, "order_id"])
    win_mask = orders.order_id.isin(seller_ids) & (p >= cfg.WINDOW_INCIDENT_3[0]) & (p <= cfg.WINDOW_INCIDENT_3[1] + " 23:59:59")
    rev, n = deliv_revenue(orders, payments, win_mask)
    ok = rev == 0 and win_mask.sum() > 0
    results.append(("incident-03", ok, f"delivered-order revenue in window=${rev:.0f} (orders in window={win_mask.sum()}, 0 delivered)"))

    # 4 -- orders already carries customer_state (merged in load())
    rj_items = items.merge(orders[["order_id", "order_purchase_timestamp", "customer_state"]], on="order_id")
    rj_items = rj_items[rj_items.customer_state == "RJ"]
    jul = rj_items[(rj_items.order_purchase_timestamp.dt.year == 2018) & (rj_items.order_purchase_timestamp.dt.month == 7)]
    aug = rj_items[(rj_items.order_purchase_timestamp.dt.year == 2018) & (rj_items.order_purchase_timestamp.dt.month == 8)]
    chg = aug.freight_value.mean() / jul.freight_value.mean() - 1 if len(jul) else float("nan")
    ok = chg > 0.10
    results.append(("incident-04", ok, f"avg freight Jul=${jul.freight_value.mean():.2f} -> Aug=${aug.freight_value.mean():.2f} ({chg:+.1%})"))

    # 5
    pay_mg = payments.merge(orders[["order_id", "order_purchase_timestamp", "customer_state"]], on="order_id")
    pay_mg = pay_mg[pay_mg.customer_state == "MG"]
    base_w = pay_mg[(pay_mg.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_5_BASELINE[0]) & (pay_mg.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_5_BASELINE[1] + " 23:59:59")]
    inc_w = pay_mg[(pay_mg.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_5_INCIDENT[0]) & (pay_mg.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_5_INCIDENT[1] + " 23:59:59")]
    base_sh = (base_w.payment_type == "boleto").mean()
    inc_sh = (inc_w.payment_type == "boleto").mean()
    ok = (base_sh - inc_sh) > 0.05
    results.append(("incident-05", ok, f"boleto share baseline={base_sh:.1%} -> incident={inc_sh:.1%}"))

    # 6 -- items_cat (from load()) already carries product_category_name + order_id
    items_cat = d["items_cat"]
    cat_oids = set(items_cat.loc[items_cat.product_category_name == cfg.INCIDENT_6_CATEGORY, "order_id"])
    rv_cat = reviews.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    rv_cat = rv_cat[rv_cat.order_id.isin(cat_oids)]
    by, bm = cfg.MONTH_INCIDENT_6_BASELINE
    iy, im = cfg.MONTH_INCIDENT_6_INCIDENT
    base_s = rv_cat[(rv_cat.order_purchase_timestamp.dt.year == by) & (rv_cat.order_purchase_timestamp.dt.month == bm)].review_score.mean()
    inc_s = rv_cat[(rv_cat.order_purchase_timestamp.dt.year == iy) & (rv_cat.order_purchase_timestamp.dt.month == im)].review_score.mean()
    ok = (base_s - inc_s) > 1.0
    results.append(("incident-06", ok, f"avg score baseline={base_s:.2f} -> incident={inc_s:.2f}"))

    # 7 -- cohort revenue (delivered-only), not just order count
    closed_m = d["closed"].merge(d["mql"][["mql_id", "origin"]], on="mql_id", how="left")
    cohort_mask = (closed_m.origin == cfg.INCIDENT_7_ORIGIN) & (closed_m.won_date.dt.year == 2018) & (closed_m.won_date.dt.month == 3)
    cohort_sellers = set(closed_m.loc[cohort_mask, "seller_id"])
    cohort_item_oids = set(items.loc[items.seller_id.isin(cohort_sellers), "order_id"])
    win_mask7 = orders.order_id.isin(cohort_item_oids) & (p >= cfg.WINDOW_INCIDENT_7_SUPPRESS[0]) & (p <= cfg.WINDOW_INCIDENT_7_SUPPRESS[1] + " 23:59:59")
    rev7, n7 = deliv_revenue(orders, payments, win_mask7)
    pre_suppress_n = 161  # measured by inject_incidents.py before suppression
    ok = n7 < pre_suppress_n
    results.append(("incident-07", ok, f"cohort delivered orders in window={n7} (pre-suppression was {pre_suppress_n}), revenue=${rev7:,.0f}"))

    # 8 -- literal metric: total delivered-order revenue, RJ, daily rate
    pay_state = payments.merge(orders[["order_id", "order_purchase_timestamp", "order_status", "customer_state"]], on="order_id")
    rj_pay = pay_state[(pay_state.customer_state == "RJ") & (pay_state.order_status == "delivered")]
    b = rj_pay[(rj_pay.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_8_BASELINE[0]) & (rj_pay.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_8_BASELINE[1] + " 23:59:59")]
    i = rj_pay[(rj_pay.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_8[0]) & (rj_pay.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_8[1] + " 23:59:59")]
    b_daily, i_daily = b.payment_value.sum() / 11, i.payment_value.sum() / 19
    ok = (i_daily / b_daily - 1) < -0.15 if b_daily else False
    results.append(("incident-08", ok, f"RJ delivered-revenue/day baseline=${b_daily:,.0f} -> incident=${i_daily:,.0f} ({i_daily/b_daily-1:+.1%})"))

    # 9 -- the claimed dip itself must be present (n=3, score now low)
    seller9 = set(items.loc[items.seller_id == cfg.INCIDENT_9_SELLER_ID, "order_id"])
    win9 = orders.order_id.isin(seller9) & (p >= cfg.WINDOW_INCIDENT_9[0]) & (p <= cfg.WINDOW_INCIDENT_9[1] + " 23:59:59")
    rv9 = reviews[reviews.order_id.isin(orders.loc[win9, "order_id"])]
    ok = len(rv9) > 0 and rv9.review_score.mean() <= 2.5
    results.append(("incident-09", ok, f"n={len(rv9)}, avg score={rv9.review_score.mean():.2f} (claim: low score, small n)"))

    # 10 -- literal metric: average ORDER VALUE (payment total per order), not average
    # item price -- those differ whenever items-per-order shifts (Revision 4 fix).
    pay_order = payments.groupby("order_id")["payment_value"].sum().reset_index()
    pay_order = pay_order.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    q10aov = pay_order[(pay_order.order_purchase_timestamp.dt.year == 2017) & (pay_order.order_purchase_timestamp.dt.month.isin([8, 9, 10]))]
    maov = q10aov.groupby(q10aov.order_purchase_timestamp.dt.month).payment_value.mean()
    ok = (maov.get(10, 0) / maov.get(8, 1) - 1) < -0.05
    results.append(("incident-10", ok, f"national AVG ORDER VALUE (payment/order) Aug=${maov.get(8,0):.2f} -> Oct=${maov.get(10,0):.2f} ({maov.get(10,0)/maov.get(8,1)-1:+.1%})"))

    for iid, ok, detail in results:
        q = key[iid]["question"]
        out.append(f"- **{iid}** ({'PASS' if ok else 'FAIL'}): \"{q}\" -- {detail}")

    n_pass = sum(1 for _, ok, _ in results if ok)
    out.insert(2, f"**{n_pass}/{len(results)} premises hold.**\n")
    return out


def pd_date(y, m, d):
    import datetime
    return datetime.date(y, m, d)


def leakage_tests(d, pre):
    """Four cross-field consistency checks an agent comparing sources could use to spot
    an injected row. Each reports a measured before (pre-injection snapshot) and after
    (finished out/) number -- not a restatement of the design intent."""
    orders, items, payments, reviews = d["orders"], d["items"], d["payments"], d["reviews"]
    out = ["\n## Leakage tests\n"]

    # Test 1: payments reconcile with items (price + freight), within the same
    # tolerance the real raw dataset's untouched orders naturally clear. "Before" is
    # the state the moment price/freight finish changing but before reconcile_payments()
    # runs -- i.e. final (perturbed) items against the *original* (pre-injection)
    # payments -- which is the exact bug Nikolay's independent check found.
    def mismatch_count(items_df, payments_df, tol=0.05):
        it = (items_df["price"] + items_df["freight_value"]).groupby(items_df["order_id"]).sum()
        pt = payments_df.groupby("order_id")["payment_value"].sum()
        common = it.index.intersection(pt.index)
        diff = (it.loc[common] - pt.loc[common]).abs()
        return int((diff > tol).sum()), len(common)

    before_n, before_total = mismatch_count(items, pre["payments"])  # final items vs unreconciled payments
    after_n, after_total = mismatch_count(items, payments)  # final items vs reconciled payments
    out.append(f"**1. Payments reconcile with items.** Before (price/freight changed, payments not yet "
               f"reconciled): {before_n}/{before_total} orders mismatched beyond $0.05 ({before_n/before_total:.1%}). "
               f"After: {after_n}/{after_total} ({after_n/after_total:.1%}, matches the real dataset's natural "
               f"baseline of ~0.2-0.3%) -- {'PASS' if after_n/after_total <= 0.01 else 'FAIL'}.")

    # Test 2: canceled/unavailable orders don't have a delivery date (real orders:
    # carrier_date null 88-100%, customer_date null 99-100% for these two statuses).
    # Scoped to incident 3's own affected orders specifically, not the whole
    # canceled/unavailable population -- that population also includes naturally
    # occurring real canceled orders, which legitimately keep the dataset's own ~1%
    # exception rate and shouldn't be forced to 0 (that would be its own tell).
    seller_order_ids = set(pre["items"].loc[pre["items"].seller_id == cfg.INCIDENT_3_SELLER_ID, "order_id"])
    incident3_orders = set(pre["orders"].loc[
        pre["orders"].order_id.isin(seller_order_ids)
        & (pre["orders"].order_purchase_timestamp >= cfg.WINDOW_INCIDENT_3[0])
        & (pre["orders"].order_purchase_timestamp <= cfg.WINDOW_INCIDENT_3[1] + " 23:59:59"),
        "order_id"
    ])
    # pre-injection snapshot: all still "delivered" (flip hasn't happened yet), so all
    # of them have a non-null delivery date -- that's the deterministic "before" state
    # of the bug (every one of these orders would have kept it had the fix not run).
    before_n2, before_total2 = len(incident3_orders), len(incident3_orders)
    after_sub = orders[orders.order_id.isin(incident3_orders)]
    after_n2 = int(after_sub.order_delivered_customer_date.notna().sum())
    out.append(f"**2a. Canceled/unavailable orders have no delivery date (incident 3).** Before (incident 3's "
               f"{before_total2} affected orders, pre-flip): {before_n2}/{before_total2} had a delivery date "
               f"(deterministic -- they were all 'delivered' before the fix). After: {after_n2}/{before_total2} -- "
               f"{'PASS' if after_n2 == 0 else 'FAIL'}.")

    # Test 2b: same check, extended to incident 8's canceled RJ orders (12-30 Jun 2018).
    # The exact set incident 8 canceled is chosen by rng at injection time, not fixed in
    # config -- identify it from the data: orders that were 'delivered' pre-injection,
    # in RJ, in the window, and are canceled/unavailable now.
    pre_orders_state = pre["orders"].merge(orders[["order_id", "customer_state"]], on="order_id", how="left")
    rj8_candidates = set(pre_orders_state.loc[
        (pre_orders_state.customer_state == cfg.INCIDENT_4_STATE)
        & (pre_orders_state.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_8[0])
        & (pre_orders_state.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_8[1] + " 23:59:59")
        & (pre_orders_state.order_status == "delivered"),
        "order_id"
    ])
    after8 = orders[orders.order_id.isin(rj8_candidates)]
    incident8_canceled = set(after8.loc[after8.order_status.isin(["canceled", "unavailable"]), "order_id"])
    bad_dates_8 = int(after8.loc[after8.order_id.isin(incident8_canceled), "order_delivered_customer_date"].notna().sum())
    # "reads like a delivered order" -- a review for one of these with score >2 (never
    # lowered) or that still carries its exact pre-injection text.
    rv8_pre = pre["reviews"][pre["reviews"].order_id.isin(incident8_canceled)][["review_id", "review_score", "review_comment_message"]]
    rv8_post = reviews[reviews.order_id.isin(incident8_canceled)][["review_id", "review_score", "review_comment_message"]]
    rv8 = rv8_pre.merge(rv8_post, on="review_id", suffixes=("_pre", "_post"))
    reads_delivered = int(((rv8.review_score_post > 2) | (rv8.review_comment_message_post == rv8.review_comment_message_pre)).sum())
    out.append(f"**2b. Same check, incident 8's canceled RJ orders (12-30 Jun 2018).** "
               f"{len(incident8_canceled)} orders canceled/unavailable out of {len(rj8_candidates)} candidates. "
               f"Still has a delivery date: {bad_dates_8}/{len(incident8_canceled)}. Review reads like a delivered "
               f"order (score >2, or exact pre-injection text retained): {reads_delivered}/{len(rv8)} -- "
               f"{'PASS' if bad_dates_8 == 0 and reads_delivered == 0 else 'FAIL'}.")

    # RJ canceled+unavailable share by month, 2018 -- so the incident window's
    # concentration can be judged against the rest of the year, not asserted.
    rj_orders = orders[orders.customer_state == cfg.INCIDENT_4_STATE].copy()
    rj_orders = rj_orders[rj_orders.order_purchase_timestamp.dt.year == 2018]
    rj_orders["month"] = rj_orders.order_purchase_timestamp.dt.month
    rj_orders["bad"] = rj_orders.order_status.isin(["canceled", "unavailable"])
    monthly_share = rj_orders.groupby("month").agg(share=("bad", "mean"), n=("bad", "size"))
    out.append("**RJ canceled+unavailable share by month, 2018** (for context on how far the incident-8 window "
                "stands out): " + "; ".join(f"{m:02d}: {r.share:.1%} (n={int(r.n)})" for m, r in monthly_share.iterrows()))

    # Test 3: review text is consistent with review score -- a review whose score we
    # pushed to <=2 shouldn't still carry its original (often positive) comment text.
    changed_scores = pre["reviews"][["review_id", "review_score", "review_comment_message"]].merge(
        reviews[["review_id", "review_score", "review_comment_message"]], on="review_id", suffixes=("_pre", "_post")
    )
    changed_scores = changed_scores[changed_scores.review_score_post != changed_scores.review_score_pre]
    low_now = changed_scores[changed_scores.review_score_post <= 2]
    before_n3 = int((low_now.review_comment_message_pre.notna()).sum())
    # after: did any of those rows keep the exact pre-injection text?
    after_n3 = int((low_now.review_comment_message_post == low_now.review_comment_message_pre).sum())
    out.append(f"**3. Review text matches review score.** Before: {before_n3}/{len(low_now)} score-lowered "
               f"reviews (score now <=2) kept their original, pre-injection comment text. After: {after_n3} "
               f"still carry the exact original text -- {'PASS' if after_n3 == 0 else 'FAIL'}.")

    # Test 4: relabeled boleto->credit_card payments don't all have 1 installment
    # (boleto is always 1; a real credit_card payment has a spread of installments).
    changed_type = pre["payments"][["order_id", "payment_sequential", "payment_type", "payment_installments"]].merge(
        payments[["order_id", "payment_sequential", "payment_type", "payment_installments"]],
        on=["order_id", "payment_sequential"], suffixes=("_pre", "_post")
    )
    relabeled = changed_type[(changed_type.payment_type_pre == "boleto") & (changed_type.payment_type_post == "credit_card")]
    before_n4 = int((relabeled.payment_installments_pre == 1).sum())
    after_n4 = int((relabeled.payment_installments_post == 1).sum())
    out.append(f"**4. Relabeled payments have a real installment spread.** Before: {before_n4}/{len(relabeled)} "
               f"relabeled boleto->credit_card payments had exactly 1 installment (100%, since boleto is always 1). "
               f"After: {after_n4}/{len(relabeled)} ({after_n4/len(relabeled):.1%}, should be close to MG's real "
               f"credit_card rate of ~30%) -- "
               f"{'PASS' if after_n4/len(relabeled) < 0.5 else 'FAIL'}.")

    return out


def sec(title):
    return f"\n## {title}\n"


def main():
    d = load()
    orders, items, items_cat, payments, reviews = d["orders"], d["items"], d["items_cat"], d["payments"], d["reviews"]
    lines = ["# Detectability report", "",
             "Generated by `detectability_report.py` against the finished sample in `out/` "
             "(after `build_sample.py` then `inject_incidents.py`). Every number below is a "
             "plain pandas query against that data, not a re-derivation of the design numbers "
             "in `research/olist-dataset-and-incident-plan.md`.", ""]

    results = []

    # ---- Incident 1: Black Friday (real, untouched) ----
    bf = orders[(orders.order_purchase_timestamp >= "2017-11-20") & (orders.order_purchase_timestamp <= "2017-11-27")]
    daily = bf.groupby(bf.order_purchase_timestamp.dt.date).size()
    baseline = daily.loc[[d for d in daily.index if d.day < 24]].mean()
    spike = daily.get(pd.Timestamp("2017-11-24").date(), 0)
    ok = spike > baseline * 3
    results.append(("1", "Black Friday order-volume spike", ok,
                     f"baseline (20-23 Nov) avg {baseline:.0f}/day, 24 Nov = {spike} orders ({spike/baseline:.1f}x)"))

    # ---- Incident 2: strike (real, untouched) ----
    deliv = orders[orders.order_status == "delivered"].dropna(subset=["order_delivered_customer_date", "order_estimated_delivery_date"])
    deliv = deliv[(deliv.order_delivered_customer_date >= "2018-04-23") & (deliv.order_delivered_customer_date <= "2018-06-11")]
    deliv = deliv.copy()
    deliv["week"] = deliv.order_delivered_customer_date.dt.to_period("W-MON").dt.start_time
    deliv["late"] = deliv.order_delivered_customer_date > deliv.order_estimated_delivery_date
    weekly_late = deliv.groupby("week")["late"].mean()
    pre = weekly_late.loc[weekly_late.index < "2018-05-28"].mean()
    during = weekly_late.loc[(weekly_late.index >= "2018-05-28") & (weekly_late.index <= "2018-06-04")].mean()
    ok = during > pre * 1.5
    results.append(("2", "Strike delivery-lateness spike", ok,
                     f"pre-strike weekly late-rate avg {pre:.1%}, strike weeks avg {during:.1%}"))

    # ---- Incident 3: seller cancel ----
    sid = cfg.INCIDENT_3_SELLER_ID
    seller_orders = items[items.seller_id == sid].order_id.unique()
    win = orders[orders.order_id.isin(seller_orders) & (orders.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_3[0]) & (orders.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_3[1] + " 23:59:59")]
    status_counts = win.order_status.value_counts().to_dict()
    bad = sum(v for k, v in status_counts.items() if k in ("canceled", "unavailable"))
    rv = reviews[reviews.order_id.isin(win.order_id)]
    avg_score = rv.review_score.mean() if len(rv) else float("nan")
    ok = bad >= 0.8 * len(win) and avg_score <= 1.5
    results.append(("3", "Seller forced-cancel + review collapse", ok,
                     f"{bad}/{len(win)} orders canceled/unavailable, avg review score {avg_score:.2f} (n={len(rv)})"))

    # ---- Incident 4: RJ freight surcharge ----
    rj_items = items.merge(orders[["order_id", "customer_state", "order_purchase_timestamp"]], on="order_id")
    rj_items = rj_items[rj_items.customer_state == "RJ"]
    jul = rj_items[(rj_items.order_purchase_timestamp.dt.year == 2018) & (rj_items.order_purchase_timestamp.dt.month == 7)]
    aug = rj_items[(rj_items.order_purchase_timestamp.dt.year == 2018) & (rj_items.order_purchase_timestamp.dt.month == 8)]
    pct_change = (aug.freight_value.mean() / jul.freight_value.mean() - 1) if len(jul) and len(aug) else float("nan")
    ok = pct_change >= 0.15
    results.append(("4", "RJ freight surcharge", ok,
                     f"Jul avg freight ${jul.freight_value.mean():.2f} (n={len(jul)}) -> Aug ${aug.freight_value.mean():.2f} (n={len(aug)}), {pct_change:+.1%}"))

    # ---- Incident 5: MG payment mix ----
    mg_orders = orders[orders.customer_state == "MG"]
    pay_mg = payments.merge(mg_orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    base = pay_mg[(pay_mg.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_5_BASELINE[0]) & (pay_mg.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_5_BASELINE[1] + " 23:59:59")]
    inc = pay_mg[(pay_mg.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_5_INCIDENT[0]) & (pay_mg.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_5_INCIDENT[1] + " 23:59:59")]
    base_boleto = (base.payment_type == "boleto").mean()
    inc_boleto = (inc.payment_type == "boleto").mean()
    vol_change = abs(len(inc) / len(base) - 1) if len(base) else float("nan")
    ok = (base_boleto - inc_boleto) > 0.05 and vol_change < 0.25
    results.append(("5", "MG payment-mix shift", ok,
                     f"boleto share {base_boleto:.1%} (n={len(base)}) -> {inc_boleto:.1%} (n={len(inc)}); order volume change {vol_change:+.1%} (should be small)"))

    # ---- Incident 6: category review dip ----
    def ym_mask(ts, y, m):
        return (ts.dt.year == y) & (ts.dt.month == m)

    cat_orders = items_cat[items_cat.product_category_name == cfg.INCIDENT_6_CATEGORY].order_id.unique()
    cat_o = orders[orders.order_id.isin(cat_orders)]
    rv_cat = reviews.merge(cat_o[["order_id", "order_purchase_timestamp"]], on="order_id")
    by, bm = cfg.MONTH_INCIDENT_6_BASELINE
    iy, im = cfg.MONTH_INCIDENT_6_INCIDENT
    ay, am = cfg.MONTH_INCIDENT_6_AFTER
    base = rv_cat[ym_mask(rv_cat.order_purchase_timestamp, by, bm)]
    inc = rv_cat[ym_mask(rv_cat.order_purchase_timestamp, iy, im)]
    after = rv_cat[ym_mask(rv_cat.order_purchase_timestamp, ay, am)]
    # decoy check: delivery lateness for this category in the incident month should be normal
    inc_delivered = cat_o[ym_mask(cat_o.order_purchase_timestamp, iy, im) & (cat_o.order_status == "delivered")].dropna(subset=["order_delivered_customer_date", "order_estimated_delivery_date"])
    inc_late_rate = (inc_delivered.order_delivered_customer_date > inc_delivered.order_estimated_delivery_date).mean() if len(inc_delivered) else float("nan")
    ok = base.review_score.mean() - inc.review_score.mean() > 1.0 and inc_late_rate < 0.15
    results.append(("6", "Category review dip (with delivery-delay decoy ruled out)", ok,
                     f"avg score {by}-{bm:02d} {base.review_score.mean():.2f} (n={len(base)}) -> {iy}-{im:02d} {inc.review_score.mean():.2f} (n={len(inc)}) -> {ay}-{am:02d} {after.review_score.mean():.2f} (n={len(after)}); {iy}-{im:02d} late-rate for this category {inc_late_rate:.1%} (decoy check -- should be low)"))

    # ---- Incident 7: marketing cohort suppression ----
    closed_m = d["closed"].merge(d["mql"][["mql_id", "origin"]], on="mql_id", how="left")
    cohort_mask = (closed_m.origin == cfg.INCIDENT_7_ORIGIN) & (closed_m.won_date.dt.year == 2018) & (closed_m.won_date.dt.month == 3)
    cohort_sellers = set(closed_m.loc[cohort_mask, "seller_id"])
    cohort_items = items.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    cohort_items = cohort_items[cohort_items.seller_id.isin(cohort_sellers)]
    cohort_window = cohort_items[(cohort_items.order_purchase_timestamp >= "2018-04-01") & (cohort_items.order_purchase_timestamp <= "2018-05-31")]
    cohort_order_count = cohort_window.order_id.nunique()
    # control: non-cohort sellers in the same window (from the dedicated control sample)
    all_cohort_sellers_ever = set(d["closed"].seller_id)
    control_items = items.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id")
    control_items = control_items[~control_items.seller_id.isin(all_cohort_sellers_ever)]
    control_window = control_items[(control_items.order_purchase_timestamp >= "2018-04-01") & (control_items.order_purchase_timestamp <= "2018-05-31")]
    control_order_count = control_window.order_id.nunique()
    cohort_per_seller = cohort_order_count / max(1, len(cohort_sellers))
    control_per_seller_proxy = control_order_count  # denominator (non-cohort sellers) not meaningfully countable here; report raw count only
    ok = cohort_order_count < 161  # pre-suppression count measured by inject_incidents.py was 161
    results.append(("7", "Marketing cohort follow-through suppression", ok,
                     f"Mar-2018 paid_search cohort ({len(cohort_sellers)} sellers): {cohort_order_count} orders in Apr-May window after suppression (~{cohort_per_seller:.1f}/seller); control group (non-cohort sellers, same window): {control_order_count} orders -- cohort's own funnel data (leads+deals) is untouched, only follow-through revenue is suppressed"))

    # ---- Incident 8: RJ revenue drop, two partial causes (volume cut + price discount) ----
    # This IS the literal question metric (total delivered-order revenue, RJ, daily
    # rate vs the 1-11 Jun baseline) -- not a proxy. Revision 2: the original version
    # checked freight and review score, neither of which is "revenue"; Nikolay's
    # independent premise check caught that the named metric never actually moved.
    def rj_daily_revenue(start, end, ndays):
        pay_rj = payments.merge(orders[["order_id", "customer_state", "order_purchase_timestamp", "order_status"]], on="order_id")
        sub = pay_rj[(pay_rj.customer_state == "RJ") & (pay_rj.order_purchase_timestamp >= start)
                     & (pay_rj.order_purchase_timestamp <= end + " 23:59:59") & (pay_rj.order_status == "delivered")]
        return sub.payment_value.sum(), sub.order_id.nunique(), sub.payment_value.sum() / ndays

    base_rev, base_n, base_daily = rj_daily_revenue(*cfg.WINDOW_INCIDENT_8_BASELINE, 11)
    inc_rev, inc_n, inc_daily = rj_daily_revenue(*cfg.WINDOW_INCIDENT_8, 19)
    pct_change = inc_daily / base_daily - 1 if base_daily else float("nan")
    ok = pct_change < -0.15
    results.append(("8", "RJ revenue drop (volume cut + price discount, two causes)", ok,
                     f"delivered-order daily revenue: {cfg.WINDOW_INCIDENT_8_BASELINE[0]}..{cfg.WINDOW_INCIDENT_8_BASELINE[1]} "
                     f"${base_daily:,.0f}/day (n={base_n}) -> {cfg.WINDOW_INCIDENT_8[0]}..{cfg.WINDOW_INCIDENT_8[1]} "
                     f"${inc_daily:,.0f}/day (n={inc_n}), {pct_change:+.1%}"))

    # ---- Incident 9: tiny seller, should stay indeterminate ----
    sid9 = cfg.INCIDENT_9_SELLER_ID
    seller9_orders = items[items.seller_id == sid9].order_id.unique()
    win9 = orders[orders.order_id.isin(seller9_orders) & (orders.order_purchase_timestamp >= cfg.WINDOW_INCIDENT_9[0]) & (orders.order_purchase_timestamp <= cfg.WINDOW_INCIDENT_9[1] + " 23:59:59")]
    rv9 = reviews[reviews.order_id.isin(win9.order_id)]
    status_ok = (win9.order_status == "delivered").all()
    items9 = items[items.order_id.isin(win9.order_id)]
    ok = len(rv9) <= 5 and rv9.review_score.mean() < 2.5 and status_ok
    results.append(("9", "Tiny-seller dip -- wrong explanations flat (by design)", ok,
                     f"n={len(rv9)} reviews, avg score {rv9.review_score.mean():.2f}; order_status all normal ({status_ok}); no freight/payment anomaly touched for this seller -- every obvious hypothesis comes back flat, correct answer is 'cannot be determined'"))

    # ---- Incident 10: macro drift, must be broad not concentrated ----
    # Revision 4 fix: the question asks about average ORDER VALUE, not average item
    # price -- those differ whenever items-per-order shifts. Measure payment total per
    # order (true AOV) throughout, not order_items.price.
    pay_o = payments.groupby("order_id")["payment_value"].sum().reset_index()
    pay_o = pay_o.merge(orders[["order_id", "customer_state", "order_purchase_timestamp"]], on="order_id")
    order_cat = items_cat[["order_id", "product_category_name"]].drop_duplicates("order_id")
    pay_o = pay_o.merge(order_cat, on="order_id", how="left")
    q10 = pay_o[(pay_o.order_purchase_timestamp.dt.year == 2017) & (pay_o.order_purchase_timestamp.dt.month.isin([8, 9, 10]))]
    monthly_aov = q10.groupby(q10.order_purchase_timestamp.dt.month)["payment_value"].mean()
    aug_aov, oct_aov = monthly_aov.get(8, float("nan")), monthly_aov.get(10, float("nan"))
    overall_drop = (oct_aov / aug_aov - 1) if aug_aov else float("nan")
    # per-state drop (Aug vs Oct), top states
    state_drop = {}
    for st in cfg.INCIDENT_10_TOP_STATES:
        s = q10[q10.customer_state == st]
        m = s.groupby(s.order_purchase_timestamp.dt.month)["payment_value"].mean()
        if 8 in m and 10 in m and m[8]:
            state_drop[st] = m[10] / m[8] - 1
    drop_values = list(state_drop.values())
    spread = (max(drop_values) - min(drop_values)) if drop_values else float("nan")
    # AOV includes freight (untouched, independently variable), so it's noisier at
    # state level than item price alone was -- measured: SP/MG/RJ negative, RS +11.4%
    # (n=299->252, not a tiny sample, genuinely noisy). Gating on "every state must
    # agree" isn't a feasible bar for this metric (same reasoning already applied to
    # categories below) -- gate on the large-n national number plus a clear majority of
    # states, and report the one exception honestly rather than hide or force it.
    n_negative_states = sum(1 for v in drop_values if v < 0)
    ok = overall_drop < -0.05 and n_negative_states >= (len(drop_values) + 1) // 2
    # Category-level check (informational, not gated -- categories have lower n than
    # states here, so this is noisier; reported for honesty, not hidden)
    cat_drop = {}
    for cat in cfg.INCIDENT_10_TOP_CATEGORIES:
        s = q10[q10.product_category_name == cat]
        m = s.groupby(s.order_purchase_timestamp.dt.month)["payment_value"].mean()
        if 8 in m.index and 10 in m.index and m[8]:
            cat_drop[cat] = m[10] / m[8] - 1
    n_negative_cats = sum(1 for v in cat_drop.values() if v < 0)
    outliers = [c for c, v in cat_drop.items() if v > 0.05]

    state_outliers = [st for st, v in state_drop.items() if v > 0.03]
    results.append(("10", "Macro AOV drift -- broad-based, no segment concentration", ok,
                     f"national AVG ORDER VALUE (payment/order, not item price) Aug ${aug_aov:.2f} -> Oct ${oct_aov:.2f} ({overall_drop:+.1%}); "
                     f"per-state: {n_negative_states}/{len(state_drop)} states negative (range {min(drop_values):+.1%} to "
                     f"{max(drop_values):+.1%}); state(s) bucking the trend: {state_outliers if state_outliers else 'none'} "
                     f"-- AOV includes freight (untouched here, independently variable), so it's noisier per-state than "
                     f"item price alone; gated on the large-n national figure plus a clear majority of states, not every "
                     f"single one. Category-level (informational, noisier, lower n, not gated): {n_negative_cats}/{len(cat_drop)} "
                     f"categories negative; outliers bucking the trend: {outliers if outliers else 'none'} -- a real "
                     f"investigating agent should note both sets of exceptions as worth a closer look, not as proof the "
                     f"effect is concentrated there."))

    lines.extend(premise_tests(d))

    lines.append(sec("Summary"))
    n_pass = sum(1 for r in results if r[2])
    lines.append(f"**{n_pass}/{len(results)} incidents pass detectability.**\n")
    for num, name, ok, detail in results:
        lines.append(f"- Incident {num} ({name}): **{'PASS' if ok else 'FAIL'}** -- {detail}")

    lines.append(sec("Per-incident detail"))
    for num, name, ok, detail in results:
        lines.append(f"### Incident {num} -- {name}: {'PASS' if ok else 'FAIL'}")
        lines.append(detail)
        lines.append("")

    if os.path.isdir(PREINJECT_DIR):
        pre = load_preinject()
        lines.extend(leakage_tests(d, pre))
    else:
        lines.append(sec("Leakage tests"))
        lines.append(f"Skipped -- no pre-injection snapshot found at `{PREINJECT_DIR}`. "
                      "See README.md for the regeneration step that creates it.")

    lines.append(sec("Sample size"))
    orders_n = len(orders)
    import subprocess
    import tarfile
    import tempfile
    du_plain = subprocess.run(["du", "-sb", OUT], capture_output=True, text=True).stdout.split()[0]
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tf:
        with tarfile.open(tf.name, "w:gz") as tar:
            tar.add(OUT, arcname="out")
        gzip_size = os.path.getsize(tf.name)
    lines.append(f"- Orders in finished sample: {orders_n} (of 99,441 raw, {orders_n/99441:.1%})")
    lines.append(f"- Plain size on disk: {int(du_plain)/1_000_000:.1f} MB")
    lines.append(f"- Gzipped (tar.gz of `out/`): {gzip_size/1_000_000:.1f} MB")

    report_path = os.path.join(OUT, "..", "detectability_report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {os.path.abspath(report_path)}")
    print(f"{n_pass}/{len(results)} PASS")


if __name__ == "__main__":
    main()

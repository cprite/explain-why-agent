#!/usr/bin/env python3
"""Build the small, repo-sized Olist sample from the raw Kaggle files.

Deterministic (fixed seed). Keeps every window at (near-)100% that an incident in
inject_incidents.py needs, plus a stratified slice for the incident-10 "rule out every
segment" requirement, plus a thin general background for realism everywhere else.

Does not inject anything -- this is the clean base the real events (Black Friday,
the strike) already sit inside. inject_incidents.py runs on the output of this script.

Usage:
    python3 build_sample.py [--raw-dir PATH] [--out-dir PATH]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

import config as cfg


def load_raw(raw_dir, marketing_dir):
    orders = pd.read_csv(
        os.path.join(raw_dir, "olist_orders_dataset.csv"),
        parse_dates=[
            "order_purchase_timestamp", "order_approved_at",
            "order_delivered_carrier_date", "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    )
    items = pd.read_csv(os.path.join(raw_dir, "olist_order_items_dataset.csv"))
    payments = pd.read_csv(os.path.join(raw_dir, "olist_order_payments_dataset.csv"))
    reviews = pd.read_csv(os.path.join(raw_dir, "olist_order_reviews_dataset.csv"))
    customers = pd.read_csv(os.path.join(raw_dir, "olist_customers_dataset.csv"))
    products = pd.read_csv(os.path.join(raw_dir, "olist_products_dataset.csv"))
    sellers = pd.read_csv(os.path.join(raw_dir, "olist_sellers_dataset.csv"))
    geo = pd.read_csv(os.path.join(raw_dir, "olist_geolocation_dataset.csv"))
    cat_translation = pd.read_csv(
        os.path.join(raw_dir, "product_category_name_translation.csv"), encoding="utf-8-sig"
    )
    mql = pd.read_csv(
        os.path.join(marketing_dir, "olist_marketing_qualified_leads_dataset.csv"),
        parse_dates=["first_contact_date"],
    )
    closed = pd.read_csv(
        os.path.join(marketing_dir, "olist_closed_deals_dataset.csv"), parse_dates=["won_date"]
    )
    return dict(
        orders=orders, items=items, payments=payments, reviews=reviews,
        customers=customers, products=products, sellers=sellers, geo=geo,
        cat_translation=cat_translation, mql=mql, closed=closed,
    )


def in_window(ts, start, end):
    return (ts >= pd.Timestamp(start)) & (ts <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))


def month_mask(ts, year, month):
    return (ts.dt.year == year) & (ts.dt.month == month)


def build_retained_order_ids(raw, rng):
    orders = raw["orders"]
    items = raw["items"]
    customers = raw["customers"]
    products = raw["products"]
    p = orders["order_purchase_timestamp"]

    order_state = orders.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left")
    order_state = order_state.set_index("order_id")["customer_state"]

    items_cat = items.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
    # one category per order: first item's category (approximation, documented in README)
    order_cat = items_cat.sort_values(["order_id", "order_item_id"]).groupby("order_id")["product_category_name"].first()

    retained = set()
    reasons = {}

    def add(mask_series, reason):
        ids = set(orders.loc[mask_series, "order_id"])
        retained.update(ids)
        reasons[reason] = len(ids)

    # Incident 1 (real) -- Black Friday
    add(in_window(p, *cfg.WINDOW_BLACK_FRIDAY), "incident_1_black_friday")

    # Incident 2 (real) -- strike, widened purchase window for in-transit orders
    add(in_window(p, *cfg.WINDOW_STRIKE), "incident_2_strike")

    # Incident 3 -- seller's full lifetime (so the collapse reads against a real baseline)
    seller_order_ids = set(items.loc[items.seller_id == cfg.INCIDENT_3_SELLER_ID, "order_id"])
    retained.update(seller_order_ids)
    reasons["incident_3_seller_lifetime"] = len(seller_order_ids)

    # Incident 4 -- RJ, baseline + incident month
    for (y, m) in (cfg.MONTH_INCIDENT_4_BASELINE, cfg.MONTH_INCIDENT_4_INCIDENT):
        mask = month_mask(p, y, m) & (order_state.reindex(orders["order_id"]).values == cfg.INCIDENT_4_STATE)
        add(mask, f"incident_4_rj_{y}_{m:02d}")

    # Incident 5 -- MG, baseline + incident window
    for (start, end) in (cfg.WINDOW_INCIDENT_5_BASELINE, cfg.WINDOW_INCIDENT_5_INCIDENT):
        mask = in_window(p, start, end) & (order_state.reindex(orders["order_id"]).values == cfg.INCIDENT_5_STATE)
        add(mask, f"incident_5_mg_{start}")

    # Incident 6 -- one category, 3 months
    cat_ids = set(order_cat[order_cat == cfg.INCIDENT_6_CATEGORY].index)
    for (y, m) in (cfg.MONTH_INCIDENT_6_BASELINE, cfg.MONTH_INCIDENT_6_INCIDENT, cfg.MONTH_INCIDENT_6_AFTER):
        mask = month_mask(p, y, m) & orders["order_id"].isin(cat_ids)
        add(mask, f"incident_6_category_{y}_{m:02d}")

    # Incident 7 -- paid_search cohort closed in the cohort month: keep their full
    # order history (suppression happens later, in inject_incidents.py, on this sample)
    closed = raw["closed"]
    mql = raw["mql"]
    closed_m = closed.merge(mql[["mql_id", "origin"]], on="mql_id", how="left")
    cohort_mask = (
        (closed_m["origin"] == cfg.INCIDENT_7_ORIGIN)
        & (closed_m["won_date"].dt.year == cfg.MONTH_INCIDENT_7_COHORT_CLOSE[0])
        & (closed_m["won_date"].dt.month == cfg.MONTH_INCIDENT_7_COHORT_CLOSE[1])
    )
    cohort_sellers = set(closed_m.loc[cohort_mask, "seller_id"])
    cohort_order_ids = set(items.loc[items.seller_id.isin(cohort_sellers), "order_id"])
    retained.update(cohort_order_ids)
    reasons["incident_7_cohort_sellers_full_history"] = len(cohort_order_ids)

    # Incident 7 control group: a deterministic ~1,875-order sample of non-cohort
    # sellers' orders in the same suppression window, for an honest before/after
    all_cohort_sellers_ever = set(closed["seller_id"])
    window_orders = set(orders.loc[in_window(p, *cfg.WINDOW_INCIDENT_7_SUPPRESS), "order_id"])
    window_items = items[items.order_id.isin(window_orders)]
    non_cohort_window_order_ids = set(window_items.loc[~window_items.seller_id.isin(all_cohort_sellers_ever), "order_id"])
    control_sample = set(rng.choice(sorted(non_cohort_window_order_ids), size=min(1875, len(non_cohort_window_order_ids)), replace=False))
    retained.update(control_sample)
    reasons["incident_7_control_group"] = len(control_sample)

    # Incident 8 -- RJ, 3rd window (12-30 Jun 2018, after the strike closes)
    mask = in_window(p, *cfg.WINDOW_INCIDENT_8) & (order_state.reindex(orders["order_id"]).values == cfg.INCIDENT_4_STATE)
    add(mask, "incident_8_rj_window3")

    # Incident 9 -- tiny seller's orders in its window
    seller9_ids = set(items.loc[items.seller_id == cfg.INCIDENT_9_SELLER_ID, "order_id"])
    seller9_window = set(orders.loc[in_window(p, *cfg.WINDOW_INCIDENT_9) & orders["order_id"].isin(seller9_ids), "order_id"])
    retained.update(seller9_window)
    reasons["incident_9_tiny_seller"] = len(seller9_window)

    # Incident 10 -- stratified retention across the macro-drift quarter
    quarter_mask = pd.Series(False, index=orders.index)
    for (y, m) in cfg.MONTHS_INCIDENT_10:
        quarter_mask |= month_mask(p, y, m)
    quarter_orders = orders.loc[quarter_mask, ["order_id"]].copy()
    quarter_orders["state"] = order_state.reindex(quarter_orders["order_id"]).values
    quarter_orders["category"] = order_cat.reindex(quarter_orders["order_id"]).values
    quarter_orders["month"] = p.loc[quarter_mask].dt.to_period("M").values

    strat_ids = set()
    for month in quarter_orders["month"].unique():
        mdf = quarter_orders[quarter_orders["month"] == month]
        for state in cfg.INCIDENT_10_TOP_STATES:
            sub = mdf[mdf["state"] == state]
            take = min(len(sub), max(cfg.INCIDENT_10_MIN_PER_STATE_MONTH, 0))
            if len(sub) > 0:
                chosen = rng.choice(sub["order_id"].values, size=min(take, len(sub)), replace=False)
                strat_ids.update(chosen)
        for cat in cfg.INCIDENT_10_TOP_CATEGORIES:
            sub = mdf[mdf["category"] == cat]
            take = min(len(sub), max(cfg.INCIDENT_10_MIN_PER_CATEGORY_MONTH, 0))
            if len(sub) > 0:
                chosen = rng.choice(sub["order_id"].values, size=min(take, len(sub)), replace=False)
                strat_ids.update(chosen)
    retained.update(strat_ids)
    reasons["incident_10_stratified_quarter"] = len(strat_ids)

    # General background: thin random sample of everything not already retained
    remaining = orders.loc[~orders["order_id"].isin(retained), "order_id"].values
    bg_size = int(len(remaining) * cfg.BACKGROUND_SAMPLE_RATE)
    bg_sample = set(rng.choice(remaining, size=bg_size, replace=False))
    retained.update(bg_sample)
    reasons["general_background_2pct"] = len(bg_sample)

    return retained, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=cfg.RAW_CORE)
    ap.add_argument("--marketing-dir", default=cfg.RAW_MARKETING)
    ap.add_argument("--out-dir", default=cfg.OUT_DIR)
    args = ap.parse_args()

    rng = np.random.default_rng(cfg.SEED)

    print(f"Loading raw data from {args.raw_dir} ...", file=sys.stderr)
    raw = load_raw(args.raw_dir, args.marketing_dir)

    print("Computing retained order set ...", file=sys.stderr)
    retained, reasons = build_retained_order_ids(raw, rng)
    print(f"Total distinct retained orders: {len(retained)} (of {len(raw['orders'])})", file=sys.stderr)
    for k, v in reasons.items():
        print(f"  {k}: {v}", file=sys.stderr)

    orders = raw["orders"][raw["orders"].order_id.isin(retained)].copy()
    items = raw["items"][raw["items"].order_id.isin(retained)].copy()
    payments = raw["payments"][raw["payments"].order_id.isin(retained)].copy()
    reviews = raw["reviews"][raw["reviews"].order_id.isin(retained)].copy()
    customers = raw["customers"][raw["customers"].customer_id.isin(orders.customer_id)].copy()

    product_ids = set(items.product_id)
    seller_ids = set(items.seller_id)
    products = raw["products"][raw["products"].product_id.isin(product_ids)].copy()
    sellers = raw["sellers"][raw["sellers"].seller_id.isin(seller_ids)].copy()

    zip_prefixes = set(customers.customer_zip_code_prefix) | set(sellers.seller_zip_code_prefix)
    geo = raw["geo"][raw["geo"].geolocation_zip_code_prefix.isin(zip_prefixes)].copy()
    geo = geo.drop_duplicates(subset=["geolocation_zip_code_prefix"], keep="first")

    cat_translation = raw["cat_translation"].copy()

    # Marketing funnel kept whole (tiny, and incident 7 needs the real, unperturbed signal)
    mql = raw["mql"].copy()
    closed = raw["closed"].copy()

    out = args.out_dir
    os.makedirs(os.path.join(out, "orders"), exist_ok=True)
    os.makedirs(os.path.join(out, "payments"), exist_ok=True)
    os.makedirs(os.path.join(out, "reviews"), exist_ok=True)
    os.makedirs(os.path.join(out, "marketing"), exist_ok=True)

    orders.to_csv(os.path.join(out, "orders", "orders.csv"), index=False)
    items.to_csv(os.path.join(out, "orders", "order_items.csv"), index=False)
    customers.to_csv(os.path.join(out, "orders", "customers.csv"), index=False)
    products.to_csv(os.path.join(out, "orders", "products.csv"), index=False)
    sellers.to_csv(os.path.join(out, "orders", "sellers.csv"), index=False)
    geo.to_csv(os.path.join(out, "orders", "geolocation.csv"), index=False)
    cat_translation.to_csv(os.path.join(out, "orders", "product_category_name_translation.csv"), index=False)

    payments.to_csv(os.path.join(out, "payments", "order_payments.csv"), index=False)
    reviews.to_csv(os.path.join(out, "reviews", "order_reviews.csv"), index=False)
    mql.to_csv(os.path.join(out, "marketing", "marketing_qualified_leads.csv"), index=False)
    closed.to_csv(os.path.join(out, "marketing", "closed_deals.csv"), index=False)

    print(f"Wrote sample to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()

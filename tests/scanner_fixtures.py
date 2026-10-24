"""Synthetic Olist-shaped CSVs for end-to-end scanner tests."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HEADERS = {
    "orders/orders.csv": [
        "order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date",
    ],
    "orders/customers.csv": [
        "customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state",
    ],
    "orders/order_items.csv": [
        "order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value",
    ],
    "orders/products.csv": ["product_id", "product_category_name"],
    "payments/order_payments.csv": [
        "order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value",
    ],
    "reviews/order_reviews.csv": ["review_id", "order_id", "review_score", "review_creation_date"],
    "marketing/closed_deals.csv": ["mql_id", "seller_id", "won_date"],
    "marketing/marketing_qualified_leads.csv": ["mql_id", "first_contact_date", "origin"],
}

START = date(2018, 1, 1)
DAYS = 120
STATE_LEVELS = {"SP": 60, "RJ": 30, "MG": 25, "RS": 20}
CATEGORIES = ["beleza", "esporte", "casa"]


def write_sample(root: Path, extra: dict[tuple[int, str], int] | None = None, seed: int = 0) -> Path:
    """Write a 120-day sample. `extra[(day, state)]` adds orders to that state on that day."""
    rng = np.random.default_rng(seed)
    extra = extra or {}
    rows: dict[str, list[list[object]]] = {k: [] for k in HEADERS}
    rows["orders/products.csv"] = [[f"p-{c}", c] for c in CATEGORIES]
    rows["marketing/marketing_qualified_leads.csv"] = [["mql-1", "2017-12-01", "paid_search"]]
    rows["marketing/closed_deals.csv"] = [["mql-1", "seller-1", "2017-12-15"]]
    n = 0
    for day in range(DAYS):
        when = START + timedelta(days=day)
        for state, level in STATE_LEVELS.items():
            count = int(rng.poisson(level)) + extra.get((day, state), 0)
            for _ in range(count):
                n += 1
                oid, cid = f"o{n}", f"c{n}"
                category = CATEGORIES[n % len(CATEGORIES)]
                ts = f"{when.isoformat()} 12:00:00"
                rows["orders/orders.csv"].append(
                    [oid, cid, "delivered", ts, ts, ts, ts, (when + timedelta(days=10)).isoformat()]
                )
                rows["orders/customers.csv"].append([cid, cid, "01000", "city", state])
                rows["orders/order_items.csv"].append([oid, 1, f"p-{category}", f"seller-{n % 3}", ts, 100.0, 15.0])
                rows["payments/order_payments.csv"].append([oid, 1, "credit_card", 1, 115.0])
                rows["reviews/order_reviews.csv"].append([f"r{n}", oid, 5, ts])
    for relative, header in HEADERS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows[relative])
    return root

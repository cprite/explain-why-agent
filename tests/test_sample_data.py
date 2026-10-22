"""Integrity checks for the prepared Olist sample and answer key."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
ANSWER_KEY = ROOT / "eval" / "answer_key.json"

EXPECTED_ROW_COUNTS = {
    "marketing/closed_deals.csv": 842,
    "marketing/marketing_qualified_leads.csv": 8000,
    "orders/customers.csv": 30369,
    "orders/geolocation.csv": 10473,
    "orders/order_items.csv": 34642,
    "orders/orders.csv": 30256,
    "orders/product_category_name_translation.csv": 71,
    "orders/products.csv": 14222,
    "orders/sellers.csv": 2108,
    "payments/order_payments.csv": 31560,
    "reviews/order_reviews.csv": 30185,
}


def _data_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # header
        return sum(1 for _ in reader)


def test_sample_csv_row_counts() -> None:
    for relative, expected in EXPECTED_ROW_COUNTS.items():
        path = SAMPLE / relative
        assert path.is_file(), f"missing {relative}"
        assert _data_row_count(path) == expected, relative


def test_answer_key_has_ten_incidents_with_id_and_question() -> None:
    payload = json.loads(ANSWER_KEY.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 10
    for incident in payload:
        assert isinstance(incident, dict)
        assert incident.get("id")
        assert incident.get("question")


def test_black_friday_order_volume_premise() -> None:
    """Incident-1 premise from data-prep/detectability_report.md."""
    orders_path = SAMPLE / "orders" / "orders.csv"
    daily: Counter[date] = Counter()
    with orders_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = date.fromisoformat(row["order_purchase_timestamp"][:10])
            daily[day] += 1

    black_friday = date(2017, 11, 24)
    assert daily[black_friday] == 1176

    baseline_days = [date(2017, 11, d) for d in range(20, 24)]
    baseline_avg = sum(daily[d] for d in baseline_days) / len(baseline_days)
    assert 230 <= baseline_avg <= 240

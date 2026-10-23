"""Plan check for the local data adapter (build-plan task 3), run in CI.

Prints the result of a cross-source join (orders x payments: orders and payment value per month)
and of a write statement that must be rejected. Exits non-zero if either check fails.

    python -m app.data.check
"""

from __future__ import annotations

import sys

from app.data.layer import QueryError, QueryResult
from app.data.local import LocalDataLayer

CROSS_SOURCE_SQL = """
SELECT strftime(o.order_purchase_timestamp, '%Y-%m') AS month,
       count(DISTINCT o.order_id)            AS orders,
       round(sum(p.payment_value), 2)        AS payment_value
FROM orders.orders AS o
JOIN payments.order_payments AS p ON p.order_id = o.order_id
GROUP BY 1
ORDER BY 1
""".strip()

WRITE_SQL = "DELETE FROM orders.orders"


def main() -> int:
    """Run both checks and print their outcome; return the process exit code."""
    ok = True
    with LocalDataLayer(run_id="plan-check-data") as layer:
        print(f"sources: {', '.join(layer.list_sources())}")
        joined = layer.query(None, CROSS_SOURCE_SQL)
        if isinstance(joined, QueryResult) and joined.row_count > 0:
            print(f"[PASS] cross-source join orders x payments: {joined.row_count} monthly rows "
                  f"(query {joined.query_id}, truncated={joined.truncated})")
            print(f"  {'month':<8} {'orders':>7} {'payment_value':>14}")
            for row in joined.rows:
                print(f"  {row['month']:<8} {row['orders']:>7} {row['payment_value']:>14.2f}")
        else:
            ok = False
            print(f"[FAIL] cross-source join returned no rows: {joined}")

        rejected = layer.query(None, WRITE_SQL)
        if isinstance(rejected, QueryError) and rejected.code == "rejected":
            print(f"[PASS] write statement rejected: {WRITE_SQL!r} -> {rejected.code}: {rejected.message}")
        else:
            ok = False
            print(f"[FAIL] write statement was not rejected: {rejected}")
        print(f"query log: {layer.log.path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

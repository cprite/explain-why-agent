# Data sample

Local copy of the public Olist e-commerce data, split into four source systems (one folder each) for cross-source investigation demos and evaluation.

## Sources and licence

- Kaggle datasets: [`olistbr/brazilian-ecommerce`](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and [`olistbr/marketing-funnel-olist`](https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist).
- Licence: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Attribute Olist / the Kaggle publishers when you reuse this sample.
- Personal data: none beyond the public, already-scrubbed Kaggle release (hashed customer ids, zip-code prefixes, no names/emails/phones in structured columns).

## Folders and row counts

Data rows only (CSV header excluded):

| Path | Rows |
|---|---:|
| `marketing/closed_deals.csv` | 842 |
| `marketing/marketing_qualified_leads.csv` | 8000 |
| `orders/customers.csv` | 30369 |
| `orders/geolocation.csv` | 10473 |
| `orders/order_items.csv` | 34642 |
| `orders/orders.csv` | 30256 |
| `orders/product_category_name_translation.csv` | 71 |
| `orders/products.csv` | 14222 |
| `orders/sellers.csv` | 2108 |
| `payments/order_payments.csv` | 31560 |
| `reviews/order_reviews.csv` | 30185 |

## Planted incidents

Ten evaluation incidents are planted in this sample: eight synthetic injections and two real events. They are listed in `eval/answer_key.json`, which only the evaluation reads — the agent under test must not use that file.

## How it was built / regenerate

Research plan: `docs/research/olist-dataset-and-incident-plan.md`.

Rebuild steps (see `data-prep/README.md` for detail):

1. `data-prep/build_sample.py` — sample and split the Kaggle downloads into these folders.
2. `data-prep/inject_incidents.py` — plant the ten incidents and write the answer key.
3. `data-prep/detectability_report.py` — check that each incident is measurable (`detectability_report.md`).

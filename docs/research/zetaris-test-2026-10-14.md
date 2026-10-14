# Zetaris on our instance — tested recipe (14 Oct 2026)

Tested on our own Zetaris instance (hackathon bundle 2.4.3, AWS eu-north-1) with throwaway data:
two separate Postgres databases, three dummy rows each. Everything below ran successfully unless it
says otherwise. This closes the open risk "Postgres registration is untested in Zetaris's repo".

## Access from Python (REST)

Base URL through the Pi's SSH tunnel: `http://127.0.0.1:8888/api/v1.0`.

1. **Session token:** `GET /auth/login` with HTTP Basic auth (admin email and password) returns
   `{"idToken", "refreshToken"}`.
2. **API key:** `POST /auth/api-key` with `Authorization: Bearer <idToken>` and body
   `{"name": "...", "expiryDate": "2026-11-30T00:00:00Z"}` returns `{"apiKey"}`. Ours is called
   `hackathon-agents`, valid to 30 Nov, stored in `~/.openclaw/credentials/zetaris.env`.
3. **Run SQL:** `POST /sql-editor/sqls/run` with `Authorization: Bearer <apiKey>`, headers
   `X-Org-ID: 1` and `X-Request-ID: <uuid>`, body
   `{"queryId": "<uuid>", "sql": "...", "limit": 50, "source": "SqlEditor"}`. The response is
   `{"headers": [...], "data": [[...]], "total": n, "timeUsed": ms}`.

Every value comes back as a string; decimals come back with 18 places (`"10.500000000000000000"`).
The adapter must convert types.

## Registering a Postgres database

The databases ran as containers on the Zetaris Docker network (`zetaris_default`), so the driver
reaches them by container name.

```sql
CREATE DATASOURCE pgtest_a DESCRIBE BY "throwaway test" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://pgtest-a:5432/shop",
  username "tester",
  password "testpw"
)
REGISTER DATASOURCE TABLES FROM pgtest_a
SELECT * FROM pgtest_a.orders
SHOW TABLES IN pgtest_a          -- plain SHOW TABLES is disabled
```

The Postgres JDBC driver is already in the bundle; nothing had to be installed.

## Joining two separate databases

Directly, without a semantic layer:

```sql
SELECT o.seller_id, AVG(r.score) AS avg_score, COUNT(*) AS n
FROM pgtest_a.orders o JOIN pgtest_b.reviews r ON r.order_id = o.order_id
GROUP BY o.seller_id
```

Returned the right answer (s1 → 4.5 from 2 reviews, s2 → 1.0) in about 2 seconds.

## Unified Semantic Layer over both

```sql
CREATE NAMESPACE IF NOT EXISTS lightning.metastore            -- parent must exist first
CREATE NAMESPACE IF NOT EXISTS lightning.metastore.usl_test

COMPILE USL IF NOT EXISTS shop_usl DEPLOY NAMESPACE lightning.metastore.usl_test DDL
CREATE TABLE orders (
    order_id varchar(10) NOT NULL PRIMARY KEY,
    seller_id varchar(10),
    amount decimal(10,2),
    created date
);
CREATE TABLE reviews (
    review_id varchar(10) NOT NULL PRIMARY KEY,
    order_id varchar(10) NOT NULL FOREIGN KEY REFERENCES orders(order_id),
    score int
)

ACTIVATE USL TABLE lightning.metastore.usl_test.shop_usl.orders AS
  SELECT order_id, seller_id, CAST(amount AS DECIMAL(10,2)) AS amount, created FROM pgtest_a.orders
ACTIVATE USL TABLE lightning.metastore.usl_test.shop_usl.reviews AS
  SELECT review_id, COALESCE(order_id, '') AS order_id, score FROM pgtest_b.reviews

SELECT o.seller_id, AVG(r.score) FROM lightning.metastore.usl_test.shop_usl.orders o
  JOIN lightning.metastore.usl_test.shop_usl.reviews r ON r.order_id = o.order_id
  GROUP BY o.seller_id
RUN DQ TABLE lightning.metastore.usl_test.shop_usl.reviews
```

The join through the layer returned the same answer in about 1 second. The data-quality check
reported 3 of 3 rows valid for both the primary key and the foreign key.

## Pitfalls hit

- `CREATE NAMESPACE lightning.metastore.x` fails until `lightning.metastore` itself exists.
- Activation checks nullability strictly: a column declared `NOT NULL` must be non-nullable in the
  activation query too, even when the source has no nulls. Wrap it in `COALESCE(...)`.
- Plain `SHOW NAMESPACES` and `SHOW TABLES` are disabled; use `SHOW TABLES IN <source>`.
- Errors come back as HTTP 400 with a long Java stack trace; the useful text follows
  `Exception: ` or is in `msg`.

## What is still on the instance

The throwaway containers `pgtest-a` and `pgtest-b`, the data sources `pgtest_a` and `pgtest_b`, and the
semantic layer `lightning.metastore.usl_test.shop_usl`. None of it is project data; it can be removed
before the build or left as a reference.

## Real sample loaded and tested (14 Oct, afternoon)

Nikolay asked to load the real data and start testing. The accepted Olist sample from `data-prep/out/`
(declared pre-existing data) now lives on the instance as four separate Postgres databases, one per
source system, each in its own container with a persistent volume, on the Zetaris network:

| Database (container) | Tables | Rows |
|---|---|---|
| `olist-orders` | orders, order_items, customers, products, sellers, geolocation, category translation | 30,256 orders, 34,642 items, 30,369 customers, 14,222 products, 2,108 sellers |
| `olist-payments` | order_payments | 31,560 |
| `olist-reviews` | order_reviews | 30,185 |
| `olist-marketing` | marketing_qualified_leads, closed_deals | 8,000 and 842 |

Row counts match the CSV files exactly. Zetaris data sources: `olist_orders`, `olist_payments`,
`olist_reviews`, `olist_marketing` (database password in `zetaris.env` as `OLIST_PG_PASSWORD`).

Five incident metrics computed through Zetaris and independently with pandas on the same files:

| Metric | Sources joined | Zetaris | pandas | Time |
|---|---|---|---|---|
| Orders on 24 Nov 2017 | orders | 1,176 | 1,176 | 0.5 s |
| Watches review score, Jan 2018 | reviews × orders | 1.88 | 1.88 | 2.1 s |
| Minas Gerais boleto share, 5–25 Mar 2018 | payments × orders | 8.6% | 8.6% | 1.3 s |
| Rio de Janeiro average freight, Aug 2018 | orders | 32.62 | 32.62 | 1.1 s |
| Orders and review score by month, Nov 2017–Feb 2018 | orders × reviews | identical, 4 rows | | 1.4 s |

All five match. On the smallest instance (2 vCPUs) cross-source queries over the full sample answer in
about 1–2 seconds, which is fast enough for an investigation loop of dozens of queries.

More pitfalls: a data-source description may not contain a colon; product size columns arrive as
decimals (`40.0`) and need a numeric type; the SQL dialect is Spark SQL (`date_format`, `DATE '…'`,
`TIMESTAMP '…'`).

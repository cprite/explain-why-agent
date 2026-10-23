# Sprint 6b — Zetaris adapter over one Unified Semantic Layer, with local fallback

Build-plan task 10, issue #13. This is the default data path from architecture §3: the agents query
the four source systems through one Zetaris Unified Semantic Layer (USL) over REST. If Zetaris is
down, each query falls back to the local DuckDB adapter, and the result says so.

## What was built

### The USL: `lightning.metastore.explain_why.olist_usl`

The layer is defined once, in `app/data/usl.py` (`OLIST_USL`). The setup statements, the adapter's
type conversion and the Postgres load scripts are all generated from that one definition.

| Source system | Zetaris data source | USL tables |
|---|---|---|
| Orders and fulfilment | `olist_orders` | `customers`, `geolocation`, `product_category_name_translation`, `products`, `sellers`, `orders`, `order_items` |
| Payments | `olist_payments` | `order_payments` |
| Reviews | `olist_reviews` | `order_reviews` |
| Marketing | `olist_marketing` | `marketing_qualified_leads`, `closed_deals` |

- Columns are typed: `varchar(n)`, `int`, `double`, `decimal(10,2)`/`decimal(12,2)` for money,
  `date`, `timestamp`, `boolean`. Seven primary keys: `customers`, `geolocation`, the category
  translation, `products`, `sellers`, `orders` and `marketing_qualified_leads`. The other four tables
  have no unique single column in the sample (`review_id` repeats), so they get no primary key.
- Nine foreign keys. Three cross source systems: `order_payments.order_id → orders`,
  `order_reviews.order_id → orders` and `closed_deals.seller_id → sellers`. The other six stay inside
  one source: `orders.customer_id`, `order_items.order_id/product_id/seller_id`,
  `products.product_category_name` and `closed_deals.mql_id`.
- Two data-quality rules: `payment_value_not_negative` on `order_payments` (`payment_value >= 0`) and
  `purchase_timestamp_present` on `orders` (`order_purchase_timestamp IS NOT NULL`).

### `scripts/zetaris_setup.py` (idempotent)

It sends one statement per request, each one whole. The `COMPILE USL` holds all eleven
`CREATE TABLE`s and is sent as a single request; it is never split on `;`. Steps:

1. **Sources.** Runs `SHOW TABLES IN olist_<source>`. A data source that is already registered is
   left alone: it is never dropped or re-created, and only missing tables are imported. A missing
   source stops the script with instructions. With `--start-sources` on the Zetaris host, the script
   starts the source's container from `docker-compose.zetaris-sources.yml` and registers it with
   `CREATE DATASOURCE … jdbcdriver "org.postgresql.Driver"`, then `REGISTER DATASOURCE TABLES`.
2. **Namespaces.** Creates `lightning.metastore` first, then `lightning.metastore.explain_why`. It
   looks with `SHOW NAMESPACES OR TABLES IN` first and creates only what is missing.
3. **USL.** Sends `COMPILE USL IF NOT EXISTS olist_usl DEPLOY NAMESPACE … DDL` only if `olist_usl` is
   not already listed. The 2.4.3.1 guide says repeat runs of `IF NOT EXISTS` are unconfirmed, so the
   script does not rely on it. It then prints the foreign keys.
4. **Activation.** Runs `ACTIVATE USL TABLE` for every table on every run. Non-varchar columns are
   `CAST` to their declared type, and primary keys are wrapped in `COALESCE`, because activation
   checks nullability. It also sets a table description for each table; a failed description is
   only a warning.
5. **Data quality.** Runs `REGISTER DQ` for each rule missing from `LIST DQ USL`, then `RUN DQ`.
   It prints the invalid-record count from `SHOW DQ INVALID RECORD`, together with the `RUN DQ`
   totals.
6. **Row counts.** Runs `COUNT(*)` on every USL table and compares it with the sample CSV (read with
   `csv.reader`, so multi-line reviews count once). A mismatch makes the script exit 1.
7. **Cross-source join** through the USL: orders × payments × reviews, by month, for Nov 2017 – Feb 2018.

Other modes: `--dry-run` prints every statement and sends nothing. `--write-init-sql` regenerates
`scripts/zetaris_sources/<source>.sql`. Exit codes: 0 done, 1 a step failed, 2 the Zetaris settings
are missing. The Postgres password appears only inside `CREATE DATASOURCE`; everything printed is
masked.

`docker-compose.zetaris-sources.yml` describes the four sources: four `postgres:16` containers
(`olist-orders`, `olist-payments`, `olist-reviews`, `olist-marketing`) on the external
`zetaris_default` network, with no published ports. Each container loads its sample CSVs once, on
its first start with an empty volume.

### `ZetarisDataLayer` (`app/data/zetaris.py`)

- It has the same interface as `LocalDataLayer`: `list_sources`, `describe` and `query` with
  identical signatures. It also uses the same `check_read_only` guard, row limit (`MAX_QUERY_ROWS`,
  with `limit+1` sent so truncation can be detected), query ids (`q001…`) and JSONL log. A query
  never raises.
- **SQL.** Agents keep writing `<source>.<table>`. The adapter rewrites these to the USL names
  (`orders.orders` → `lightning.metastore.explain_why.olist_usl.orders`); string literals, comments
  and quoted identifiers are left alone. With a source scope, an unqualified table right after
  `FROM`/`JOIN` is rewritten too. The query keeps the SQL as the agent wrote it, and the log also
  records the SQL sent (`zetaris_sql`).
- **REST client.** Sends `POST <ZETARIS_URL>/sql-editor/sqls/run` with `Authorization: Bearer
  <ZETARIS_API_KEY>`, `X-Org-ID`, and a fresh UUID in both `X-Request-ID` and `queryId`. Every call
  has a timeout (`QUERY_TIMEOUT_SECONDS`, connect at most 10 s).
  - If no key is set, or the key is refused with 401/403, the client logs in once with
    `GET /auth/login` (Basic `ZETARIS_USERNAME`/`ZETARIS_PASSWORD`) and uses the `idToken` from then
    on.
  - Credentials only ever go into request headers. Error texts are scrubbed of the key, token and
    password, and are cut down to the useful part of the Java stack trace (the `msg` field, or the
    text after `Exception: `).
- **Types.** REST returns every value as a string. Each column is converted using, in order:
  1. the type in the header, if the server sends one;
  2. the USL type of a column with that name in the tables the query reads;
  3. inference from the column's values: int, then float, then timestamp, else string.

  The results have the same shapes the local adapter returns: int → `int`; decimal (including
  `0E-18`) and double → `float`; date → `YYYY-MM-DD`; timestamp → ISO (`2017-11-24T10:53:01`);
  boolean → `bool`; null → `None`. An all-digit `varchar` id stays a string.
- **Fallback.** A connection error, timeout or HTTP 5xx is retried once, after
  `ZETARIS_RETRY_DELAY_SECONDS` (1 s by default). If the retry also fails, the same statement runs on
  the local adapter under the same query id. Both the result and the log line then say
  `adapter: "local (fallback from zetaris)"`, and the log line adds a `fallback_reason`.
  - A 4xx is not an outage. It is returned as `code: "failed"` with Zetaris's message, so the
    Investigator can repair the SQL.
  - Refused credentials are reported, not hidden behind the fallback. This follows the Meterless
    rule from Sprint 2.
- **`describe`.** Returns the USL column types, and row counts from one `COUNT(*) … UNION ALL`
  query per source, cached for the run. If Zetaris is down it falls back to the local description.
- **Query log** (`logs/queries-<run>.jsonl`). The adapter writes the usual fields (`adapter`, `sql`,
  `duration_ms`, `row_count`, `status`, …) plus `usl_tables` (fully qualified) and `zetaris_sql`.
  After a fallback the line also has `fallback_reason`.

### Selection and configuration

- `app/data/factory.py` `make_data_layer` chooses the adapter, and `run.py` uses it.
  - `SAMPLE_MODE=true` → local, always; nothing touches the network.
  - `DATA_LAYER=local` → local.
  - `DATA_LAYER=zetaris` (the default) → Zetaris. If `ZETARIS_URL` is empty it uses local and says
    so on stderr. If the URL is set but the organisation id or credentials are missing, it stops
    with a clear error.
- `DataLayer` gained a default `close()` and context manager. `QueryLog.write` gained an optional
  `extra` dict. `LocalDataLayer.execute()` runs a statement without logging or replay; the fallback
  uses it.
- New settings, all documented in `.env.example` with no values: `DATA_LAYER`, `ZETARIS_ORG_ID`,
  `ZETARIS_USERNAME`, `ZETARIS_PASSWORD`, `ZETARIS_RETRY_DELAY_SECONDS` and `OLIST_PG_PASSWORD`.
  `ZETARIS_URL` and `ZETARIS_API_KEY` were already there.

### Parity

- `app/data/parity.py` holds what the CI plan check and the live script share: the query list,
  fixture read and write, a replay transport, the Zetaris wire encoding, the comparison and the
  side-by-side printout.
- `scripts/zetaris_parity.py` needs live credentials. It runs every parity query through both
  adapters with fallback off (so a Zetaris failure is a FAIL, never a quiet local answer). It prints
  each pair side by side, then a parity table, then `PASS`/`FAIL`, and exits 0 or 1.
  - Without credentials it prints a clear message and exits 2.
  - `--record` rewrites `tests/fixtures/zetaris/` from the live responses.
  - `--synthetic` writes fixtures from DuckDB with no Zetaris (see "Known limits").
- The comparison passes rows that are identical, or that differ only in order. It has one more
  pass, for an `ORDER BY … LIMIT n` that cuts through a tie: the Day 1 seller query cuts its
  `LIMIT 20` through a tie, and engines may keep different sellers. That pass needs a statement
  ending in `LIMIT n` with `n` rows returned, the same numbers with the same group sizes on both
  sides, and identical labels in every group except the last tie group (the rows sharing the last
  row's numbers). Labels attached to different numbers (swapped categories) and a date printed as
  a timestamp (`2017-11-24` vs `2017-11-24 00:00:00`) fail. Each pass says which case it was.

## Deliberately left out

- **The agents' SQL dialect.** The Investigator prompt and `SqlProposal` still say "DuckDB". On the
  Zetaris path, Spark SQL runs the statements, and a DuckDB-only function (`strftime`) comes back as
  a `failed` error for the Investigator to repair. All five Day 1 queries are standard SQL
  (`DATE '…'`, CTEs, `ROUND`, `NULLIF`, `NULLS LAST`). Changing the prompts would invalidate the
  sample-mode cache, so it is left for a prompt-tuning task.
- **Recording query rows for sample mode on the Zetaris path.** `RECORD_CACHE` still records only
  through the local adapter.
- **Composite primary keys** (`order_items`, `order_payments`): the DDL form is not documented.
- **`MATERIALIZE USL TABLE` and table caching.**
- **Cross-table DQ rules:** these are unconfirmed in the Zetaris companion guide, so cross-table
  checks stay as foreign-key constraints and plain join queries.

## How it was tested

- `ruff check .` → `All checks passed!`. `pytest -q` → `199 passed`; 85 of these are new, in the
  three files below.
- `tests/test_data_zetaris.py` (54 tests). Every REST exchange goes through `httpx.MockTransport`;
  nothing in these tests can reach a server.
  - Interface: signatures match `LocalDataLayer`. Factory: every selection, and the configuration
    errors.
  - Sample mode never touches the network: a subprocess runs `run.py` on the Day 1 question with
    Zetaris configured at an unreachable address. Every query-log line says `adapter: local`.
  - Requests: bearer key, `X-Org-ID`, a unique UUID `X-Request-ID`, `queryId`, the rewritten SQL,
    `limit+1`, and a timeout on every call (the read timeout and the 10 s connect timeout).
  - Auth: login when no key is set (Basic auth, one login reused); a refused key falls back to
    login and the token is used from then on; refused credentials come back as an error with no
    fallback.
  - No secret reaches a result or the log, even when Zetaris echoes it. Stack traces are trimmed to
    their message.
  - Guard: rejected statements never reach the network.
  - Truncation and the row cap. Rewrite cases: literals, comments, aliases, wrong source/table
    pairs, names that are already qualified, source scope.
  - Types: 18 conversion cases (int, decimal, `0E-18`, double, date, timestamp in three forms,
    boolean, null as `None`/`"null"`/empty, all-digit varchar ids, unparsable input); type-family
    names; per-column inference; USL types winning over inference; typed header objects.
  - Fallback: connection error, read timeout and 503 each make exactly two Zetaris calls, then
    return the local rows (`n = 31560`) marked `local (fallback from zetaris)`, with the reason in
    the log.
    - A first failure followed by a success stays on Zetaris.
    - A 400 makes one call and does not fall back.
    - With fallback off, the outage is reported.
    - A SQL error during fallback is marked with the fallback adapter.
  - Query log fields (`adapter`, `usl_tables`, `sql`, `zetaris_sql`, `duration_ms`, `row_count`).
  - `describe`: through Zetaris, cached, falling back to local, and reporting a USL error.
  - `.env.example` lists every new setting with no value.
- `tests/test_zetaris_setup.py` (15 tests) runs the script against `FakeZetaris`, a stateful fake
  that enforces what we learned on the real server:
  - one statement per request (a `;` is allowed only inside `COMPILE USL`);
  - the parent namespace must exist first;
  - a table must be activated before a DQ rule is registered on it;
  - a duplicate DQ rule or a second `COMPILE USL` is an error;
  - description text is limited to letters, digits, spaces and `_ . - ,`.

  The tests check:
  - the USL model matches the CSV files and headers, and every foreign key points at a primary key
    defined earlier;
  - the `COMPILE USL` has all 11 tables and goes out as one request;
  - registered sources build the USL, run DQ and print invalid counts;
  - running it twice leaves the fake's state unchanged, sends no CREATE/COMPILE/REGISTER, and
    re-activates all 11 tables;
  - a missing source without `--start-sources` stops with instructions; with it, docker and
    `CREATE DATASOURCE` run and the password is never printed;
  - a Zetaris error stops the run with its message;
  - the CLI exits 2 without settings, and `--dry-run` sends nothing;
  - the committed init SQL is current, and the compose file is checked.
- **Plan check D** (CI step `pytest -s -q tests/test_zetaris_plan_check.py`, 15 tests). The Day 1
  question's five queries run two ways. The first is through `ZetarisDataLayer`, with the REST
  responses replayed from `tests/fixtures/zetaris/`; the replay requires the bearer, `X-Org-ID` and
  `X-Request-ID` headers and matches on the rewritten USL SQL. The second is `LocalDataLayer` on the
  sample. Both result sets are printed side by side. Three extra queries run the same way:
  `COUNT(*)` of orders, a types query (timestamps, dates, nulls, ints, decimals including zero) and
  a source-scoped query. All eight `PASS`. The output on this machine:

  ```text
  == plan check day1_orders_vs_baseline [synthetic (local DuckDB rows in Zetaris REST wire format)]: PASS
    local (DuckDB)            | zetaris (USL, REST)
           value     baseline |        value     baseline
            1176     136.5714 |         1176     136.5714
  == plan check day1_price_and_installments [synthetic (...)]: PASS
    avg_price_w~ avg_price_b~ discount_pr~ discount_pr~ | avg_price_w~ avg_price_b~ discount_pr~ discount_pr~
         133.669     165.0758            1            1 |      133.669     165.0758            1            1
  ```

  The seller query prints all 20 rows, and every number matches. The file also checks that the
  fixtures contain no URL, host, IP address, token, key, password, org or request header. It also
  checks that they are in REST wire format: only strings and nulls, 18-place decimals, `0E-18`, and
  `yyyy-MM-dd HH:mm:ss` timestamps.
- The CI plan checks A–C are unchanged and still pass. `run.py` now selects the adapter through the
  factory, and in sample mode it gets the local one.

## Known limits

- **The fixtures are synthetic until the maintainer records them live.** This sandbox cannot reach
  Zetaris, so `scripts/zetaris_parity.py --synthetic` wrote `tests/fixtures/zetaris/`. It takes the
  local DuckDB rows and encodes them exactly as Zetaris REST returns them: strings, 18-place
  decimals, `0E-18`, timestamps with a space. Each file says so in `recorded_with`.
  - So the plan check proves the adapter path (rewrite, request shape, type conversion, comparison)
    on documented wire data. It does not prove that Zetaris computes the same numbers.
  - Two figures do tie back to real runs. The 30,256 orders match the session's live probe on
    23 Oct (REST returned `[["30256"]]`). The 1,176 orders on 24 Nov 2017 match the live Zetaris
    figure from 14 Oct.
  - With credentials, `python scripts/zetaris_parity.py --record` replaces the files with real
    responses (`recorded_with: "zetaris (live REST response)"`). The plan check then replays those.
  - **Acceptance criterion 7 stays open until that live recording is committed.** The maintainer
    runs `python scripts/zetaris_parity.py --record` over the tunnel, checks that every file reads
    `recorded_with: "zetaris (live REST response)"` and holds no host or token
    (`tests/test_zetaris_plan_check.py` checks the latter), and commits the files.
- **Live parity result:** _to be added by the maintainer after running
  `python scripts/zetaris_parity.py` against the AWS instance._
- **Setup statements that no one has run on our server yet.** The 14 Oct test covered `date`, `int`,
  `decimal` and `varchar` columns, a two-table USL with one foreign key, and activation with `CAST`
  and `COALESCE`. Not yet tried on 2.4.3: `timestamp`, `double` and `boolean` USL columns; USL
  tables without a primary key; `UPDATE USL … SET TABLE DESCRIPTION`; and the output shapes of
  `RUN DQ`, `LIST DQ USL` and `SHOW TABLES IN`. Listings are searched by value rather than by
  column name, for that reason. The first live `python scripts/zetaris_setup.py` is the test.
- **Which response field holds the invalid-record count is unknown.** The script takes `total` from
  `SHOW DQ INVALID RECORD` when the server sends it, else the number of rows returned (with a limit
  of 100,000). It also prints the `RUN DQ` row as it comes.
- **Nulls in `varchar` columns.** If REST sends a null as the string `"null"`, a `varchar` column
  keeps it as text. Other types convert it to `None`. The live parity run will show which it is.
- **Unqualified table names in a source scope** are rewritten only right after `FROM` or `JOIN`. A
  comma-separated `FROM a, b` is not rewritten, and a CTE named like a table of that source is
  replaced by the real table. Agents write `<source>.<table>` (the cross-source form), which is
  always rewritten.
- **Worst-case time for a failed query.** Before falling back, a query can wait two Zetaris
  timeouts plus the retry delay.

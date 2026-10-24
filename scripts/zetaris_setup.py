"""Set up Zetaris for the agents: four Postgres sources, one Unified Semantic Layer, data-quality rules.

    python scripts/zetaris_setup.py                  # check and create what is missing (idempotent)
    python scripts/zetaris_setup.py --start-sources  # also start the Postgres containers if a source is missing
    python scripts/zetaris_setup.py --dry-run        # print every statement, send nothing
    python scripts/zetaris_setup.py --write-init-sql # regenerate scripts/zetaris_sources/*.sql

Steps, each statement sent whole and one per request (Zetaris rejects two statements in one call):

1. Sources: `SHOW TABLES IN olist_<source>` for orders, payments, reviews, marketing. A registered source
   is left alone (never dropped or re-created). A missing one is started from
   `docker-compose.zetaris-sources.yml` (with `--start-sources`, on the Zetaris host), registered with
   `CREATE DATASOURCE … jdbcdriver "org.postgresql.Driver"` and its tables imported.
2. Namespaces `lightning.metastore` (parent first) and `lightning.metastore.explain_why`, if missing.
3. `COMPILE USL olist_usl` over all eleven tables with typed columns and foreign keys, if missing.
4. `ACTIVATE USL TABLE` for every table, every run (a model change clears activation), and table
   descriptions.
5. Data-quality rules (`REGISTER DQ`, if missing), `RUN DQ` and the invalid-record count from
   `SHOW DQ INVALID RECORD`.
6. Row counts through the USL against the sample files, then a cross-source join through the USL.

Needs `ZETARIS_URL`, `ZETARIS_ORG_ID` and `ZETARIS_API_KEY` (or `ZETARIS_USERNAME` and
`ZETARIS_PASSWORD`); `OLIST_PG_PASSWORD` only when a source has to be registered. Exit 0 when done,
1 when a step failed, 2 when the Zetaris settings are missing. No credential is printed.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT, get_settings
from app.data.usl import (
    DQ_RULES,
    OLIST_USL,
    SOURCES,
    TABLES,
    USL_NAME,
    USL_NAMESPACE,
    USL_NAMESPACE_PARENT,
    USL_PATH,
    activate_sql,
    compile_usl_sql,
    datasource_name,
    describe_sql,
    foreign_keys,
    postgres_init_sql,
    register_dq_sql,
    tables_of,
)
from app.data.zetaris import (
    RestResult,
    ZetarisClient,
    ZetarisRequestError,
    ZetarisUnavailable,
)

COMPOSE_FILE = REPO_ROOT / "docker-compose.zetaris-sources.yml"
INIT_SQL_DIR = REPO_ROOT / "scripts" / "zetaris_sources"
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
PG_DATABASE = "olist"
PG_USER = "olist"
STATEMENT_TIMEOUT_SECONDS = 300.0
COMPOSE_TIMEOUT_SECONDS = 600
MAX_ROWS = 100_000

CROSS_SOURCE_SQL = f"""WITH pay AS (
  SELECT order_id, SUM(payment_value) AS paid FROM {USL_PATH}.order_payments GROUP BY order_id
),
rev AS (
  SELECT order_id, AVG(review_score) AS score FROM {USL_PATH}.order_reviews GROUP BY order_id
)
SELECT date_format(o.order_purchase_timestamp, 'yyyy-MM') AS month,
       COUNT(*) AS orders,
       ROUND(SUM(pay.paid), 2) AS payment_value,
       ROUND(AVG(rev.score), 2) AS avg_review_score
FROM {USL_PATH}.orders o
LEFT JOIN pay ON pay.order_id = o.order_id
LEFT JOIN rev ON rev.order_id = o.order_id
WHERE o.order_purchase_timestamp >= TIMESTAMP '2017-11-01 00:00:00'
  AND o.order_purchase_timestamp < TIMESTAMP '2018-03-01 00:00:00'
GROUP BY 1
ORDER BY 1"""

MISSING = ("Zetaris settings are missing: set ZETARIS_URL, ZETARIS_ORG_ID and ZETARIS_API_KEY (or "
           "ZETARIS_USERNAME and ZETARIS_PASSWORD). Nothing was sent. Use --dry-run to see the statements.")


class SetupError(Exception):
    """A step that cannot continue; the message says what to do."""


def cells(result: RestResult) -> set[str]:
    """Every value in a result, lower-cased: listings are searched by name, whatever their columns."""
    return {str(v).strip().lower() for row in result.data for v in row if v is not None}


def has_name(found: set[str], name: str) -> bool:
    """True if `name` is a value in a listing, bare or as the last part of a dotted name."""
    name = name.lower()
    return any(v == name or v.endswith("." + name) for v in found)


def sample_row_count(table: str) -> int:
    """Data rows in the sample CSV (csv.reader, so quoted newlines in reviews count once)."""
    path = SAMPLE_DIR / TABLES[table].source / f"{table}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


def create_datasource_sql(source: str, password: str) -> str:
    """`CREATE DATASOURCE` for one source's Postgres container on the Zetaris Docker network."""
    host = f"olist-{source}"
    return (
        f'CREATE DATASOURCE {datasource_name(source)} DESCRIBE BY "Olist {source} source system, Postgres" '
        f'OPTIONS (\n  jdbcdriver "org.postgresql.Driver",\n'
        f'  jdbcurl "jdbc:postgresql://{host}:5432/{PG_DATABASE}",\n'
        f'  username "{PG_USER}",\n  password "{password}"\n)'
    )


class Setup:
    """The setup steps against one Zetaris; `send` is the only way a statement leaves the script."""

    def __init__(
        self,
        client: ZetarisClient | None,
        *,
        out: Callable[[str], None] = print,
        start_sources: bool = False,
        pg_password: str = "",
        compose: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.client = client
        self.out = out
        self.start_sources = start_sources
        self.pg_password = pg_password
        self.compose = compose
        self.created: list[str] = []
        self.present: list[str] = []

    def redact(self, text: str) -> str:
        if self.pg_password:
            text = text.replace(self.pg_password, "***")
        return self.client.redact(text) if self.client else text

    def send(self, sql: str, *, limit: int = 1000, quiet: bool = False) -> RestResult:
        """Send one whole statement; print it (credentials masked) and how it went."""
        if not quiet:
            first = self.redact(sql).splitlines()[0]
            more = f" … ({len(sql.splitlines())} lines, sent as one statement)" if "\n" in sql else ""
            self.out(f"  > {first}{more}")
        if self.client is None:  # dry run: show multi-line statements in full
            if "\n" in sql and not quiet:
                self.out("    " + self.redact(sql).replace("\n", "\n    "))
            return RestResult(headers=[], header_types=[], data=[], total=0, body={})
        result = self.client.run_sql(sql, limit=limit, timeout=STATEMENT_TIMEOUT_SECONDS)
        if not quiet:
            self.out(f"    ok ({len(result.data)} rows)")
        return result

    def probe(self, sql: str) -> RestResult | None:
        """A read-only listing that may fail because the object does not exist yet."""
        if self.client is None:
            self.out(f"  > {sql}")
            return None
        try:
            return self.send(sql, quiet=True)
        except ZetarisRequestError:
            return None

    # --- steps ----------------------------------------------------------------------------------------

    def sources(self) -> None:
        self.out("1. Sources (Postgres databases registered as Zetaris data sources)")
        for source in SOURCES:
            ds = datasource_name(source)
            expected = [t.name for t in tables_of(source)]
            listing = self.probe(f"SHOW TABLES IN {ds}")
            if self.client is None:
                self.out(f"    if {ds} is missing: " + create_datasource_sql(source, "<OLIST_PG_PASSWORD>")
                         .replace("\n", " ") + f"; REGISTER DATASOURCE TABLES FROM {ds}")
                continue
            if listing is None:
                self.register_source(source)
                listing = self.send(f"SHOW TABLES IN {ds}", quiet=True)
            else:
                self.present.append(f"data source {ds}")
            found = cells(listing)
            for table in [t for t in expected if not has_name(found, t)]:
                self.send(f'REGISTER DATASOURCE TABLE "{table}" FROM {ds}')
                self.created.append(f"table {ds}.{table}")
            self.out(f"  {ds}: {len(expected)} tables ({', '.join(expected)})")

    def register_source(self, source: str) -> None:
        ds = datasource_name(source)
        if not self.start_sources:
            raise SetupError(
                f"data source {ds} is not registered. On the Zetaris host, run this script with "
                f"--start-sources (it starts olist-{source} from {COMPOSE_FILE.name}) and OLIST_PG_PASSWORD set.")
        if not self.pg_password:
            raise SetupError(f"OLIST_PG_PASSWORD is needed to register {ds}")
        self.out(f"  starting container olist-{source} ({COMPOSE_FILE.name})")
        done = self.compose(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait", f"olist-{source}"],
            cwd=REPO_ROOT, timeout=COMPOSE_TIMEOUT_SECONDS, check=False, capture_output=True, text=True,
        )
        if done.returncode != 0:
            raise SetupError(f"docker compose failed for olist-{source}: {self.redact(done.stderr or '')[-500:]}")
        self.send(create_datasource_sql(source, self.pg_password))
        self.send(f"REGISTER DATASOURCE TABLES FROM {ds}")
        self.created.append(f"data source {ds}")

    def namespaces(self) -> None:
        self.out("2. Namespaces")
        parent = self.probe(f"SHOW NAMESPACES OR TABLES IN {USL_NAMESPACE_PARENT}")
        if self.client is not None and parent is not None:
            self.present.append(f"namespace {USL_NAMESPACE_PARENT}")
        else:
            self.send(f"CREATE NAMESPACE IF NOT EXISTS {USL_NAMESPACE_PARENT}")
            self.created.append(f"namespace {USL_NAMESPACE_PARENT}")
            parent = None
        child = USL_NAMESPACE.rsplit(".", 1)[1]
        if parent is not None and has_name(cells(parent), child):
            self.present.append(f"namespace {USL_NAMESPACE}")
        else:
            self.send(f"CREATE NAMESPACE IF NOT EXISTS {USL_NAMESPACE}")
            self.created.append(f"namespace {USL_NAMESPACE}")

    def usl(self) -> None:
        self.out(f"3. Unified Semantic Layer {USL_PATH}")
        listing = self.probe(f"SHOW NAMESPACES OR TABLES IN {USL_NAMESPACE}")
        if listing is not None and has_name(cells(listing), USL_NAME):
            self.present.append(f"USL {USL_PATH}")
            self.out(f"  {USL_NAME} exists; not compiled again")
        else:
            self.send(compile_usl_sql())
            self.created.append(f"USL {USL_PATH}")
        self.out(f"  {len(OLIST_USL)} tables over {len(SOURCES)} sources; foreign keys:")
        for column, target, kind in foreign_keys():
            self.out(f"    {column} -> {target} ({kind})")

    def activate(self) -> None:
        self.out("4. Activation (every table, every run) and descriptions")
        for table in OLIST_USL:
            self.send(activate_sql(table))
        for table in OLIST_USL:
            try:
                self.send(describe_sql(table), quiet=True)
            except ZetarisRequestError as exc:
                self.out(f"  warning: description for {table.name} not set: {exc}")

    def data_quality(self) -> None:
        self.out("5. Data quality")
        listing = self.probe(f"LIST DQ USL {USL_PATH}")
        found = cells(listing) if listing is not None else set()
        for rule in DQ_RULES:
            table = TABLES[rule.table]
            if self.client is not None and has_name(found, rule.name):
                self.present.append(f"DQ rule {rule.name}")
            else:
                self.send(register_dq_sql(rule))
                self.created.append(f"DQ rule {rule.name}")
            run = self.send(f"RUN DQ {rule.name} TABLE {table.fqn}")
            invalid = self.send(f"SHOW DQ INVALID RECORD {rule.name} TABLE {table.fqn}", limit=MAX_ROWS)
            if self.client is None:
                continue
            summary = ", ".join(f"{h}={v}" for row in run.data for h, v in zip(run.headers, row, strict=False))
            count = invalid.total if invalid.total is not None else len(invalid.data)
            self.out(f"  rule {rule.name} on {rule.table} ({rule.expression}): "
                     f"invalid records: {count}" + (f" [RUN DQ: {summary}]" if summary else ""))

    def row_counts(self) -> bool:
        self.out("6. Row counts through the USL against the sample files")
        ok = True
        for source in SOURCES:
            tables = tables_of(source)
            sql = "\nUNION ALL\n".join(
                f"SELECT '{t.name}' AS table_name, COUNT(*) AS row_count FROM {t.fqn}" for t in tables)
            result = self.send(sql, quiet=True)
            if self.client is None:
                continue
            counts = {row[0]: int(row[1]) for row in result.data}
            for table in tables:
                expected = sample_row_count(table.name)
                got = counts.get(table.name)
                mark = "ok" if got == expected else "MISMATCH"
                ok = ok and got == expected
                self.out(f"  {table.fqn}: {got} (sample {expected}) {mark}")
        return ok

    def cross_source_join(self) -> None:
        self.out("7. Cross-source join through the USL (orders x payments x reviews, by month)")
        result = self.send(CROSS_SOURCE_SQL)
        if self.client is None:
            return
        self.out("  " + " ".join(f"{h:>16}" for h in result.headers))
        for row in result.data:
            self.out("  " + " ".join(f"{'' if v is None else v:>16}" for v in row))

    def run(self) -> int:
        try:
            self.sources()
            self.namespaces()
            self.usl()
            self.activate()
            self.data_quality()
            counts_ok = self.row_counts()
            self.cross_source_join()
        except SetupError as exc:
            self.out(f"FAILED: {exc}")
            return 1
        except (ZetarisRequestError, ZetarisUnavailable) as exc:
            self.out(f"FAILED: Zetaris: {self.redact(str(exc))}")
            return 1
        if self.client is None:
            self.out("dry run: nothing was sent")
            return 0
        self.out(f"created: {', '.join(self.created) or 'nothing (everything was already there)'}")
        self.out(f"already present: {', '.join(self.present) or 'nothing'}")
        self.out(f"USL ready: {USL_PATH} ({len(OLIST_USL)} tables, {len(foreign_keys())} foreign keys)")
        if not counts_ok:
            self.out("FAILED: row counts through the USL differ from the sample")
            return 1
        return 0


def write_init_sql(directory: Path = INIT_SQL_DIR) -> list[Path]:
    """Write the Postgres load script for every source; return the paths."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for source in SOURCES:
        path = directory / f"{source}.sql"
        path.write_text(postgres_init_sql(source), encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None, *, client: ZetarisClient | None = None,
         compose: Callable[..., Any] = subprocess.run) -> int:
    """Run the setup; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start-sources", action="store_true",
                        help="start missing Postgres containers with docker compose (run on the Zetaris host)")
    parser.add_argument("--dry-run", action="store_true", help="print the statements, send nothing")
    parser.add_argument("--write-init-sql", action="store_true", help="regenerate scripts/zetaris_sources/*.sql")
    args = parser.parse_args(argv)

    if args.write_init_sql:
        for path in write_init_sql():
            print(f"wrote {path.relative_to(REPO_ROOT)}")
        return 0
    pg_password = os.environ.get("OLIST_PG_PASSWORD", "")
    if args.dry_run:
        return Setup(None, start_sources=args.start_sources, pg_password=pg_password).run()
    if client is None:
        settings = get_settings()
        try:
            client = ZetarisClient.from_settings(settings)
        except ValueError:
            print(MISSING, file=sys.stderr)
            return 2
    try:
        return Setup(client, start_sources=args.start_sources, pg_password=pg_password, compose=compose).run()
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

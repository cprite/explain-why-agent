"""The Unified Semantic Layer over the four sources: one model, used by setup, adapter and loaders.

`OLIST_USL` is the single definition of the Zetaris Unified Semantic Layer (USL)
`lightning.metastore.explain_why.olist_usl`: its eleven tables, typed columns, primary keys and the
foreign keys between them (four of which cross source systems), the Zetaris data source each table
is activated from, and the data-quality rules. From it come:

- the `COMPILE USL` and `ACTIVATE USL TABLE` statements sent by `scripts/zetaris_setup.py`;
- the column types `ZetarisDataLayer` uses to convert REST values (which all arrive as strings);
- the Postgres load scripts in `scripts/zetaris_sources/` for a fresh Zetaris host.

Table names are the CSV stems, unique across the four sources, so `<source>.<table>` in agent SQL maps
to exactly one USL table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

USL_NAMESPACE_PARENT = "lightning.metastore"
USL_NAMESPACE = "lightning.metastore.explain_why"
USL_NAME = "olist_usl"
USL_PATH = f"{USL_NAMESPACE}.{USL_NAME}"


@dataclass(frozen=True)
class UslColumn:
    """One USL column: name, declared type, and whether it is NOT NULL (primary keys)."""

    name: str
    type: str
    primary_key: bool = False
    references: str | None = None  # "<table>.<column>" for a foreign key


@dataclass(frozen=True)
class UslTable:
    """One USL table and the source system (and Zetaris data source) it is activated from."""

    name: str
    source: str
    description: str
    columns: tuple[UslColumn, ...] = field(default_factory=tuple)

    @property
    def datasource(self) -> str:
        """The Zetaris data source registered for this table's source system."""
        return datasource_name(self.source)

    @property
    def fqn(self) -> str:
        """Fully qualified name for querying: `lightning.metastore.explain_why.olist_usl.<table>`."""
        return f"{USL_PATH}.{self.name}"

    def column(self, name: str) -> UslColumn | None:
        """The column called `name`, or None."""
        return next((c for c in self.columns if c.name == name), None)


@dataclass(frozen=True)
class DqRule:
    """A data-quality rule registered with `REGISTER DQ` on one USL table."""

    name: str
    table: str
    expression: str
    description: str


def datasource_name(source: str) -> str:
    """Zetaris data source name for a source system, e.g. `orders` -> `olist_orders`."""
    return f"olist_{source}"


def _c(name: str, type_: str, *, pk: bool = False, ref: str | None = None) -> UslColumn:
    return UslColumn(name=name, type=type_, primary_key=pk, references=ref)


ID = "varchar(32)"

OLIST_USL: tuple[UslTable, ...] = (
    # --- orders and fulfilment (order management) ---
    UslTable("customers", "orders", "Customers of the shop, one row per customer id", (
        _c("customer_id", ID, pk=True),
        _c("customer_unique_id", ID),
        _c("customer_zip_code_prefix", "int"),
        _c("customer_city", "varchar(100)"),
        _c("customer_state", "varchar(2)"),
    )),
    UslTable("geolocation", "orders", "One location per zip code prefix", (
        _c("geolocation_zip_code_prefix", "int", pk=True),
        _c("geolocation_lat", "double"),
        _c("geolocation_lng", "double"),
        _c("geolocation_city", "varchar(100)"),
        _c("geolocation_state", "varchar(2)"),
    )),
    UslTable("product_category_name_translation", "orders", "Category names in Portuguese and English", (
        _c("product_category_name", "varchar(100)", pk=True),
        _c("product_category_name_english", "varchar(100)"),
    )),
    UslTable("products", "orders", "Product catalogue", (
        _c("product_id", ID, pk=True),
        _c("product_category_name", "varchar(100)", ref="product_category_name_translation.product_category_name"),
        _c("product_name_lenght", "double"),
        _c("product_description_lenght", "double"),
        _c("product_photos_qty", "double"),
        _c("product_weight_g", "double"),
        _c("product_length_cm", "double"),
        _c("product_height_cm", "double"),
        _c("product_width_cm", "double"),
    )),
    UslTable("sellers", "orders", "Marketplace sellers", (
        _c("seller_id", ID, pk=True),
        _c("seller_zip_code_prefix", "int"),
        _c("seller_city", "varchar(100)"),
        _c("seller_state", "varchar(2)"),
    )),
    UslTable("orders", "orders", "Orders with purchase, approval and delivery timestamps", (
        _c("order_id", ID, pk=True),
        _c("customer_id", ID, ref="customers.customer_id"),
        _c("order_status", "varchar(20)"),
        _c("order_purchase_timestamp", "timestamp"),
        _c("order_approved_at", "timestamp"),
        _c("order_delivered_carrier_date", "timestamp"),
        _c("order_delivered_customer_date", "timestamp"),
        _c("order_estimated_delivery_date", "date"),
    )),
    UslTable("order_items", "orders", "Order lines with product, seller, price and freight", (
        _c("order_id", ID, ref="orders.order_id"),
        _c("order_item_id", "int"),
        _c("product_id", ID, ref="products.product_id"),
        _c("seller_id", ID, ref="sellers.seller_id"),
        _c("shipping_limit_date", "timestamp"),
        _c("price", "decimal(10,2)"),
        _c("freight_value", "decimal(10,2)"),
    )),
    # --- payments (finance / payment provider) ---
    UslTable("order_payments", "payments", "Payments per order from the payment provider", (
        _c("order_id", ID, ref="orders.order_id"),
        _c("payment_sequential", "int"),
        _c("payment_type", "varchar(20)"),
        _c("payment_installments", "int"),
        _c("payment_value", "decimal(12,2)"),
    )),
    # --- reviews (customer experience) ---
    UslTable("order_reviews", "reviews", "Customer reviews with score and comment", (
        _c("review_id", ID),
        _c("order_id", ID, ref="orders.order_id"),
        _c("review_score", "int"),
        _c("review_comment_title", "varchar(255)"),
        _c("review_comment_message", "varchar(1000)"),
        _c("review_creation_date", "timestamp"),
        _c("review_answer_timestamp", "timestamp"),
    )),
    # --- marketing (CRM) ---
    UslTable("marketing_qualified_leads", "marketing", "Marketing qualified leads by first contact", (
        _c("mql_id", ID, pk=True),
        _c("first_contact_date", "date"),
        _c("landing_page_id", ID),
        _c("origin", "varchar(50)"),
    )),
    UslTable("closed_deals", "marketing", "Leads that closed and became sellers", (
        _c("mql_id", ID, ref="marketing_qualified_leads.mql_id"),
        _c("seller_id", ID, ref="sellers.seller_id"),
        _c("sdr_id", ID),
        _c("sr_id", ID),
        _c("won_date", "timestamp"),
        _c("business_segment", "varchar(100)"),
        _c("lead_type", "varchar(50)"),
        _c("lead_behaviour_profile", "varchar(50)"),
        _c("has_company", "boolean"),
        _c("has_gtin", "boolean"),
        _c("average_stock", "varchar(20)"),
        _c("business_type", "varchar(50)"),
        _c("declared_product_catalog_size", "double"),
        _c("declared_monthly_revenue", "double"),
    )),
)

SOURCES: tuple[str, ...] = ("orders", "payments", "reviews", "marketing")
TABLES: dict[str, UslTable] = {t.name: t for t in OLIST_USL}

DQ_RULES: tuple[DqRule, ...] = (
    DqRule("payment_value_not_negative", "order_payments", "payment_value >= 0",
           "A payment is never negative"),
    DqRule("purchase_timestamp_present", "orders", "order_purchase_timestamp IS NOT NULL",
           "Every order has a purchase timestamp"),
)


def tables_of(source: str) -> list[UslTable]:
    """USL tables activated from one source system, in model order."""
    return [t for t in OLIST_USL if t.source == source]


def foreign_keys() -> list[tuple[str, str, str]]:
    """Every foreign key as (table.column, referenced table.column, 'cross-source' or 'same source')."""
    out = []
    for table in OLIST_USL:
        for col in table.columns:
            if col.references:
                target = TABLES[col.references.split(".")[0]]
                kind = "cross-source" if target.source != table.source else "same source"
                out.append((f"{table.name}.{col.name}", col.references, kind))
    return out


# --- statements for scripts/zetaris_setup.py ------------------------------------------------------


def _column_ddl(col: UslColumn) -> str:
    parts = [col.name, col.type]
    if col.primary_key:
        parts.append("NOT NULL PRIMARY KEY")
    if col.references:
        table, column = col.references.split(".")
        parts.append(f"FOREIGN KEY REFERENCES {table}({column})")
    return " ".join(parts)


def compile_usl_sql() -> str:
    """The one `COMPILE USL` statement for all eleven tables; send it whole, never split on `;`.

    Tables are ordered so every referenced table is defined before the table that references it, and
    each CREATE TABLE starts on a new line (a Zetaris requirement).
    """
    blocks = []
    for table in OLIST_USL:
        cols = ",\n".join(f"    {_column_ddl(c)}" for c in table.columns)
        blocks.append(f"CREATE TABLE {table.name} (\n{cols}\n)")
    return (
        f"COMPILE USL IF NOT EXISTS {USL_NAME} DEPLOY NAMESPACE {USL_NAMESPACE} DDL\n"
        + ";\n".join(blocks)
    )


def _activation_expr(col: UslColumn) -> str:
    # Varchar columns pass through (the 14 Oct test activated strings uncast); every other column is
    # cast to its declared type so activation's schema check sees exactly that type. A NOT NULL
    # (primary key) column needs a non-null expression, hence COALESCE.
    expr = col.name if col.type.startswith("varchar") else f"CAST({col.name} AS {col.type.upper()})"
    if col.primary_key:
        default = "''" if col.type.startswith("varchar") else "0"
        expr = f"COALESCE({expr}, {default})"
    return f"{expr} AS {col.name}" if expr != col.name else col.name


def activate_sql(table: UslTable) -> str:
    """`ACTIVATE USL TABLE` binding one USL table to its registered Postgres table."""
    cols = ",\n       ".join(_activation_expr(c) for c in table.columns)
    return f"ACTIVATE USL TABLE {table.fqn} AS\nSELECT {cols}\nFROM {table.datasource}.{table.name}"


def describe_sql(table: UslTable) -> str:
    """`UPDATE USL … SET TABLE DESCRIPTION` (letters, digits, spaces and `_ . - ,` only)."""
    return f"UPDATE USL {table.fqn} SET TABLE DESCRIPTION {table.description}, from source {table.datasource}"


def register_dq_sql(rule: DqRule) -> str:
    """`REGISTER DQ` for one rule (no row alias, no window functions)."""
    return f"REGISTER DQ {rule.name} TABLE {TABLES[rule.table].fqn} AS {rule.expression}"


# --- Postgres load scripts for docker-compose.zetaris-sources.yml ------------------------------------

_PG_TYPES = {"int": "integer", "double": "double precision", "boolean": "boolean", "date": "date",
             "timestamp": "timestamp"}


def _pg_type(usl_type: str) -> str:
    if usl_type.startswith("varchar"):
        return "text"
    if usl_type.startswith("decimal"):
        return "numeric" + usl_type[len("decimal"):]
    return _PG_TYPES[usl_type]


def postgres_init_sql(source: str) -> str:
    """Init script for one source's Postgres container: create its tables and COPY the sample CSVs.

    Runs once, on the container's first start with an empty volume (the Postgres image's
    `/docker-entrypoint-initdb.d` convention), so restarting the containers never reloads data.
    """
    lines = [
        "-- Generated from app/data/usl.py by `python scripts/zetaris_setup.py --write-init-sql`.",
        (f"-- Loads data/sample/{source}/*.csv (mounted at /data) into container olist-{source}, "
         f"registered in Zetaris as {datasource_name(source)}."),
    ]
    for table in tables_of(source):
        cols = ",\n".join(f"    {c.name} {_pg_type(c.type)}" for c in table.columns)
        lines.append(f"CREATE TABLE {table.name} (\n{cols}\n);")
        lines.append(f"COPY {table.name} FROM '/data/{table.name}.csv' WITH (FORMAT csv, HEADER true);")
    return "\n".join(lines) + "\n"

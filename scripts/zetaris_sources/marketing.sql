-- Generated from app/data/usl.py by `python scripts/zetaris_setup.py --write-init-sql`.
-- Loads data/sample/marketing/*.csv (mounted at /data) into container olist-marketing, registered in Zetaris as olist_marketing.
CREATE TABLE marketing_qualified_leads (
    mql_id text,
    first_contact_date date,
    landing_page_id text,
    origin text
);
COPY marketing_qualified_leads FROM '/data/marketing_qualified_leads.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE closed_deals (
    mql_id text,
    seller_id text,
    sdr_id text,
    sr_id text,
    won_date timestamp,
    business_segment text,
    lead_type text,
    lead_behaviour_profile text,
    has_company boolean,
    has_gtin boolean,
    average_stock text,
    business_type text,
    declared_product_catalog_size double precision,
    declared_monthly_revenue double precision
);
COPY closed_deals FROM '/data/closed_deals.csv' WITH (FORMAT csv, HEADER true);

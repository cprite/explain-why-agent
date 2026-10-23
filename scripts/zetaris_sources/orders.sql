-- Generated from app/data/usl.py by `python scripts/zetaris_setup.py --write-init-sql`.
-- Loads data/sample/orders/*.csv (mounted at /data) into container olist-orders, registered in Zetaris as olist_orders.
CREATE TABLE customers (
    customer_id text,
    customer_unique_id text,
    customer_zip_code_prefix integer,
    customer_city text,
    customer_state text
);
COPY customers FROM '/data/customers.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE geolocation (
    geolocation_zip_code_prefix integer,
    geolocation_lat double precision,
    geolocation_lng double precision,
    geolocation_city text,
    geolocation_state text
);
COPY geolocation FROM '/data/geolocation.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE product_category_name_translation (
    product_category_name text,
    product_category_name_english text
);
COPY product_category_name_translation FROM '/data/product_category_name_translation.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE products (
    product_id text,
    product_category_name text,
    product_name_lenght double precision,
    product_description_lenght double precision,
    product_photos_qty double precision,
    product_weight_g double precision,
    product_length_cm double precision,
    product_height_cm double precision,
    product_width_cm double precision
);
COPY products FROM '/data/products.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE sellers (
    seller_id text,
    seller_zip_code_prefix integer,
    seller_city text,
    seller_state text
);
COPY sellers FROM '/data/sellers.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE orders (
    order_id text,
    customer_id text,
    order_status text,
    order_purchase_timestamp timestamp,
    order_approved_at timestamp,
    order_delivered_carrier_date timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date date
);
COPY orders FROM '/data/orders.csv' WITH (FORMAT csv, HEADER true);
CREATE TABLE order_items (
    order_id text,
    order_item_id integer,
    product_id text,
    seller_id text,
    shipping_limit_date timestamp,
    price numeric(10,2),
    freight_value numeric(10,2)
);
COPY order_items FROM '/data/order_items.csv' WITH (FORMAT csv, HEADER true);

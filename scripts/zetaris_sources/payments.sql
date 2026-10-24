-- Generated from app/data/usl.py by `python scripts/zetaris_setup.py --write-init-sql`.
-- Loads data/sample/payments/*.csv (mounted at /data) into container olist-payments, registered in Zetaris as olist_payments.
CREATE TABLE order_payments (
    order_id text,
    payment_sequential integer,
    payment_type text,
    payment_installments integer,
    payment_value numeric(12,2)
);
COPY order_payments FROM '/data/order_payments.csv' WITH (FORMAT csv, HEADER true);

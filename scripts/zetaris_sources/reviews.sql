-- Generated from app/data/usl.py by `python scripts/zetaris_setup.py --write-init-sql`.
-- Loads data/sample/reviews/*.csv (mounted at /data) into container olist-reviews, registered in Zetaris as olist_reviews.
CREATE TABLE order_reviews (
    review_id text,
    order_id text,
    review_score integer,
    review_comment_title text,
    review_comment_message text,
    review_creation_date timestamp,
    review_answer_timestamp timestamp
);
COPY order_reviews FROM '/data/order_reviews.csv' WITH (FORMAT csv, HEADER true);

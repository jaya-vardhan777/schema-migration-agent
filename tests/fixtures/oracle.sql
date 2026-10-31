CREATE TABLE sales.orders (
    order_id           NUMB(18,0)                 NOT NULL,
    customer_id        NUMBER(18,0)                 NOT NULL,
    order_amount       NUMBER(20,4),
    order_status       VARCHAR2(32)                 DEFAULT 'NEW',
    order_notes        CLOB,
    business_date      DATE                         NOT NULL,
    created_at         TIMESTAMP WITH TIME ZONE     DEFAULT SYSTIMESTAMP,
    payload_json       CLOB,
    is_active          NUMBER(1,0)                  DEFAULT 1,
    source_hash        RAW(32)
);

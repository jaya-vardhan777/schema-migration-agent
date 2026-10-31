CREATE TABLE analytics.events (
    event_id        BIGINT              NOT NULL,
    user_id         BIGINT              NOT NULL,
    event_type      VARCHAR(64)         NOT NULL,
    event_time      TIMESTAMPTZ         NOT NULL,
    payload         JSONB,
    amount          NUMERIC(18,4),
    is_test         BOOLEAN             DEFAULT FALSE,
    ingest_bytes    BYTEA
);

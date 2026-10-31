CREATE TABLE IF NOT EXISTS sales.orders (
  order_id INT64 NOT NULL,
  customer_id INT64 NOT NULL,
  order_amount NUMERIC(20, 4),
  order_status STRING DEFAULT 'NEW',
  order_notes STRING,
  business_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  payload_json STRING,
  is_active INT64 DEFAULT 1,
  source_hash BYTES,
  _ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL OPTIONS(description="Row ingestion timestamp injected by schema-migrator."),
  _source_hash STRING NOT NULL OPTIONS(description="Deterministic hash of the source row for change detection."),
  _source_system STRING OPTIONS(description="Identifier of the originating system.")
)
PARTITION BY business_date
CLUSTER BY order_id, customer_id;

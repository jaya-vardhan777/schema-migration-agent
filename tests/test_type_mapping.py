from __future__ import annotations

import pytest

from schema_migrator.dialects import get_renderer
from schema_migrator.models.schema import ColumnSchema


def col(name: str, source_type: str, **kwargs) -> ColumnSchema:
    return ColumnSchema(name=name, source_type=source_type, **kwargs)


@pytest.mark.parametrize(
    "dialect,source,expected_prefix",
    [
        # BigQuery
        ("bigquery", col("s", "VARCHAR2", length=100), "STRING"),
        ("bigquery", col("s", "TEXT"), "STRING"),
        ("bigquery", col("s", "TIMESTAMPTZ"), "TIMESTAMP"),
        ("bigquery", col("s", "TIMESTAMP WITH TIME ZONE"), "TIMESTAMP"),
        ("bigquery", col("s", "TIMESTAMP"), "DATETIME"),
        ("bigquery", col("s", "BYTEA"), "BYTES"),
        ("bigquery", col("s", "JSONB"), "JSON"),
        ("bigquery", col("s", "BOOLEAN"), "BOOL"),
        # ClickHouse
        ("clickhouse", col("s", "VARCHAR"), "String"),
        ("clickhouse", col("s", "BIGINT"), "Int64"),
        ("clickhouse", col("s", "TIMESTAMP WITH TIME ZONE"), "DateTime64"),
        ("clickhouse", col("s", "UUID"), "UUID"),
        # Snowflake
        ("snowflake", col("s", "VARCHAR2", length=200), "STRING"),
        ("snowflake", col("s", "TIMESTAMPTZ"), "TIMESTAMP_TZ"),
        ("snowflake", col("s", "TIMESTAMP"), "TIMESTAMP_NTZ"),
        ("snowflake", col("s", "JSONB"), "VARIANT"),
    ],
)
def test_direct_mappings(dialect: str, source: ColumnSchema, expected_prefix: str) -> None:
    renderer = get_renderer(dialect)
    mapped = renderer.map_column(source)
    assert mapped.resolved_by == "rule"
    assert mapped.target_type.startswith(expected_prefix), f"{mapped.target_type} does not start with {expected_prefix}"


@pytest.mark.parametrize(
    "precision,scale,dialect,expected",
    [
        (18, 0, "bigquery", "INT64"),
        (38, 0, "bigquery", "NUMERIC(38, 0)"),
        (20, 4, "bigquery", "NUMERIC(20, 4)"),
        (40, 4, "bigquery", "BIGNUMERIC(40, 4)"),
        (18, 0, "snowflake", "NUMBER(18, 0)"),
        (20, 4, "snowflake", "NUMBER(20, 4)"),
        (9, 0, "clickhouse", "Int32"),
        (18, 0, "clickhouse", "Int64"),
        (20, 4, "clickhouse", "Decimal(20, 4)"),
    ],
)
def test_number_precision_rules(precision: int, scale: int, dialect: str, expected: str) -> None:
    renderer = get_renderer(dialect)
    mapped = renderer.map_column(col("n", "NUMBER", precision=precision, scale=scale))
    assert mapped.target_type == expected


def test_unknown_type_passthrough() -> None:
    renderer = get_renderer("bigquery")
    mapped = renderer.map_column(col("weird", "SDO_GEOMETRY"))
    assert mapped.resolved_by == "passthrough"
    assert mapped.confidence < 1.0


def test_metadata_columns_present() -> None:
    for dialect in ("bigquery", "clickhouse", "snowflake"):
        renderer = get_renderer(dialect)
        meta = renderer.build_metadata_columns(existing_names=set())
        names = {c.name for c in meta}
        assert "_ingested_at" in names
        assert "_source_hash" in names


def test_metadata_collision_gets_suffix() -> None:
    renderer = get_renderer("bigquery")
    meta = renderer.build_metadata_columns(existing_names={"_ingested_at"})
    names = {c.name for c in meta}
    assert "_ingested_at_sys" in names

from __future__ import annotations

import sqlglot

from schema_migrator.dialects import get_renderer
from schema_migrator.models.schema import ColumnHints, ColumnSchema, TableSchema


def _sample_table() -> TableSchema:
    return TableSchema(
        name="orders",
        schema="sales",
        source_dialect="oracle",
        primary_key=["order_id"],
        columns=[
            ColumnSchema(name="order_id", source_type="NUMBER", precision=18, scale=0, nullable=False),
            ColumnSchema(
                name="business_date",
                source_type="DATE",
                nullable=False,
                hints=ColumnHints(is_business_date=True, is_partition_key=True),
            ),
            ColumnSchema(
                name="customer_id",
                source_type="NUMBER",
                precision=18,
                scale=0,
                hints=ColumnHints(is_cluster_key=True, cluster_order=1),
            ),
            ColumnSchema(name="amount", source_type="NUMBER", precision=20, scale=4),
            ColumnSchema(name="notes", source_type="CLOB"),
        ],
    )


def _map_and_meta(dialect: str) -> tuple[list, TableSchema]:
    renderer = get_renderer(dialect)
    table = _sample_table()
    mapped = [renderer.map_column(c) for c in table.columns]
    meta = renderer.build_metadata_columns(existing_names={c.name for c in table.columns})
    from schema_migrator.models.schema import MappedColumn

    for m in meta:
        mapped.append(MappedColumn(source=m, target_type=m.source_type, resolved_by="metadata"))
    table.columns = list(table.columns) + meta
    return mapped, table


def test_bigquery_ddl_has_partition_and_metadata() -> None:
    mapped, table = _map_and_meta("bigquery")
    ddl = get_renderer("bigquery").render_table(table, mapped)
    # business_date is DATE type → PARTITION BY col directly, no DATE() wrapper.
    assert "PARTITION BY business_date" in ddl
    assert "DATE(business_date)" not in ddl
    assert "CLUSTER BY customer_id" in ddl
    assert "_ingested_at" in ddl
    assert "_source_hash" in ddl
    # Must round-trip through sqlglot.
    sqlglot.parse_one(ddl, read="bigquery")


def test_clickhouse_ddl_uses_mergetree() -> None:
    mapped, table = _map_and_meta("clickhouse")
    ddl = get_renderer("clickhouse").render_table(table, mapped)
    assert "ENGINE = MergeTree()" in ddl
    assert "PARTITION BY toYYYYMM" in ddl
    assert "ORDER BY" in ddl
    sqlglot.parse_one(ddl, read="clickhouse")


def test_snowflake_ddl_has_cluster_by_and_no_partition() -> None:
    mapped, table = _map_and_meta("snowflake")
    ddl = get_renderer("snowflake").render_table(table, mapped)
    assert "CLUSTER BY" in ddl
    assert "PARTITION BY" not in ddl.upper()
    sqlglot.parse_one(ddl, read="snowflake")


def test_reserved_word_gets_quoted() -> None:
    renderer = get_renderer("bigquery")
    table = TableSchema(
        name="orders",
        columns=[
            ColumnSchema(name="order", source_type="INT"),  # reserved
            ColumnSchema(name="normal", source_type="INT"),
        ],
    )
    mapped = [renderer.map_column(c) for c in table.columns]
    ddl = renderer.render_table(table, mapped)
    assert "`order`" in ddl
    assert " normal " in ddl or "\n  normal " in ddl

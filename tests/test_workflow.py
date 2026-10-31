from __future__ import annotations

import pytest
import sqlglot

from schema_migrator.api import transpile


@pytest.mark.parametrize("dialect", ["bigquery", "clickhouse", "snowflake"])
def test_end_to_end_oracle(oracle_sql: str, dialect: str) -> None:
    result = transpile(oracle_sql, target_dialect=dialect)
    assert result.target_ddl, "DDL must be produced"
    assert result.validation is not None
    assert result.validation.passed, f"Validation failed: {result.validation.issues}"
    assert "_ingested_at" in result.target_ddl
    assert "_source_hash" in result.target_ddl
    sqlglot.parse_one(result.target_ddl, read=dialect)


@pytest.mark.parametrize("dialect", ["bigquery", "clickhouse", "snowflake"])
def test_end_to_end_yaml(yaml_schema: str, dialect: str) -> None:
    result = transpile(yaml_schema, target_dialect=dialect, source_format="yaml")
    assert result.validation is not None
    assert result.validation.passed
    if dialect == "bigquery":
        # signup_date is DATE type → PARTITION BY col directly, no DATE() wrapper.
        assert "PARTITION BY signup_date" in result.target_ddl
        assert "DATE(signup_date)" not in result.target_ddl
        assert "CLUSTER BY" in result.target_ddl
    if dialect == "clickhouse":
        assert "PARTITION BY toYYYYMM(signup_date)" in result.target_ddl
    if dialect == "snowflake":
        assert "CLUSTER BY (signup_date" in result.target_ddl


def test_postgres_maps_jsonb_to_json_or_variant(postgres_sql: str) -> None:
    for dialect, expected in [
        ("bigquery", "JSON"),
        ("snowflake", "VARIANT"),
        ("clickhouse", "JSON"),
    ]:
        result = transpile(postgres_sql, target_dialect=dialect)
        assert expected in result.target_ddl, f"{dialect} DDL missing {expected}"


def test_metrics_recorded(oracle_sql: str) -> None:
    result = transpile(oracle_sql, target_dialect="bigquery")
    assert result.metrics.duration_ms > 0
    # Deterministic path only — no LLM calls when fallback is disabled in conftest.
    assert result.metrics.llm_calls == 0
    assert "parser" in result.metrics.per_agent_ms
    assert "validator" in result.metrics.per_agent_ms

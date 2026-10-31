from __future__ import annotations

from schema_migrator.parsers import detect_format, parse_sql_ddl, parse_yaml_schema


def test_detect_format_sql(oracle_sql: str) -> None:
    assert detect_format(oracle_sql) == "sql"


def test_detect_format_yaml(yaml_schema: str) -> None:
    assert detect_format(yaml_schema) == "yaml"


def test_parse_oracle_sql(oracle_sql: str) -> None:
    table = parse_sql_ddl(oracle_sql)
    assert table is not None
    assert table.name.lower() == "orders"
    names = [c.name for c in table.columns]
    assert {"order_id", "customer_id", "business_date", "created_at"} <= set(names)

    order_id = table.column("order_id")
    assert order_id is not None
    # sqlglot normalizes Oracle NUMBER -> DECIMAL; either is acceptable for our purposes
    # since both hit the same rulebook path in every dialect.
    assert order_id.source_type in ("NUMBER", "DECIMAL")
    assert order_id.precision == 18
    assert order_id.scale == 0
    assert order_id.nullable is False

    created_at = table.column("created_at")
    assert created_at is not None
    # sqlglot normalizes "TIMESTAMP WITH TIME ZONE" -> "TIMESTAMPTZ"; both are in the rulebook.
    assert created_at.source_type in ("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE")

    biz = table.column("business_date")
    assert biz is not None and biz.hints.is_business_date is True


def test_parse_postgres_sql(postgres_sql: str) -> None:
    table = parse_sql_ddl(postgres_sql)
    assert table is not None
    payload = table.column("payload")
    assert payload is not None
    assert payload.source_type == "JSONB"


def test_parse_yaml_schema(yaml_schema: str) -> None:
    table = parse_yaml_schema(yaml_schema)
    assert table is not None
    assert table.name == "customers"
    assert table.primary_key == ["customer_id"]
    signup = table.column("signup_date")
    assert signup is not None
    assert signup.hints.is_partition_key
    assert signup.hints.is_business_date
    email = table.column("email")
    assert email is not None
    assert email.hints.is_cluster_key
    assert email.hints.cluster_order == 1


def test_parse_yaml_rejects_non_schema() -> None:
    assert parse_yaml_schema("- just: a list") is None


def test_parse_sql_returns_none_on_garbage() -> None:
    assert parse_sql_ddl("not sql at all !!!") is None

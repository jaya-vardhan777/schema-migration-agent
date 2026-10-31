"""YAML schema parser.

Accepted schema (permissive):

    table: sales_fact
    schema: warehouse            # optional
    source_dialect: oracle       # optional; default 'unknown'
    comment: "..."               # optional
    primary_key: [order_id]      # optional
    columns:
      - name: order_id
        type: NUMBER(18,0)
        nullable: false
        comment: "Business key"
      - name: business_date
        type: DATE
        partition_key: true
        business_date: true
      - name: customer_id
        type: NUMBER(18,0)
        cluster_key: true
        cluster_order: 1
"""
from __future__ import annotations

import re
from typing import Any

from ruamel.yaml import YAML

from schema_migrator.models.schema import (
    ColumnHints,
    ColumnSchema,
    SourceDialect,
    TableSchema,
)

_yaml = YAML(typ="safe")

_TYPE_PARAMS = re.compile(r"^\s*([A-Z_][A-Z0-9_ ]*?)\s*(?:\(([^)]+)\))?\s*$", re.IGNORECASE)


def _split_type(type_str: str) -> tuple[str, int | None, int | None, int | None]:
    """Split 'NUMBER(18,2)' into ('NUMBER', 18, 2, None)."""
    m = _TYPE_PARAMS.match(type_str.strip())
    if not m:
        return type_str.strip().upper(), None, None, None
    base = m.group(1).strip().upper()
    params_str = m.group(2)
    precision = scale = length = None
    if params_str:
        parts = [p.strip() for p in params_str.split(",") if p.strip()]
        nums: list[int] = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                continue
        if base in {"NUMBER", "NUMERIC", "DECIMAL"}:
            if nums:
                precision = nums[0]
            if len(nums) > 1:
                scale = nums[1]
        elif base in {"VARCHAR", "VARCHAR2", "NVARCHAR", "CHAR", "NCHAR", "STRING"}:
            if nums:
                length = nums[0]
        else:
            if nums:
                precision = nums[0]
            if len(nums) > 1:
                scale = nums[1]
    return base, precision, scale, length


def _normalize_source_dialect(v: Any) -> SourceDialect:
    if not v:
        return "unknown"
    v = str(v).lower()
    if v in ("oracle", "postgres", "postgresql", "mysql", "ansi"):
        return "postgres" if v == "postgresql" else v  # type: ignore[return-value]
    return "unknown"


def parse_yaml_schema(text: str) -> TableSchema | None:
    try:
        data: dict[str, Any] = _yaml.load(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "columns" not in data or "table" not in data and "name" not in data:
        return None

    table_name = data.get("table") or data.get("name")
    if not table_name:
        return None

    columns: list[ColumnSchema] = []
    for raw in data.get("columns", []):
        if not isinstance(raw, dict):
            continue
        col_name = raw.get("name")
        col_type = raw.get("type") or raw.get("source_type")
        if not col_name or not col_type:
            continue
        base, precision, scale, length = _split_type(str(col_type))
        hints = ColumnHints(
            is_partition_key=bool(raw.get("partition_key")),
            is_business_date=bool(raw.get("business_date")),
            is_cluster_key=bool(raw.get("cluster_key")),
            cluster_order=raw.get("cluster_order"),
            description=raw.get("comment"),
        )
        columns.append(
            ColumnSchema(
                name=col_name,
                source_type=base,
                precision=precision,
                scale=scale,
                length=length,
                nullable=bool(raw.get("nullable", True)),
                default=raw.get("default"),
                comment=raw.get("comment"),
                hints=hints,
            )
        )

    if not columns:
        return None

    pk = data.get("primary_key") or []
    if isinstance(pk, str):
        pk = [pk]

    return TableSchema(
        name=str(table_name),
        schema=data.get("schema"),
        columns=columns,
        primary_key=list(pk),
        source_dialect=_normalize_source_dialect(data.get("source_dialect")),
        comment=data.get("comment"),
    )

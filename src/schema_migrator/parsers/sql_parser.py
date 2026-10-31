"""Deterministic SQL DDL parser built on sqlglot.

Handles Oracle, PostgreSQL, MySQL, and generic ANSI CREATE TABLE statements.
Falls back to `None` when the input cannot be parsed — the caller can then
invoke the LLM parser fallback.
"""
from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from schema_migrator.models.schema import (
    ColumnHints,
    ColumnSchema,
    SourceDialect,
    TableSchema,
)

_PARTITION_HINT = re.compile(r"partition[_\s-]*key|business[_\s-]*date", re.IGNORECASE)
_CLUSTER_HINT = re.compile(r"cluster[_\s-]*key", re.IGNORECASE)
_BUSINESS_DATE_NAMES = (
    "business_date", "biz_date", "as_of_date", "event_date", "event_time",
    "created_at", "created_date", "load_date", "partition_date",
)


def _guess_dialect(sql: str) -> str:
    lowered = sql.lower()
    if "varchar2" in lowered or "number(" in lowered or "sysdate" in lowered:
        return "oracle"
    if "serial" in lowered or "bytea" in lowered or "jsonb" in lowered or "timestamptz" in lowered:
        return "postgres"
    return "ansi"


def _column_type_string(col_def: exp.ColumnDef) -> tuple[str, int | None, int | None, int | None]:
    """Return (base_type_name, precision, scale, length) for a sqlglot ColumnDef."""
    kind = col_def.args.get("kind")
    if kind is None:
        return "UNKNOWN", None, None, None
    # sqlglot represents type names via DataType.Type enum; text form is easier for our rulebooks.
    type_sql = kind.sql().upper()
    # Strip parameter list to get the base name.
    base = type_sql.split("(")[0].strip()
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    params = kind.args.get("expressions") or []
    numbers = []
    for p in params:
        try:
            numbers.append(int(p.name if hasattr(p, "name") else str(p)))
        except (TypeError, ValueError):
            continue
    if base in {"NUMBER", "NUMERIC", "DECIMAL"}:
        if len(numbers) >= 1:
            precision = numbers[0]
        if len(numbers) >= 2:
            scale = numbers[1]
    elif base in {"VARCHAR", "VARCHAR2", "NVARCHAR", "CHAR", "NCHAR", "STRING"}:
        if numbers:
            length = numbers[0]
    else:
        if len(numbers) >= 1:
            precision = numbers[0]
        if len(numbers) >= 2:
            scale = numbers[1]
    # Preserve full source form (e.g. "TIMESTAMP WITH TIME ZONE") when meaningful.
    canonical = type_sql if any(w in type_sql for w in ("WITH TIME ZONE", "WITHOUT TIME ZONE")) else base
    return canonical, precision, scale, length


def _extract_constraints(col_def: exp.ColumnDef) -> dict[str, Any]:
    out: dict[str, Any] = {"nullable": True, "default": None, "primary_key": False, "comment": None}
    for constraint in col_def.constraints or []:
        kind = constraint.args.get("kind")
        if isinstance(kind, exp.NotNullColumnConstraint):
            out["nullable"] = False
        elif isinstance(kind, exp.PrimaryKeyColumnConstraint):
            out["primary_key"] = True
            out["nullable"] = False
        elif isinstance(kind, exp.DefaultColumnConstraint):
            expr = kind.args.get("this")
            if expr is not None:
                out["default"] = expr.sql()
        elif isinstance(kind, exp.CommentColumnConstraint):
            expr = kind.args.get("this")
            if expr is not None:
                out["comment"] = expr.name if hasattr(expr, "name") else str(expr)
    return out


def _build_hints(name: str, comment: str | None) -> ColumnHints:
    hints = ColumnHints()
    haystack = " ".join(filter(None, [name.lower(), (comment or "").lower()]))
    if _PARTITION_HINT.search(haystack):
        hints.is_partition_key = True
    if any(hint in name.lower() for hint in _BUSINESS_DATE_NAMES):
        hints.is_business_date = True
    if _CLUSTER_HINT.search(haystack):
        hints.is_cluster_key = True
    if comment:
        hints.description = comment
    return hints


def parse_sql_ddl(sql: str, source_dialect: str | None = None) -> TableSchema | None:
    """Parse a CREATE TABLE statement into a TableSchema; return None on failure."""
    
    # If source_dialect is not provided, then trying to guess which dialect it is based on the SQL content.
    dialect = source_dialect or _guess_dialect(sql)
    
    # Parsing the SQL content using sqlglot and extracting the AST (Abstract Syntax Tree)
    try:
        parse_dialect = None if dialect == "ansi" else dialect
        parsed = sqlglot.parse_one(sql, read=parse_dialect)
    except Exception:
        return None

    # If it is not a CREATE statement or not a TABLE, then return None
    if not isinstance(parsed, exp.Create) or parsed.args.get("kind") != "TABLE":
        return None

    table_expr = parsed.this

    # Extracting the TABLE-NAME, COLUMN DEFINITIONS and TABLE CONSTRAINTS from the AST.
    if isinstance(table_expr, exp.Schema):
        table_name_expr = table_expr.this
        column_defs = [c for c in table_expr.expressions if isinstance(c, exp.ColumnDef)]
        table_constraints = [c for c in table_expr.expressions if not isinstance(c, exp.ColumnDef)]
    else:
        table_name_expr = table_expr
        column_defs = []
        table_constraints = []

    # Extracting the TABLE-NAME and SCHEMA-NAME from the AST.
    if isinstance(table_name_expr, exp.Table):
        table_name = table_name_expr.name
        schema_name = table_name_expr.args.get("db").name if table_name_expr.args.get("db") else None
    else:
        table_name = table_name_expr.name if hasattr(table_name_expr, "name") else str(table_name_expr)
        schema_name = None

    # For each column, trying to extract the constraints, expressions (like precision, scale, length) and hints
    columns: list[ColumnSchema] = []
    for col_def in column_defs:
        col_name = col_def.name

        # Extracting the precision, scale,length values from the column AST
        base_type, precision, scale, length = _column_type_string(col_def)

        # Extracting the constraints from the column AST like NULLABLE, PRIMARY KEY, DEFAULT and COMMENT
        meta = _extract_constraints(col_def)

        # From the column name and comment, trying to infer the hints like partition key, business date, cluster key
        hints = _build_hints(col_name, meta["comment"])
        
        # Appending the ColumnSchema object to the columns list
        columns.append(
            ColumnSchema(
                name=col_name,
                source_type=base_type,
                precision=precision,
                scale=scale,
                length=length,
                nullable=meta["nullable"],
                default=meta["default"],
                comment=meta["comment"],
                hints=hints,
            )
        )
    print("Columns:", columns)

    '''
    PRIMARY KEYS can be defined in 2 ways:
    1. In column definition (NOT NULL PK / PRIMARY KEY) or
    2. As a separate table constraint (CONSTRAINT pk PRIMARY KEY (col1, col2, ...))
    The following code handles both cases.

    Why overwriting is done?
    The CONSTRAINT mentioned at the END has more authoritativeness than the one defined in column definition.
    '''
    primary_key: list[str] = [c.name for c in columns if _column_is_pk(column_defs, c.name)]
    for constraint in table_constraints:
        if isinstance(constraint, exp.PrimaryKey):
            primary_key = [e.name for e in constraint.expressions]
            break
    
    # Extracting the TABLE COMMENT from the AST
    props = parsed.args.get("properties")
    table_comment = None
    if props is not None:
        for prop in props.expressions:
            if isinstance(prop, exp.SchemaCommentProperty):
                val = prop.args.get("this")
                if val is not None:
                    table_comment = val.name if hasattr(val, "name") else str(val)

    return TableSchema(
        name=table_name,
        schema=schema_name,
        columns=columns,
        primary_key=primary_key,
        source_dialect=_normalize_source_dialect(dialect),
        comment=table_comment,
    )


def _column_is_pk(col_defs: list[exp.ColumnDef], name: str) -> bool:
    for c in col_defs:
        if c.name == name:
            for constraint in c.constraints or []:
                if isinstance(constraint.args.get("kind"), exp.PrimaryKeyColumnConstraint):
                    return True
    return False


def _normalize_source_dialect(value: str) -> SourceDialect:
    v = value.lower()
    if v in ("oracle",):
        return "oracle"
    if v in ("postgres", "postgresql"):
        return "postgres"
    if v == "mysql":
        return "mysql"
    if v in ("ansi", ""):
        return "ansi"
    return "unknown"

"""ClickHouse (MergeTree family) DDL renderer."""
from __future__ import annotations

from schema_migrator.dialects.base import DialectRenderer
from schema_migrator.models.schema import MappedColumn, TableSchema


class ClickHouseRenderer(DialectRenderer):
    name = "clickhouse"

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def render_column(self, col: MappedColumn) -> str:
        # ClickHouse: nullability is expressed by wrapping the type in Nullable(...).
        target = col.target_type
        if col.source.nullable and not target.startswith("Nullable("):
            # Nullable(JSON) / Nullable(String) etc. — but not for LowCardinality wrappers.
            if not target.startswith(("Array(", "Nullable(", "LowCardinality(")):
                target = f"Nullable({target})"
        parts = [self.quote_ident(col.source.name), target]
        if col.source.default is not None:
            parts.append(f"DEFAULT {self._translate_default(col.source.default)}")
        if col.source.comment:
            escaped = col.source.comment.replace("'", "''")
            parts.append(f"COMMENT '{escaped}'")
        return " ".join(parts)

    def render_partition(self, table: TableSchema) -> str | None:
        parts = table.partition_columns
        if not parts:
            return None
        col = next((c for c in parts if c.hints.is_business_date), parts[0])
        norm = col.source_type.upper()
        col_ref = self.quote_ident(col.name)
        if "TIMESTAMP" in norm or "DATETIME" in norm:
            return f"PARTITION BY toYYYYMM({col_ref})"
        if norm == "DATE":
            return f"PARTITION BY toYYYYMM({col_ref})"
        return f"PARTITION BY {col_ref}"

    def render_cluster(self, table: TableSchema) -> str | None:
        # ClickHouse: ORDER BY is the primary sort key. Use cluster columns + partition column.
        clusters = table.cluster_columns
        if not clusters:
            clusters = table.partition_columns[:1]
        if not clusters and table.primary_key:
            clusters = [c for c in table.columns if c.name in table.primary_key]
        if not clusters:
            return None
        cols = ", ".join(self.quote_ident(c.name) for c in clusters)
        return f"ORDER BY ({cols})"

    def render_table(self, table: TableSchema, mapped: list[MappedColumn]) -> str:
        column_lines = [f"  {self.render_column(m)}" for m in mapped]
        body = ",\n".join(column_lines)
        parts = [f"CREATE TABLE IF NOT EXISTS {self.full_table_name(table)} (", body, ")"]
        parts.append("ENGINE = MergeTree()")
        partition = self.render_partition(table)
        if partition:
            parts.append(partition)
        cluster = self.render_cluster(table)
        if cluster:
            parts.append(cluster)
        else:
            parts.append("ORDER BY tuple()")
        if table.comment:
            escaped = table.comment.replace("'", "''")
            parts.append(f"COMMENT '{escaped}'")
        return "\n".join(parts) + ";"

    @staticmethod
    def _translate_default(value: str) -> str:
        upper = value.upper().strip().rstrip("()").strip()
        if upper in ("SYSDATE", "SYSTIMESTAMP", "CURRENT_TIMESTAMP", "NOW"):
            return "now64()"
        if upper == "CURRENT_DATE":
            return "today()"
        return value

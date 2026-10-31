"""Snowflake DDL renderer.

Snowflake auto-manages micro-partitions; there is no explicit PARTITION BY.
`CLUSTER BY (...)` is used to define the clustering key (which drives micro-partition
pruning). We put the business_date first, followed by any declared cluster keys.
"""
from __future__ import annotations

from schema_migrator.dialects.base import DialectRenderer
from schema_migrator.models.schema import MappedColumn, TableSchema


class SnowflakeRenderer(DialectRenderer):
    name = "snowflake"

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def render_column(self, col: MappedColumn) -> str:
        parts = [self.quote_ident(col.source.name), col.target_type]
        if not col.source.nullable:
            parts.append("NOT NULL")
        if col.source.default is not None:
            parts.append(f"DEFAULT {self._translate_default(col.source.default)}")
        if col.source.comment:
            escaped = col.source.comment.replace("'", "''")
            parts.append(f"COMMENT '{escaped}'")
        return " ".join(parts)

    def render_partition(self, table: TableSchema) -> str | None:
        # Snowflake has no explicit partition clause; partition candidates fold into CLUSTER BY.
        return None

    def render_cluster(self, table: TableSchema) -> str | None:
        keys: list[str] = []
        # Business date / partition column first (drives pruning).
        for c in table.partition_columns:
            if c.name not in keys:
                keys.append(c.name)
        for c in table.cluster_columns:
            if c.name not in keys:
                keys.append(c.name)
        if not keys:
            return None
        cols = ", ".join(self.quote_ident(k) for k in keys[:4])
        return f"CLUSTER BY ({cols})"

    def render_table(self, table: TableSchema, mapped: list[MappedColumn]) -> str:
        column_lines = [f"  {self.render_column(m)}" for m in mapped]
        body = ",\n".join(column_lines)
        parts = [f"CREATE TABLE IF NOT EXISTS {self.full_table_name(table)} (", body, ")"]
        cluster = self.render_cluster(table)
        if cluster:
            parts.append(cluster)
        if table.comment:
            escaped = table.comment.replace("'", "''")
            parts.append(f"COMMENT = '{escaped}'")
        return "\n".join(parts) + ";"

    @staticmethod
    def _translate_default(value: str) -> str:
        upper = value.upper().strip().rstrip("()").strip()
        if upper in ("SYSDATE", "SYSTIMESTAMP", "NOW"):
            return "CURRENT_TIMESTAMP()"
        return value

"""BigQuery DDL renderer."""
from __future__ import annotations

from schema_migrator.dialects.base import DialectRenderer
from schema_migrator.models.schema import MappedColumn, TableSchema


class BigQueryRenderer(DialectRenderer):
    name = "bigquery"

    def _quote(self, name: str) -> str:
        return f"`{name}`"

    def render_column(self, col: MappedColumn) -> str:
        parts = [self.quote_ident(col.source.name), col.target_type]
        if col.source.default is not None:
            parts.append(f"DEFAULT {self._translate_default(col.source.default)}")
        if not col.source.nullable:
            parts.append("NOT NULL")
        if col.source.comment:
            escaped = col.source.comment.replace('"', '\\"')
            parts.append(f'OPTIONS(description="{escaped}")')
        return " ".join(parts)

    def render_partition(self, table: TableSchema) -> str | None:
        parts = table.partition_columns
        if not parts:
            return None
        # BigQuery supports one partition column. Prefer business_date if flagged.
        col = next((c for c in parts if c.hints.is_business_date), parts[0])
        norm = col.source_type.upper()
        col_ref = self.quote_ident(col.name)
        # TIMESTAMP / DATETIME columns: DATE() extracts the date component for partitioning.
        # Pure DATE columns: partition directly — DATE() on a DATE column is a BigQuery error.
        if any(kw in norm for kw in ("TIMESTAMP", "DATETIME")):
            return f"PARTITION BY DATE({col_ref})"
        return f"PARTITION BY {col_ref}"

    def render_cluster(self, table: TableSchema) -> str | None:
        clusters = table.cluster_columns
        # If the user has more than one partition candidate, use the extras as cluster.
        if not clusters:
            partitions = table.partition_columns
            if len(partitions) > 1:
                clusters = partitions[1:]
        if not clusters:
            return None
        cols = ", ".join(self.quote_ident(c.name) for c in clusters[:4])  # BQ limit: 4
        return f"CLUSTER BY {cols}"

    def render_table(self, table: TableSchema, mapped: list[MappedColumn]) -> str:
        column_lines = [f"  {self.render_column(m)}" for m in mapped]
        body = ",\n".join(column_lines)
        parts = [f"CREATE TABLE IF NOT EXISTS {self.full_table_name(table)} (", body, ")"]
        partition = self.render_partition(table)
        if partition:
            parts.append(partition)
        cluster = self.render_cluster(table)
        if cluster:
            parts.append(cluster)
        if table.comment:
            escaped = table.comment.replace('"', '\\"')
            parts.append(f'OPTIONS(description="{escaped}")')
        return "\n".join(parts) + ";"

    @staticmethod
    def _translate_default(value: str) -> str:
        upper = value.upper().strip().rstrip("()").strip()
        if upper in ("SYSDATE", "SYSTIMESTAMP", "CURRENT_TIMESTAMP", "NOW", "CURRENT_DATE"):
            return "CURRENT_TIMESTAMP()"
        return value

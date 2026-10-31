# Adding a new target dialect

Suppose you want to add Redshift. Four steps.

## 1. Rulebook

`src/schema_migrator/rules/redshift_types.yaml`:

```yaml
mappings:
  - source: [VARCHAR, VARCHAR2, NVARCHAR, TEXT, CHAR, CLOB]
    target: "VARCHAR(65535)"
  - source: NUMBER
    rules:
      - when: "scale == 0 and precision is not None and precision <= 18"
        target: BIGINT
      - when: "precision is not None"
        target: "NUMERIC({precision}, {scale_or_0})"
      - when: "true"
        target: "NUMERIC(38, 0)"
  # ...

metadata_columns:
  - name: _ingested_at
    type: TIMESTAMPTZ
    nullable: false
    default: "SYSDATE"
  - name: _source_hash
    type: VARCHAR(64)
    nullable: false

reserved_words: [SELECT, FROM, ...]
```

## 2. Renderer

`src/schema_migrator/dialects/redshift.py`:

```python
from schema_migrator.dialects.base import DialectRenderer
from schema_migrator.models.schema import MappedColumn, TableSchema


class RedshiftRenderer(DialectRenderer):
    name = "redshift"

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def render_column(self, col: MappedColumn) -> str:
        parts = [self.quote_ident(col.source.name), col.target_type]
        if not col.source.nullable:
            parts.append("NOT NULL")
        return " ".join(parts)

    def render_partition(self, table: TableSchema) -> str | None:
        return None  # Redshift has no PARTITION BY; distribution key instead

    def render_cluster(self, table: TableSchema) -> str | None:
        keys = table.cluster_columns or table.partition_columns
        if not keys:
            return None
        cols = ", ".join(self.quote_ident(c.name) for c in keys)
        return f"SORTKEY ({cols})"

    def render_table(self, table: TableSchema, mapped: list[MappedColumn]) -> str:
        cols = ",\n".join(f"  {self.render_column(m)}" for m in mapped)
        parts = [f"CREATE TABLE IF NOT EXISTS {self.full_table_name(table)} (", cols, ")"]
        sort = self.render_cluster(table)
        if sort:
            parts.append(sort)
        return "\n".join(parts) + ";"
```

## 3. Register

`src/schema_migrator/dialects/__init__.py`:

```python
from schema_migrator.dialects.redshift import RedshiftRenderer
registry.register(RedshiftRenderer)
```

Update the `TargetDialect` Literal in `src/schema_migrator/models/schema.py`
to include `"redshift"`.

## 4. Tests

Add fixtures and cases in `tests/test_dialects.py` and `tests/test_workflow.py`.
The workflow test only needs a new parametrize value; every existing agent
just works because the renderer/rulebook are the only dialect-specific parts.

That's it — the CLI, MCP server, and library all pick up the new target
through the registry.

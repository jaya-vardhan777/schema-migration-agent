from schema_migrator.dialects.base import DialectRenderer, get_renderer, registry
from schema_migrator.dialects.bigquery import BigQueryRenderer
from schema_migrator.dialects.clickhouse import ClickHouseRenderer
from schema_migrator.dialects.snowflake import SnowflakeRenderer

# Register on import so `get_renderer("bigquery")` etc. work.
registry.register(BigQueryRenderer)
registry.register(ClickHouseRenderer)
registry.register(SnowflakeRenderer)

__all__ = [
    "DialectRenderer",
    "BigQueryRenderer",
    "ClickHouseRenderer",
    "SnowflakeRenderer",
    "get_renderer",
]

"""Core domain models used across parsers, agents, and renderers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TargetDialect = Literal["bigquery", "clickhouse", "snowflake"]
SourceDialect = Literal["oracle", "postgres", "postgresql", "mysql", "ansi", "unknown"]
InputFormat = Literal["sql", "yaml", "auto"]


class ColumnHints(BaseModel):
    """Extra metadata that drives partition/cluster/audit decisions."""

    model_config = ConfigDict(extra="forbid")

    is_partition_key: bool = False
    is_business_date: bool = False
    is_cluster_key: bool = False
    cluster_order: int | None = None
    description: str | None = None


class ColumnSchema(BaseModel):
    """A single column parsed from source DDL / YAML."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source_type: str
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    nullable: bool = True
    default: str | None = None
    comment: str | None = None
    hints: ColumnHints = Field(default_factory=ColumnHints)

    @property
    def normalized_type(self) -> str:
        """Return source_type upper-cased and stripped for rule lookup."""
        return self.source_type.strip().upper()


class MappedColumn(BaseModel):
    """A ColumnSchema after type mapping to a target dialect."""

    model_config = ConfigDict(extra="forbid")

    source: ColumnSchema
    target_type: str
    notes: list[str] = Field(default_factory=list)
    resolved_by: Literal["rule", "llm", "passthrough", "metadata"] = "rule"
    confidence: float = 1.0


class TableSchema(BaseModel):
    """A full table description ready for rendering."""

    model_config = ConfigDict(extra="forbid")

    name: str
    schema_: str | None = Field(default=None, alias="schema")
    columns: list[ColumnSchema]
    primary_key: list[str] = Field(default_factory=list)
    source_dialect: SourceDialect = "unknown"
    comment: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    def column(self, name: str) -> ColumnSchema | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    @property
    def partition_columns(self) -> list[ColumnSchema]:
        return [c for c in self.columns if c.hints.is_partition_key or c.hints.is_business_date]

    @property
    def cluster_columns(self) -> list[ColumnSchema]:
        cols = [c for c in self.columns if c.hints.is_cluster_key]
        return sorted(cols, key=lambda c: (c.hints.cluster_order is None, c.hints.cluster_order or 0))


class Analysis(BaseModel):
    """Output of the analyzer agent."""

    model_config = ConfigDict(extra="forbid")

    partition_column: str | None = None
    cluster_columns: list[str] = Field(default_factory=list)
    business_date_column: str | None = None
    warnings: list[str] = Field(default_factory=list)
    inferred_by_llm: bool = False


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    retryable: bool = False


class RunMetrics(BaseModel):
    """Per-run usage/timing metrics captured by callbacks."""

    model_config = ConfigDict(extra="forbid")

    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    per_agent_ms: dict[str, float] = Field(default_factory=dict)


class TranspileResult(BaseModel):
    """Public return type of `transpile()`."""

    model_config = ConfigDict(extra="forbid")

    target_ddl: str
    target_dialect: TargetDialect
    warnings: list[str] = Field(default_factory=list)
    parsed_schema: TableSchema | None = None
    analysis: Analysis | None = None
    validation: ValidationReport | None = None
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    trace_id: str

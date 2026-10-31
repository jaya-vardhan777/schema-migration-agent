"""LangGraph state object shared across all nodes in the workflow."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schema_migrator.models.schema import (
    Analysis,
    InputFormat,
    MappedColumn,
    RunMetrics,
    TableSchema,
    TargetDialect,
    ValidationReport,
)


class AgentMessage(BaseModel):
    """Trace entry appended by each agent."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    event: str
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Full workflow state — every node receives and returns a partial of this."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # Inputs
    raw_input: str
    input_format: InputFormat = "auto"
    target_dialect: TargetDialect
    trace_id: str

    # Parser output
    parsed_schema: TableSchema | None = None

    # Analyzer output
    analysis: Analysis | None = None

    # Type mapper output
    mapped_columns: list[MappedColumn] = Field(default_factory=list)

    # DDL generator output
    generated_ddl: str | None = None

    # Validator output
    validation: ValidationReport | None = None

    # Book-keeping
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    retry_count: int = 0
    options: dict[str, Any] = Field(default_factory=dict)

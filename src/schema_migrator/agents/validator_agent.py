"""Validator — parse-checks the generated DDL and asserts semantic requirements."""
from __future__ import annotations

from typing import Any

import sqlglot

from schema_migrator.models.schema import ValidationReport
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.callbacks import log_agent

_DIALECT_TO_SQLGLOT = {"bigquery": "bigquery", "clickhouse": "clickhouse", "snowflake": "snowflake"}


def validator_node(state: AgentState) -> dict[str, Any]:
    with log_agent("validator", state.trace_id, state.metrics, dialect=state.target_dialect):
        issues: list[str] = []
        retryable = False

        ddl = state.generated_ddl
        if not ddl:
            return {
                "validation": ValidationReport(passed=False, issues=["No DDL was generated."], retryable=False)
            }

        # 1) Syntactic: parse via sqlglot against the target dialect.
        try:
            sqlglot.parse_one(ddl, read=_DIALECT_TO_SQLGLOT[state.target_dialect])
        except Exception as exc:
            issues.append(f"sqlglot parse failed: {exc}")
            retryable = True

        # 2) Semantic checks.
        if state.parsed_schema is not None:
            names = {c.name for c in state.parsed_schema.columns}
            if not any(n.startswith("_ingested_at") for n in names):
                issues.append("Missing mandatory metadata column '_ingested_at'.")
            if not any(n.startswith("_source_hash") for n in names):
                issues.append("Missing mandatory metadata column '_source_hash'.")

            has_partitionable = any(
                c.hints.is_partition_key or c.hints.is_business_date for c in state.parsed_schema.columns
            )
            if state.target_dialect in ("bigquery", "clickhouse") and has_partitionable:
                if "PARTITION BY" not in ddl.upper():
                    issues.append("Partition candidate present but no PARTITION BY clause was emitted.")
                    retryable = True
            if state.target_dialect == "snowflake" and has_partitionable and "CLUSTER BY" not in ddl.upper():
                issues.append("Partition candidate present but no CLUSTER BY clause was emitted.")
                retryable = True

        passed = len(issues) == 0
        report = ValidationReport(passed=passed, issues=issues, retryable=retryable and not passed)

        return {
            "validation": report,
            "messages": state.messages + [
                AgentMessage(
                    agent="validator",
                    event="validated",
                    detail=f"passed={passed} issues={len(issues)}",
                    metadata={"retryable": report.retryable},
                )
            ],
        }

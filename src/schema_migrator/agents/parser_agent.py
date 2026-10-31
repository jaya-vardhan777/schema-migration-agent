"""Parser agent — detects input format and parses to TableSchema.

Deterministic path uses sqlglot / ruamel.yaml. If both fail and an LLM is
available, an LLM extraction fallback is invoked.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from schema_migrator.llm.factory import try_get_llm
from schema_migrator.models.schema import TableSchema
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.callbacks import UsageCallbackHandler, log_agent
from schema_migrator.parsers import detect_format, parse_sql_ddl, parse_yaml_schema

_LLM_SYSTEM = """You extract database table schemas from arbitrary text.
Return ONLY valid JSON that matches this exact shape:

{
  "name": "<table name>",
  "schema": "<schema/database name or null>",
  "source_dialect": "oracle|postgres|mysql|ansi|unknown",
  "primary_key": ["<col>", ...],
  "comment": "<table comment or null>",
  "columns": [
    {
      "name": "<col>",
      "source_type": "<UPPERCASE type incl. WITH TIME ZONE if applicable>",
      "precision": <int|null>,
      "scale": <int|null>,
      "length": <int|null>,
      "nullable": <bool>,
      "default": "<string|null>",
      "comment": "<string|null>",
      "is_partition_key": <bool>,
      "is_business_date": <bool>,
      "is_cluster_key": <bool>
    }
  ]
}

Do not include any prose. If a field is unknown, use null / false.
"""


def parser_node(state: AgentState) -> dict[str, Any]:
    with log_agent("parser", state.trace_id, state.metrics, target=state.target_dialect):
        fmt = state.input_format if state.input_format in ("sql", "yaml") else detect_format(state.raw_input)

        parsed: TableSchema | None = None
        if fmt == "sql":
            parsed = parse_sql_ddl(state.raw_input)
        else:
            parsed = parse_yaml_schema(state.raw_input)

        used_llm = False
        if parsed is None:
            parsed = _llm_extract(state, fmt)
            used_llm = parsed is not None

        if parsed is None:
            return {
                "errors": state.errors + [f"Could not parse input as {fmt.upper()}."],
                "messages": state.messages + [
                    AgentMessage(agent="parser", event="parse_failed", detail=f"format={fmt}")
                ],
            }
        print("Parsed: ", parsed)
        return {
            "parsed_schema": parsed,
            "input_format": fmt,
            "messages": state.messages + [
                AgentMessage(
                    agent="parser",
                    event="parsed",
                    detail=f"{parsed.name} ({len(parsed.columns)} cols)",
                    metadata={"format": fmt, "used_llm": used_llm, "source_dialect": parsed.source_dialect},
                )
            ],
        }


def _llm_extract(state: AgentState, fmt: str) -> TableSchema | None:
    llm = try_get_llm("parser")
    if llm is None:
        return None
    callback = UsageCallbackHandler(state.metrics, state.trace_id)
    prompt = [
        SystemMessage(content=_LLM_SYSTEM),
        HumanMessage(content=f"Format hint: {fmt}\n\nInput:\n{state.raw_input}"),
    ]
    try:
        response = llm.invoke(prompt, config={"callbacks": [callback]})
        payload = response.content if isinstance(response.content, str) else str(response.content)
        data = _extract_json(payload)
        if not data:
            return None
    except Exception:
        return None
    return _table_from_json(data)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        # Strip fenced blocks.
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip().rstrip("`")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Attempt to find the outermost JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _table_from_json(data: dict[str, Any]) -> TableSchema | None:
    from schema_migrator.models.schema import ColumnHints, ColumnSchema

    try:
        cols = [
            ColumnSchema(
                name=c["name"],
                source_type=str(c.get("source_type", "STRING")).upper(),
                precision=c.get("precision"),
                scale=c.get("scale"),
                length=c.get("length"),
                nullable=bool(c.get("nullable", True)),
                default=c.get("default"),
                comment=c.get("comment"),
                hints=ColumnHints(
                    is_partition_key=bool(c.get("is_partition_key")),
                    is_business_date=bool(c.get("is_business_date")),
                    is_cluster_key=bool(c.get("is_cluster_key")),
                    description=c.get("comment"),
                ),
            )
            for c in data.get("columns", [])
        ]
        if not cols:
            return None
        return TableSchema(
            name=data["name"],
            schema=data.get("schema"),
            columns=cols,
            primary_key=data.get("primary_key") or [],
            source_dialect=data.get("source_dialect") or "unknown",
            comment=data.get("comment"),
        )
    except (KeyError, TypeError):
        return None

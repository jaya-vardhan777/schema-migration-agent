"""Analyzer agent — detect partition / cluster / business_date candidates.

Rule-based first: explicit hints from parsing + name patterns. LLM only
runs when nothing was flagged and fallback is enabled.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from schema_migrator.config import get_settings
from schema_migrator.llm.factory import try_get_llm
from schema_migrator.models.schema import Analysis, ColumnHints
from schema_migrator.models.state import AgentMessage, AgentState
from schema_migrator.observability.callbacks import UsageCallbackHandler, log_agent

_DATE_KEYWORDS = ("date", "_dt", "_ts", "time", "created", "updated", "as_of", "event", "load")
# Used for cluster key inference. Matched as word-boundary prefixes or exact _id suffix
# to avoid false positives like "order_amount" matching "order".
_ID_KEYWORDS = ("customer", "product", "account", "region", "country", "tenant")

_LLM_SYSTEM = """You are a data warehouse architect. Given a list of columns from a source
table, propose:
  - one column suitable as partition/business_date column (must be DATE/TIMESTAMP-like)
  - up to 3 columns suitable as clustering keys (high-cardinality, frequently filtered)

Return JSON only:
{"partition_column": "<name or null>", "cluster_columns": ["<name>", ...], "rationale": "<short>"}
"""


def analyzer_node(state: AgentState) -> dict[str, Any]:
    with log_agent("analyzer", state.trace_id, state.metrics):
        if state.parsed_schema is None:
            return {"errors": state.errors + ["analyzer: no parsed schema"]}

        table = state.parsed_schema

        partition_col: str | None = None
        cluster_cols: list[str] = []
        business_date_col: str | None = None
        warnings: list[str] = []
        used_llm = False

        # 1) Honor explicit hints from parsing.
        for c in table.columns:
            if c.hints.is_partition_key and partition_col is None:
                partition_col = c.name
            if c.hints.is_business_date:
                business_date_col = c.name
                if partition_col is None:
                    partition_col = c.name
            if c.hints.is_cluster_key:
                cluster_cols.append(c.name)

        # 2) Rule-based inference for business_date if none flagged.
        if partition_col is None:
            for c in table.columns:
                lower = c.name.lower()
                type_upper = c.source_type.upper()
                looks_dateish = any(k in lower for k in _DATE_KEYWORDS)
                type_dateish = any(k in type_upper for k in ("DATE", "TIMESTAMP", "DATETIME"))
                if looks_dateish and type_dateish:
                    partition_col = c.name
                    business_date_col = business_date_col or c.name
                    break

        # 3) Rule-based cluster suggestions if none flagged.
        if not cluster_cols:
            candidates = []
            for c in table.columns:
                if c.name == partition_col:
                    continue
                lower = c.name.lower()
                # Accept columns ending in _id (order_id, customer_id, product_id ...)
                # or starting with a known high-cardinality dimension keyword followed by _.
                is_id_col = lower.endswith("_id")
                is_dim_col = any(
                    lower == k or lower.startswith(k + "_")
                    for k in _ID_KEYWORDS
                )
                if is_id_col or is_dim_col:
                    candidates.append(c.name)
            cluster_cols = candidates[:3]

        # 4) Optional LLM assist when we still have no partition column.
        settings = get_settings()
        if partition_col is None and settings.enable_llm_fallback:
            suggestion = _llm_suggest(state)
            if suggestion:
                partition_col = suggestion.get("partition_column") or partition_col
                cluster_cols = suggestion.get("cluster_columns") or cluster_cols
                used_llm = True
                if suggestion.get("rationale"):
                    warnings.append(f"LLM inferred: {suggestion['rationale']}")

        # Propagate inferred hints back onto the parsed schema so downstream renderers see them.
        updated_schema = table.model_copy(deep=True)
        for c in updated_schema.columns:
            if c.name == partition_col:
                c.hints = c.hints.model_copy(update={"is_partition_key": True})
            if c.name == business_date_col:
                c.hints = c.hints.model_copy(update={"is_business_date": True})
            if c.name in cluster_cols:
                c.hints = c.hints.model_copy(update={"is_cluster_key": True})

        analysis = Analysis(
            partition_column=partition_col,
            cluster_columns=cluster_cols,
            business_date_column=business_date_col,
            warnings=warnings,
            inferred_by_llm=used_llm,
        )

        if partition_col is None:
            warnings.append(
                "No partition/business_date column identified. Target DDL will omit partitioning."
            )

        return {
            "parsed_schema": updated_schema,
            "analysis": analysis,
            "warnings": state.warnings + warnings,
            "messages": state.messages + [
                AgentMessage(
                    agent="analyzer",
                    event="analyzed",
                    detail=f"partition={partition_col} cluster={cluster_cols}",
                    metadata={"used_llm": used_llm},
                )
            ],
        }


def _llm_suggest(state: AgentState) -> dict[str, Any] | None:
    llm = try_get_llm("analyzer")
    if llm is None or state.parsed_schema is None:
        return None
    callback = UsageCallbackHandler(state.metrics, state.trace_id)
    cols_summary = "\n".join(
        f"- {c.name}: {c.source_type} (nullable={c.nullable}, comment={c.comment!r})"
        for c in state.parsed_schema.columns
    )
    prompt = [
        SystemMessage(content=_LLM_SYSTEM),
        HumanMessage(
            content=f"Table: {state.parsed_schema.name}\nTarget dialect: {state.target_dialect}\nColumns:\n{cols_summary}"
        ),
    ]
    try:
        response = llm.invoke(prompt, config={"callbacks": [callback]})
        text = response.content if isinstance(response.content, str) else str(response.content)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(text[start : end + 1])
    except Exception:
        return None

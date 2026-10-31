"""MCP stdio server exposing the transpiler to Antigravity, Claude Code, and any MCP host.

Tools:
  - transpile_schema(source, target_dialect, source_format?) -> JSON result
  - validate_ddl(ddl, dialect) -> JSON {ok, error}
  - list_dialects() -> list[str]

Run:
    python -m schema_migrator.mcp_server
"""
from __future__ import annotations

import asyncio
import json

import sqlglot
from mcp.server import MCPServer

from schema_migrator.api import transpile
from schema_migrator.dialects import registry

server = MCPServer("schema-migrator")


@server.tool(
    name="transpile_schema",
    description=(
        "Transpile a source table description (ANSI SQL CREATE TABLE or YAML) "
        "into optimized DDL for BigQuery, ClickHouse, or Snowflake. "
        "Applies type mapping, partition/cluster clauses, and audit metadata columns."
    ),
)
async def transpile_schema(source: str, target_dialect: str, source_format: str = "auto") -> str:
    result = transpile(source=source, target_dialect=target_dialect, source_format=source_format)
    payload = json.loads(result.model_dump_json())
    return json.dumps(payload, indent=2)


@server.tool(
    name="validate_ddl",
    description="Parse-check DDL against a target dialect using sqlglot.",
)
async def validate_ddl(ddl: str, dialect: str) -> str:
    try:
        sqlglot.parse_one(ddl, read=dialect)
        body: dict = {"ok": True}
    except Exception as exc:
        body = {"ok": False, "error": str(exc)}
    return json.dumps(body)


@server.tool(
    name="list_dialects",
    description="List target dialects registered with the transpiler.",
)
async def list_dialects_tool() -> str:
    return json.dumps(registry.list())


async def _run() -> None:
    await server.run_stdio_async()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()

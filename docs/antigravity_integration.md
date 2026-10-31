# Antigravity integration

`schema-migrator` exposes three parallel surfaces:

| Surface     | Entry point                                    | Best for                                        |
|-------------|------------------------------------------------|-------------------------------------------------|
| MCP server  | `python -m schema_migrator.mcp_server`         | Antigravity / Claude Code discovers tools natively |
| CLI         | `schema-migrate transpile ...`                 | Terminal invocation, shell scripts, CI          |
| Library     | `from schema_migrator import transpile`        | Notebook / Python code inside the workspace     |

## Option A — MCP (recommended for Antigravity)

The bundled `.mcp.json` at the repo root registers the server:

```json
{
  "mcpServers": {
    "schema-migrator": {
      "command": "python",
      "args": ["-m", "schema_migrator.mcp_server"],
      "env": {"PYTHONUNBUFFERED": "1"}
    }
  }
}
```

Open the workspace in Antigravity — the three tools appear automatically:

- **`transpile_schema`** — runs the full agentic pipeline; returns the full
  JSON `TranspileResult` (DDL + warnings + validation + metrics + trace_id).
- **`validate_ddl`** — parse-check any DDL against a target dialect.
- **`list_dialects`** — capability discovery.

To use a different Python (e.g. a project venv), edit the `command` field.
For a global install, `pip install schema-migrator` and use
`command: "schema-migrate-mcp"` after adding a script entry to
`pyproject.toml`.

## Option B — CLI

Antigravity's terminal / shell tool can invoke:

```bash
schema-migrate transpile --source path/to/oracle.sql --target bigquery --out /tmp/out.sql
schema-migrate transpile --source ./schema.yaml --target snowflake --json
schema-migrate validate --ddl /tmp/out.sql --dialect bigquery
```

`--json` emits the full result as JSON so a wrapping agent can parse the
DDL + warnings + metrics.

## Option C — Library

Inside a workspace notebook:

```python
from schema_migrator import transpile

ddl = open("orders.sql").read()
result = transpile(ddl, target_dialect="bigquery")
print(result.target_ddl)
print("warnings:", result.warnings)
print("trace:", result.trace_id, "cost_usd:", result.metrics.cost_usd)
```

## Environment

For the LLM fallback to fire (unknown types, no partition hint), one of the
provider blocks in `.env` must be filled in. Everything else runs
deterministically without LLM access.

To send traces to LangSmith:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=schema-migrator
```

To expose Prometheus metrics on `:9090/metrics`:

```
METRICS_ENABLED=true
METRICS_PORT=9090
```

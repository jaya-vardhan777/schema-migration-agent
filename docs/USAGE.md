# Usage Guide — schema-migrator

This guide walks through every way to use the transpiler:

1. [Install](#1-install)
2. [Configure](#2-configure-env)
3. [Command-Line Interface](#3-command-line-interface)
4. [Python Library](#4-python-library)
5. [Antigravity (via MCP)](#5-antigravity-via-mcp)
6. [Claude Code / Cursor / any MCP host](#6-claude-code--cursor--any-mcp-host)
7. [Raw MCP over stdio](#7-raw-mcp-over-stdio)
8. [Docker / CI](#8-docker--ci)
9. [Observability — LangSmith, logs, Prometheus](#9-observability)
10. [Input formats reference](#10-input-formats-reference)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Install

Requires **Python 3.10+**.

```bash
# From a clone of the repo
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"        # dev extras include pytest, ruff, mypy
# or
pip install -e .               # runtime only
# or, for AWS Bedrock users:
pip install -e ".[bedrock]"
```

Verify:

```bash
schema-migrate dialects
# - bigquery
# - clickhouse
# - snowflake

pytest -q
# 47 passed
```

---

## 2. Configure (`.env`)

Copy the template:

```bash
cp .env.example .env
```

You only need to fill in the block for **one** LLM provider. Rules-based
transpilation works **without any LLM credentials** — the LLM is only used
when the rulebook can't decide (unknown source type or no partition hint).

### Minimum viable `.env` (deterministic only, no LLM)

```env
LLM_PROVIDER=anthropic
ENABLE_LLM_FALLBACK=false
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### With Anthropic (recommended)

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=schema-migrator
```

### With Azure OpenAI

```env
LLM_PROVIDER=azure
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-06-01
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

### With OpenAI or Bedrock

Set `LLM_PROVIDER=openai` (needs `OPENAI_API_KEY`) or
`LLM_PROVIDER=bedrock` (uses AWS default credential chain +
`AWS_REGION`, `BEDROCK_MODEL_ID`). Install the `[bedrock]` extra.

### Key knobs

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` / `openai` / `azure` / `bedrock` |
| `ENABLE_LLM_FALLBACK` | `true` | Allow LLM for unknown types & missing partition hints |
| `MAX_VALIDATION_RETRIES` | `2` | Retry `type_mapper → ddl_generator → validator` on retryable failures |
| `LOG_FORMAT` | `json` | `json` (production) or `console` (dev) |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `METRICS_ENABLED` | `false` | Start Prometheus HTTP server on `METRICS_PORT` |
| `LANGCHAIN_TRACING_V2` | `false` | Send traces to LangSmith |
| `LANGCHAIN_API_KEY` | — | LangSmith API key |

---

## 3. Command-Line Interface

### 3.1 Transpile a file to stdout

```bash
schema-migrate transpile --source tests/fixtures/oracle.sql --target bigquery
```

Output — a rich panel with the DDL, a warnings table (if any), and a
one-line metrics footer:

```
+------------------------------- bigquery DDL --------------------------------+
| CREATE TABLE IF NOT EXISTS sales.orders (                                   |
|   order_id INT64 NOT NULL,                                                  |
|   ...                                                                       |
| )                                                                           |
| PARTITION BY DATE(business_date)                                            |
| CLUSTER BY order_id, customer_id, order_amount;                             |
+-----------------------------------------------------------------------------+
trace_id=8dcfb4508df7  duration=22.9ms  llm_calls=0  tokens=0/0  cost=$0.0000
```

### 3.2 Write to a file

```bash
schema-migrate transpile \
  --source tests/fixtures/oracle.sql \
  --target bigquery \
  --out ./out/orders.bq.sql
```

### 3.3 YAML input

```bash
schema-migrate transpile \
  --source tests/fixtures/schema.yaml \
  --target snowflake
```

Format is auto-detected. Force it with `--source-format sql` or
`--source-format yaml`.

### 3.4 Machine-readable JSON output

```bash
schema-migrate transpile \
  --source tests/fixtures/oracle.sql \
  --target clickhouse \
  --json
```

Emits the full `TranspileResult` — DDL, warnings, validation report,
metrics, trace_id — as pretty-printed JSON. Ideal for piping into other
tools:

```bash
schema-migrate transpile --source foo.sql --target bigquery --json \
  | jq -r '.target_ddl' \
  > out.sql
```

### 3.5 Validate an existing DDL

```bash
schema-migrate validate --ddl ./out.sql --dialect bigquery
# OK — parses cleanly.
```

### 3.6 List targets

```bash
schema-migrate dialects
```

### 3.7 Batch a directory

Standard shell scripting works — the CLI is one process per file:

```bash
for f in schemas/*.sql; do
  schema-migrate transpile \
    --source "$f" \
    --target bigquery \
    --out "out/$(basename "${f%.sql}").bq.sql"
done
```

### 3.8 Exit codes

| Code | Meaning |
|---|---|
| 0 | Transpile OK, validation passed |
| 2 | Transpile ran but validation failed (DDL still printed) |
| 1 | Bad arguments / unreadable input / dialect not registered |

---

## 4. Python Library

### 4.1 One-liner

```python
from schema_migrator import transpile

with open("tests/fixtures/oracle.sql") as f:
    result = transpile(f.read(), target_dialect="bigquery")

print(result.target_ddl)
```

### 4.2 With options

```python
from schema_migrator import transpile, TranspileOptions

result = transpile(
    source=open("orders.sql").read(),
    target_dialect="snowflake",
    source_format="sql",           # "auto" | "sql" | "yaml"
    options=TranspileOptions(
        include_metrics=True,
        extra={"note": "run from ETL job 42"},
    ),
)
```

### 4.3 Inspect the full result

```python
print("trace_id:", result.trace_id)
print("dialect:", result.target_dialect)
print("passed:", result.validation.passed)
print("warnings:", result.warnings)

# Per-agent timing:
for agent, ms in result.metrics.per_agent_ms.items():
    print(f"  {agent:15} {ms:7.2f} ms")

# LLM usage this run:
m = result.metrics
print(f"llm_calls={m.llm_calls} tokens={m.tokens_in}/{m.tokens_out} "
      f"cost_usd={m.cost_usd:.6f}")
```

### 4.4 Work with the parsed schema

Use the library as a **parser only** by inspecting `result.parsed_schema`:

```python
result = transpile(sql, target_dialect="bigquery")
for col in result.parsed_schema.columns:
    print(col.name, col.source_type, col.hints.is_business_date)
```

### 4.5 Call the graph directly (advanced)

You can invoke the compiled LangGraph app yourself for streaming, checkpointing,
or custom state manipulation:

```python
from schema_migrator.graph import build_graph
from schema_migrator.models.state import AgentState

app = build_graph()
state = AgentState(
    raw_input=open("t.sql").read(),
    target_dialect="bigquery",
    trace_id="my-trace-123",
)
for step in app.stream(state):
    print(step)   # each node's partial state as it runs
```

---

## 5. Antigravity (via MCP)

This is the recommended way to use the transpiler inside Antigravity.
The transpiler runs as an **MCP stdio server**; Antigravity discovers
its three tools and can call them from any conversation.

### 5.1 Register the server

The repo already contains `.mcp.json`:

```json
{
  "mcpServers": {
    "schema-migrator": {
      "command": "python",
      "args": ["-m", "schema_migrator.mcp_server"],
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

Open the repo folder in Antigravity. The server appears in the MCP tools
panel with three tools:

| Tool | Purpose |
|---|---|
| `transpile_schema` | Run the full pipeline |
| `validate_ddl` | Parse-check a DDL against a dialect |
| `list_dialects` | Capability discovery |

### 5.2 Use it from an Antigravity conversation

Just ask:

> Transpile the file `schemas/orders.sql` to BigQuery and write the result to
> `bq/orders.sql`. Flag any columns that couldn't be mapped by rules.

Antigravity will:
1. Read the file (Read tool).
2. Call `transpile_schema` with `source=<file contents>` and `target_dialect="bigquery"`.
3. Write the returned `target_ddl` to `bq/orders.sql`.
4. Report the `warnings` and `metrics` fields.

### 5.3 Point Antigravity at a specific Python

If the venv isn't on `PATH`, edit `.mcp.json`:

```json
"command": "C:\\path\\to\\.venv\\Scripts\\python.exe",
"args": ["-m", "schema_migrator.mcp_server"]
```

On macOS/Linux:

```json
"command": "/path/to/.venv/bin/python",
"args": ["-m", "schema_migrator.mcp_server"]
```

### 5.4 Pass env vars to the server

Add them to the `env` block in `.mcp.json`:

```json
"env": {
  "PYTHONUNBUFFERED": "1",
  "LLM_PROVIDER": "anthropic",
  "ANTHROPIC_API_KEY": "sk-ant-...",
  "LANGCHAIN_TRACING_V2": "true",
  "LANGCHAIN_API_KEY": "lsv2_pt_..."
}
```

`.env` in the repo root is also loaded automatically by pydantic-settings.

### 5.5 What Antigravity sees in the JSON response

`transpile_schema` returns a JSON `TranspileResult`:

```json
{
  "target_ddl": "CREATE TABLE IF NOT EXISTS sales.orders (\n  ...\n);",
  "target_dialect": "bigquery",
  "warnings": ["order_amount: no rule matched 'SDO_GEOMETRY'; ..."],
  "validation": { "passed": true, "issues": [], "retryable": false },
  "analysis": {
      "partition_column": "business_date",
      "cluster_columns": ["order_id", "customer_id"],
      "business_date_column": "business_date",
      "inferred_by_llm": false,
      "warnings": []
  },
  "metrics": {
      "tokens_in": 0, "tokens_out": 0, "llm_calls": 0, "cost_usd": 0.0,
      "duration_ms": 22.89,
      "per_agent_ms": {"parser": 5.9, "analyzer": 0.18, "type_mapper": 9.49, "...": "..."}
  },
  "trace_id": "8dcfb4508df7"
}
```

The agent can read `warnings` to decide whether to escalate to a human,
inspect `analysis` to explain its choices, and use `trace_id` to link back
to the LangSmith trace.

---

## 6. Claude Code / Cursor / any MCP host

The `.mcp.json` in this repo works for **any** MCP host, not just Antigravity.

### Claude Code

```bash
# From the repo root:
claude
# The MCP server is auto-registered because .mcp.json exists.
# Confirm:
> /mcp
# schema-migrator: connected — 3 tools
```

Then:

> Use `transpile_schema` to convert `tests/fixtures/oracle.sql` to Snowflake.

### Cursor

Add to `~/.cursor/mcp.json` (or the project-local `.cursor/mcp.json`) the
same block as `.mcp.json`. Cursor auto-restarts the MCP server on config
change.

### Generic host

Any MCP-compliant client can spawn:

```
python -m schema_migrator.mcp_server
```

and communicate over stdio.

---

## 7. Raw MCP over stdio

For scripting and debugging, invoke the server directly:

```bash
python -m schema_migrator.mcp_server
```

Then send JSON-RPC over stdin. The MCP Python SDK ships an inspector:

```bash
mcp dev python -m schema_migrator.mcp_server
# Opens the MCP inspector in your browser.
```

Manual `initialize` + `tools/call`:

```
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_dialects","arguments":{}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"transpile_schema","arguments":{"source":"CREATE TABLE t (id NUMBER(18,0));","target_dialect":"bigquery"}}}
```

---

## 8. Docker / CI

### 8.1 Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["schema-migrate"]
```

Build & run:

```bash
docker build -t schema-migrator .
docker run --rm -v "$PWD:/w" -w /w schema-migrator \
    transpile --source /w/orders.sql --target bigquery
```

### 8.2 GitHub Actions

```yaml
name: transpile
on: [pull_request]
jobs:
  ddl:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest -q
      - name: Transpile schemas
        run: |
          for f in schemas/*.sql; do
            schema-migrate transpile \
              --source "$f" --target bigquery \
              --out "generated/$(basename "${f%.sql}").bq.sql"
          done
      - uses: actions/upload-artifact@v4
        with: { name: bq-ddls, path: generated/ }
```

---

## 9. Observability

### 9.1 Structured logs

Every run emits one JSON line per lifecycle event to **stderr**:

```json
{"trace_id":"8dcfb4508df7","target":"bigquery","event":"transpile.start","level":"info","timestamp":"..."}
{"agent":"parser","trace_id":"...","event":"agent.start","level":"info","timestamp":"..."}
{"agent":"parser","trace_id":"...","duration_ms":5.9,"event":"agent.end","level":"info","timestamp":"..."}
...
{"trace_id":"...","status":"ok","duration_ms":22.89,"tokens_in":0,"tokens_out":0,"cost_usd":0.0,"event":"transpile.done","level":"info","timestamp":"..."}
```

For dev, set `LOG_FORMAT=console` for colorized human output.

Ship logs to your aggregator with any container log driver — the JSON is
already newline-delimited.

### 9.2 LangSmith

Set:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=schema-migrator
```

Every run appears as a trace with each node as a span. LLM calls show
prompt, response, tokens, and latency inline.

### 9.3 Prometheus

Enable:

```env
METRICS_ENABLED=true
METRICS_PORT=9090
```

`http://localhost:9090/metrics` serves:

| Metric | Labels | Meaning |
|---|---|---|
| `schema_migrator_transpile_runs_total` | dialect, status | Count of runs |
| `schema_migrator_agent_duration_seconds` | agent | Histogram per node |
| `schema_migrator_llm_calls_total` | model | LLM invocations |
| `schema_migrator_llm_tokens_total` | model, direction | Tokens in/out |
| `schema_migrator_llm_cost_usd_total` | model | Estimated USD spend |
| `schema_migrator_validation_retries_total` | dialect | Retries triggered |

Scrape from Grafana or any Prometheus-compatible backend.

---

## 10. Input formats reference

### 10.1 SQL (auto-detected)

Anything sqlglot can parse as a `CREATE TABLE`. Oracle, PostgreSQL, MySQL,
and generic ANSI SQL work out of the box. Precision/scale on `NUMBER(p,s)`
is respected. `TIMESTAMP WITH TIME ZONE` and `TIMESTAMPTZ` are treated
identically. Reserved words are quoted per target.

Hints picked up **automatically** from column names:

| Pattern | Effect |
|---|---|
| `business_date`, `event_date`, `event_time`, `created_at`, `as_of_date`, `load_date`, `partition_date` | Treated as `business_date` (drives partition) |
| Name matches `.*_id$` or common ID stems (`customer`, `product`, ...) | Suggested as cluster candidate |
| Comment or name contains `partition_key` / `cluster_key` | Explicit hint honored |

### 10.2 YAML

```yaml
table: sales_fact              # required
schema: warehouse              # optional
source_dialect: oracle         # optional; oracle | postgres | mysql | ansi
comment: "..."
primary_key: [order_id]
columns:
  - name: order_id
    type: NUMBER(18,0)
    nullable: false
    comment: "Business key"

  - name: business_date
    type: DATE
    partition_key: true        # drives PARTITION BY / CLUSTER BY
    business_date: true

  - name: customer_id
    type: NUMBER(18,0)
    cluster_key: true          # explicit cluster keys
    cluster_order: 1           # optional ordering
```

### 10.3 What gets **automatically added**

Regardless of input, every generated table has three audit columns:

| Column | Type per dialect |
|---|---|
| `_ingested_at` | `TIMESTAMP` (BQ) / `DateTime64(6,'UTC')` (CH) / `TIMESTAMP_TZ` (SF) |
| `_source_hash` | `STRING` / `String` / `STRING` |
| `_source_system` | `STRING` / `Nullable(String)` / `STRING` |

If a user column already has one of these names, the injected column is
renamed with a `_sys` suffix (`_ingested_at_sys`, etc.).

---

## 11. Troubleshooting

### `Unknown target 'xyz'`

Run `schema-migrate dialects` for the registered list. To add a new
dialect, see `docs/extending_dialects.md`.

### `No credentials configured for provider 'anthropic'`

You called the LLM path but didn't set `ANTHROPIC_API_KEY`.  Either fill
in credentials or set `ENABLE_LLM_FALLBACK=false` (the pipeline will then
skip the LLM and pass unknown types through unchanged, with a warning).

### Validation fails with `PARTITION BY not emitted`

The analyzer couldn't find a partition column. Either:
- Add `partition_key: true` (YAML) to the intended column, **or**
- Rename the column to something matching the built-in patterns
  (`business_date`, `event_time`, `created_at`, ...), **or**
- Enable LLM fallback (`ENABLE_LLM_FALLBACK=true`) so the analyzer can
  infer one.

### `sqlglot parse failed`

The source DDL isn't valid ANSI/Oracle/Postgres/MySQL. If you enable the
LLM fallback, the parser agent will try to extract the schema via prompt.

### Antigravity doesn't see the MCP server

- Confirm the working directory is the repo root (contains `.mcp.json`).
- Check `python -m schema_migrator.mcp_server` runs manually without
  errors.
- Restart Antigravity after editing `.mcp.json`.
- Point `command` at an absolute Python path if `python` isn't on `PATH`.

### Cost / tokens are zero even though I set `LLM_PROVIDER`

That's the point of deterministic-first design — the LLM is only called
when the rulebook can't decide. Runs on the fixtures produce zero LLM
calls. To force LLM usage for testing, feed it an unknown source type
(e.g. `SDO_GEOMETRY`, `ARRAY<STRUCT<...>>`).

### Where do I see traces?

Structured logs are on stderr. LangSmith traces (if enabled) live at
[smith.langchain.com](https://smith.langchain.com) under the project name
in `LANGCHAIN_PROJECT`. Prometheus metrics (if enabled) live at
`http://localhost:$METRICS_PORT/metrics`.

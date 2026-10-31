# schema-migrator

Agentic cross-dialect schema transpiler. Parses ANSI SQL `CREATE TABLE` or a YAML
schema from an Oracle / PostgreSQL source and emits optimized DDL for
**BigQuery, ClickHouse, and Snowflake** with correct type mapping, automatic
partition / cluster clauses, and mandatory audit metadata columns.

Built on **LangChain + LangGraph**. Provider-agnostic LLM factory
(Anthropic / OpenAI / Azure / Bedrock). Ships with **LangSmith tracing**,
**structlog JSON logs**, and **Prometheus metrics**. Exposed as an
**MCP server**, a **Typer CLI**, and an importable Python library — so it
plugs cleanly into Antigravity, Claude Code, or any orchestrator.

---

## Quick start

```bash
pip install -e .[dev]
cp .env.example .env       # fill in LLM_PROVIDER + credentials (optional)

# CLI
schema-migrate transpile --source tests/fixtures/oracle.sql --target bigquery
schema-migrate transpile --source tests/fixtures/schema.yaml --target snowflake
schema-migrate dialects

# Library
python -c "from schema_migrator import transpile; print(transpile(open('tests/fixtures/oracle.sql').read(), 'bigquery').target_ddl)"

# MCP server (for Antigravity / Claude Code)
python -m schema_migrator.mcp_server

# Tests
pytest
```

---

## Architecture

```
              parser  ->  analyzer  ->  type_mapper  ->  meta_injector
                                                              |
                                                              v
              END  <-  validator  <-  ddl_generator  <------- +
                          |
                          +--(retryable failure, max N)--> type_mapper
```

- **parser** — sqlglot + ruamel.yaml (LLM fallback if both fail)
- **analyzer** — detects partition/business_date/cluster columns from parsing hints, name patterns, and (optionally) LLM suggestions
- **type_mapper** — rulebook-driven (`rules/*_types.yaml`), LLM fallback for unknown source types
- **meta_injector** — deterministic addition of `_ingested_at`, `_source_hash`, `_source_system`
- **ddl_generator** — dialect-specific renderers implementing `DialectRenderer`
- **validator** — sqlglot round-trip parse + semantic checks (partition emitted, metadata present)

Every node's entry/exit is logged with a per-run `trace_id`. LangSmith traces
show every node and every LLM call as spans. Prometheus metrics count runs,
retries, token usage, and cost when enabled.

---

## Extending

Add a new target dialect:

1. Drop a rulebook at `src/schema_migrator/rules/<dialect>_types.yaml`.
2. Implement `DialectRenderer` in `src/schema_migrator/dialects/<dialect>.py`.
3. Register the class in `src/schema_migrator/dialects/__init__.py`.
4. Add fixtures + tests.

See `docs/extending_dialects.md`.

---

## Antigravity integration

`.mcp.json` registers this repo as an MCP server. Antigravity (any MCP host)
discovers three tools:

- `transpile_schema(source, target_dialect, source_format?)` — full pipeline
- `validate_ddl(ddl, dialect)` — sqlglot round-trip check
- `list_dialects()` — capability discovery

Or invoke via terminal (`schema-migrate transpile ...`) or `from schema_migrator import transpile`.

See `docs/antigravity_integration.md`.

---

## Configuration

All runtime settings via env / `.env`. See `.env.example` for the full list.
Key knobs: `LLM_PROVIDER`, `ENABLE_LLM_FALLBACK`, `MAX_VALIDATION_RETRIES`,
`METRICS_ENABLED`, `LANGCHAIN_TRACING_V2`.

---

## Design notes

**Deterministic-first, LLM-as-fallback.** Type mapping and DDL rendering are
executed by code + YAML rules — they're fast, reproducible, and testable.
The LLM is only invoked for genuinely ambiguous cases (unknown source types,
no partition hint present). This keeps the prototype cheap, correct, and
auditable while still being an agentic system.

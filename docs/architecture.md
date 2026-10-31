# Architecture

## Goals

1. **Correctness** — type mapping must be data-warehouse-native (BigQuery
   `BIGNUMERIC` for oversized NUMBER, ClickHouse `MergeTree` engine,
   Snowflake `TIMESTAMP_TZ` / `NUMBER(p,s)`).
2. **Determinism** — the same input, same target must yield the same DDL byte-for-byte
   whenever the LLM fallback is not required.
3. **Extensibility** — a new target dialect must be a rulebook + one class.
4. **Observability** — every run has a `trace_id`; every node logs entry/exit;
   every LLM call records tokens + cost.
5. **Composability** — usable as library, CLI, and MCP tool with a single core.

## Flow

`schema_migrator.api.transpile()` builds an `AgentState`, then invokes the
compiled LangGraph app. Nodes execute in sequence; the validator's return
determines whether we terminate or loop back to `type_mapper` with a bumped
retry counter (bounded by `MAX_VALIDATION_RETRIES`).

State is a Pydantic model — every node returns a **partial dict** merged into
state, keeping the flow explicit and easy to reason about in LangSmith.

## Why deterministic-first?

Fully-LLM pipelines have three problems for this workload:

1. **Type-mapping drift.** LLMs occasionally suggest plausible but wrong
   targets (`FLOAT` when `NUMERIC(20,4)` is required, breaking downstream
   arithmetic).
2. **Cost.** A rulebook lookup is free; an LLM call is not.
3. **Auditability.** Data engineers want to see *why* a source type became
   what it did — a rulebook diff is easier to review than a prompt/trace pair.

The LLM is still critical when the rulebook cannot decide (unknown vendor
types, no partition hint at all) — but it's a fallback, not the primary path.

## Component boundaries

- `models/` — Pydantic data classes only. No side effects.
- `parsers/` — pure functions. Return `TableSchema | None`.
- `dialects/` — pure renderers. All I/O-free. Rulebook loaded via
  `importlib.resources` so the package works when zipped.
- `agents/` — thin LangGraph nodes. Each is one function
  `(state) -> partial state dict`. They orchestrate parsers/renderers/LLMs.
- `graph/` — `StateGraph` assembly. No business logic.
- `observability/` — logger, callbacks, Prometheus metrics.
- `llm/factory.py` — provider selection. Cached instances.
- `api.py` / `cli.py` / `mcp_server.py` — three thin entry points over the
  same core.

## Retry loop

If the validator finds a **retryable** issue (missing partition clause, sqlglot
parse error), the router node bumps `retry_count` and reruns
`type_mapper -> meta_injector -> ddl_generator -> validator`. The
`analyzer` output is preserved, so retries produce a different render
without re-guessing hints. Non-retryable issues (e.g. missing metadata
columns after injection) short-circuit to failure.

## Observability wiring

`observability.callbacks.UsageCallbackHandler` is attached per-LLM-call via
`config={"callbacks": [callback]}` inside each agent that uses an LLM. It:

- times each call,
- extracts provider-shaped token usage (Anthropic vs. OpenAI vs. Azure),
- estimates cost from a small `_PRICING` table,
- writes a `llm.call` JSON log line,
- increments Prometheus counters,
- accumulates into the run-level `RunMetrics`.

`observability.callbacks.log_agent()` is a `contextmanager` used by every
node; it records agent duration into `RunMetrics.per_agent_ms` and the
Prometheus histogram.

LangSmith tracing kicks in automatically when `LANGCHAIN_TRACING_V2=true` and
`LANGCHAIN_API_KEY` is present — every node and LLM call appears as a span.

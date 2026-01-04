# HTTP Server Reference

This guide explains how the FastAPI-based HTTP transport in `truenas_mcp_server/http_server.py` is structured, how it authenticates requests, and how to customize the tool-gating behavior to match your deployment.

## Lifecycle Overview

1. **Startup** – `lifespan()` configures logging, instantiates `TrueNASMCPServer`, and discovers every registered tool.
2. **Registry + Gating** – `TrueNASToolRegistry` snapshots the tool metadata while `ToolGateController` wires up the `TaskType`, `Resource`, and `Security` filters defined in [http_api/tool_gating.py](../truenas_mcp_server/http_api/tool_gating.py).
3. **Intent Classification** – `KeywordIntentClassifier` (from `http_api/intent_classifier.py`) loads optional keyword overrides from the filter config and feeds task-type hints to the gate controller.
4. **Serving Requests** – `TrueNASHTTPMCP` processes JSON-RPC `initialize`, `tools/list`, `tools/call`, `prompts/list`, and `prompts/get` calls, enforcing the user-provided scopes plus gating decisions on each round-trip.
5. **Shutdown** – `TrueNASMCPServer.cleanup()` runs when the FastAPI application stops, ensuring HTTP clients disconnect cleanly.

> The HTTP server mirrors the behavior of `docker-swarm-mcp` so MCP-compatible clients can swap between the two without code changes.

## Authentication & Scopes

- **Single-token mode** – Set `MCP_ACCESS_TOKEN` to require a single bearer token that automatically receives the `admin` scope.
- **Scoped tokens** – Provide a JSON object via `TOKEN_SCOPES` (or `TOKEN_SCOPES_FILE`) where each key is a token and each value is a list of scopes, e.g. `{ "token-a": ["storage", "snapshot"], "token-b": ["apps"] }`.
- **Verification** – `verify_token_with_scopes()` (see `http_api/auth.py`) validates the `Authorization: Bearer ...` header or `X-Access-Token` header and forwards a scope set into the request handler.

If neither `MCP_ACCESS_TOKEN` nor `TOKEN_SCOPES` is configured, the server refuses to start.

## Server Environment Variables

| Variable | Description | Default |
| --- | --- | --- |
| `MCP_ACCESS_TOKEN` / `_FILE` | Primary bearer token | _required unless TOKEN_SCOPES is set_ |
| `TOKEN_SCOPES` / `_FILE` | JSON map `{token: [scopes...]}` | empty |
| `MCP_TRANSPORT` | Reported transport (`http` or `sse`) | `http` |
| `ALLOWED_ORIGINS` | Comma-separated CORS allow list | `*` |
| `LOG_LEVEL` | Python logging level | `INFO` |
| `INTENT_CLASSIFICATION_ENABLED` | Toggle keyword-based task routing | `true` |
| `INTENT_FALLBACK_TO_ALL` | Allow fall back to all tools when intent fails | `true` |
| `INTENT_PRECEDENCE` | Which signal wins (`intent` or `explicit` header) | `intent` |
| `STRICT_CONTEXT_LIMIT` | Enforce hard token ceiling in gate controller | `false` |
| `MCP_MAX_TOOLS` | Max tools returned when not overridden per task type | `12` |
| `FILTER_CONFIG_PATH` | Path to JSON file with gating overrides | `filter-config.json` |

All variables honor the `_FILE` convention so secrets can be injected through Docker/Kubernetes secrets.

## Filter Configuration

`FilterConfig` combines three inputs:

```json
{
  "task_type_allowlists": {
    "storage-ops": ["list_pools", "list_datasets"],
    "snapshot-ops": ["list_snapshots", "create_snapshot"],
    "meta-ops": ["debug_connection"]
  },
  "max_tools": 18,
  "blocklist": ["delete_dataset"],
  "intent_keywords": {
    "apps": ["kubernetes", "helm"],
    "snapshot-ops": ["snapshot", "restore"]
  }
}
```

- Place the file wherever `FILTER_CONFIG_PATH` points (defaults to the project root `filter-config.json`).
- Task-type keys are normalized to lowercase kebab-case. Aliases like `storage`, `storage_ops`, or `storageops` all resolve to `storage-ops`.
- `max_tools` feeds the `ResourceFilter`, and `blocklist` enforces a hard deny list before responses are serialized.
- `intent_keywords` (optional) gives the keyword classifier deterministic overrides for tricky phrases.

If the file is missing or invalid, the server logs a warning and auto-builds allowlists from the tool metadata, ensuring the server still starts with sensible defaults.

## Endpoints & Headers

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Liveness probe (`{"status": "healthy", ...}`) |
| `/` | GET | Human-friendly metadata plus handy endpoint map |
| `/mcp` | POST | JSON-RPC 2.0 endpoint that mirrors OpenAI MCP conventions |

Important headers:

- `Authorization: Bearer <token>` – required for every `/mcp` call (or provide `X-Access-Token`).
- `X-Session-ID` – optional; if absent the server hashes the bearer token to create a stable session ID via `_derive_session_id()`.
- `X-Task-Type` – optional hint that narrows `tools/list` responses to a specific task group; aliases are accepted.

## Request Flow

1. FastAPI validates and parses the JSON-RPC payload into `JSONRPCRequest` models.
2. A request UUID plus derived session ID are logged for traceability.
3. `TrueNASHTTPMCP` dispatches to the appropriate handler (`handle_initialize`, `handle_tools_list`, `handle_tools_call`, etc.).
4. `ToolGateController` applies filters in order: task type → resource limit → security blocklist.
5. Results (or JSON-RPC errors) are serialized via `serialize_response()`.

Unhandled exceptions are trapped, logged with `request_id`/`session_id`, and returned as JSON-RPC `INTERNAL_ERROR` objects so clients receive a well-formed response.

## Logging

Logging format is `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"`. Set `LOG_LEVEL=DEBUG` to:

- Enable verbose tool-gate diagnostics (remaining tool counts, alias matches)
- Switch the context-size estimator to `tiktoken` if available, providing accurate token counts before enforcing the 7,600-token hard limit.

## Testing Checklist

Use [testing.md](testing.md) for end-to-end curl smoke tests. The health, dataset, sharing, snapshot, and SCALE app commands in that document map directly to the `/health`, `/`, and `/mcp` endpoints described above, making it easy to validate changes after modifying the HTTP server or gating rules.

"""FastAPI entrypoint that mirrors docker-swarm-mcp's HTTP behavior."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from truenas_mcp_server import TrueNASMCPServer, __version__
from truenas_mcp_server.http_api.auth import verify_token_with_scopes
from truenas_mcp_server.http_api.intent_classifier import KeywordIntentClassifier
from truenas_mcp_server.http_api.jsonrpc_models import (
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    serialize_response,
)
from truenas_mcp_server.http_api.mcp_server import TrueNASHTTPMCP
from truenas_mcp_server.http_api.settings import http_settings
from truenas_mcp_server.http_api.tool_gating import FilterConfig, ToolGateController
from truenas_mcp_server.http_api.tool_registry import TrueNASToolRegistry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared state for the HTTP server and ensure cleanup."""

    _configure_logging()
    logger.info("Starting TrueNAS MCP HTTP server v%s", __version__)

    try:
        truenas_server = TrueNASMCPServer()
        await truenas_server.initialize()
    except Exception as exc:  # pragma: no cover - startup validation
        logger.error("Failed to initialize TrueNAS MCP server: %s", exc)
        sys.exit(1)

    tool_registry = TrueNASToolRegistry(truenas_server.tools)
    filter_config, keyword_overrides = _load_filter_config(tool_registry)
    gate_controller = ToolGateController(tool_registry.get_all_tools(), filter_config)
    intent_classifier = KeywordIntentClassifier(keyword_overrides)
    mcp_server = TrueNASHTTPMCP(
        tool_registry,
        gate_controller,
        intent_classifier,
        server_version=__version__,
    )

    app.state.truenas_server = truenas_server
    app.state.tool_registry = tool_registry
    app.state.tool_gate_controller = gate_controller
    app.state.mcp_server = mcp_server

    yield

    logger.info("Shutting down TrueNAS MCP HTTP server")
    try:
        await truenas_server.cleanup()
    except Exception as exc:  # pragma: no cover - shutdown cleanup
        logger.warning("Cleanup error: %s", exc)


def _configure_logging() -> None:
    """Configure root logging using the HTTP settings."""

    logging.basicConfig(
        level=getattr(logging, http_settings.log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _load_filter_config(tool_registry: TrueNASToolRegistry) -> tuple[FilterConfig, dict[str, list[str]] | None]:
    """Load task gating config from disk, falling back to auto-generated defaults."""

    config_path = Path(http_settings.filter_config_path)
    default_allowlists = _build_default_allowlists(tool_registry)

    if not config_path.exists():
        logger.warning("filter-config.json not found; using automatic defaults")
        return (
            FilterConfig(
                task_type_allowlists=default_allowlists,
                max_tools=http_settings.default_max_tools,
                blocklist=[],
            ),
            None,
        )

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in %s: %s", config_path, exc)
        return (
            FilterConfig(
                task_type_allowlists=default_allowlists,
                max_tools=http_settings.default_max_tools,
                blocklist=[],
            ),
            None,
        )

    allowlists = data.get("task_type_allowlists") or default_allowlists
    blocklist = data.get("blocklist") or []
    max_tools = data.get("max_tools") or http_settings.default_max_tools
    intent_keywords = data.get("intent_keywords")

    return (
        FilterConfig(
            task_type_allowlists=allowlists,
            max_tools=max_tools,
            blocklist=blocklist,
        ),
        intent_keywords,
    )


def _build_default_allowlists(tool_registry: TrueNASToolRegistry) -> dict[str, list[str]]:
    """Construct allowlists by enumerating task types on every registered tool."""

    allowlists: dict[str, list[str]] = {}
    for tool_name, tool in tool_registry.get_all_tools().items():
        for task_type in tool.task_types:
            allowlists.setdefault(task_type, []).append(tool_name)
    return allowlists


app = FastAPI(
    title="TrueNAS MCP HTTP Server",
    description="HTTP-based Model Context Protocol server for TrueNAS Core & SCALE",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=http_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Simple liveness probe compatible with docker-swarm-mcp deployments."""

    return {"status": "healthy", "version": __version__, "transport": http_settings.mcp_transport}


@app.get("/")
async def root() -> dict[str, Any]:
    """Expose service metadata and primary endpoints for ad-hoc inspection."""

    return {
        "name": "TrueNAS MCP HTTP Server",
        "version": __version__,
        "transport": http_settings.mcp_transport,
        "endpoints": {"mcp": "/mcp", "health": "/health"},
    }


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    rpc_request: JSONRPCRequest,
    scopes: set[str] = Depends(verify_token_with_scopes),
    x_task_type: str | None = Header(default=None, alias="X-Task-Type"),
):
    """Handle JSON-RPC traffic for MCP clients, including gating enforcement."""

    request_id = str(uuid.uuid4())
    session_id = request.headers.get("X-Session-ID") or _derive_session_id(request)
    is_notification = rpc_request.id is None

    logger.info(
        "JSON-RPC %s (%s)",
        rpc_request.method,
        "notification" if is_notification else "request",
        extra={"request_id": request_id, "session_id": session_id},
    )

    mcp_server: TrueNASHTTPMCP = request.app.state.mcp_server

    if is_notification:
        logger.info("Dropping notification response per spec", extra={"request_id": request_id})
        return Response(content="", media_type="application/json")

    try:
        if rpc_request.method == "initialize":
            result = await mcp_server.handle_initialize(request_id, session_id)
            return serialize_response(JSONRPCResponse(id=rpc_request.id, result=result))

        if rpc_request.method == "tools/list":
            result = await mcp_server.handle_tools_list(
                rpc_request.params,
                request_id,
                session_id,
                scopes,
                x_task_type,
            )
            return serialize_response(JSONRPCResponse(id=rpc_request.id, result=result))

        if rpc_request.method == "tools/call":
            result = await mcp_server.handle_tools_call(
                rpc_request.params,
                request_id,
                session_id,
                scopes,
            )
            if "error" in result:
                return serialize_response(JSONRPCResponse(id=rpc_request.id, error=result["error"]))
            return serialize_response(JSONRPCResponse(id=rpc_request.id, result=result))

        if rpc_request.method == "prompts/list":
            result = await mcp_server.handle_prompts_list(request_id, session_id)
            return serialize_response(JSONRPCResponse(id=rpc_request.id, result=result))

        if rpc_request.method == "prompts/get":
            result = await mcp_server.handle_prompts_get(rpc_request.params, request_id, session_id)
            if isinstance(result, dict) and "error" in result:
                return serialize_response(JSONRPCResponse(id=rpc_request.id, error=result["error"]))
            return serialize_response(JSONRPCResponse(id=rpc_request.id, result=result))

        logger.warning("Unknown JSON-RPC method: %s", rpc_request.method)
        return serialize_response(
            JSONRPCResponse(
                id=rpc_request.id,
                error=JSONRPCError.create_error(
                    JSONRPCError.METHOD_NOT_FOUND,
                    f"Method '{rpc_request.method}' not found",
                ),
            )
        )

    except Exception as exc:  # pragma: no cover - runtime protection
        logger.exception("Unhandled MCP error", extra={"request_id": request_id, "session_id": session_id})
        return serialize_response(
            JSONRPCResponse(
                id=rpc_request.id,
                error=JSONRPCError.create_error(
                    JSONRPCError.INTERNAL_ERROR,
                    f"Internal server error: {exc}",
                ),
            )
        )


def _derive_session_id(request: Request) -> str:
    """Generate a repeatable session ID derived from the caller's token when available."""

    token_source: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        token_source = parts[1] if len(parts) == 2 else auth_header
    if not token_source:
        token_source = request.headers.get("X-Access-Token")

    if token_source:
        digest = hashlib.sha256(token_source.encode("utf-8")).hexdigest()
        return f"token-{digest[:16]}"

    return str(uuid.uuid4())

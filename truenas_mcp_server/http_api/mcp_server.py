"""JSON-RPC handlers for the HTTP TrueNAS MCP server."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Set

import jsonschema

from .intent_classifier import IntentClassifierBase
from .jsonrpc_models import JSONRPCError
from .settings import http_settings
from .tool_gating import FilterContext, Tool, ToolGateController
from .tool_registry import TrueNASToolRegistry

logger = logging.getLogger(__name__)


class TrueNASHTTPMCP:
    """MCP handler that mirrors docker-swarm-mcp behavior."""

    def __init__(
        self,
        tool_registry: TrueNASToolRegistry,
        tool_gate_controller: ToolGateController,
        intent_classifier: IntentClassifierBase | None = None,
        server_version: str = "unknown",
    ) -> None:
        self.tool_registry = tool_registry
        self.tool_gate_controller = tool_gate_controller
        self.intent_classifier = intent_classifier
        self.session_tools: dict[str, dict[str, Tool]] = {}
        self.server_version = server_version

    # ------------------------------------------------------------------
    async def handle_initialize(self, request_id: str, session_id: str) -> dict[str, Any]:
        logger.info(
            "tools/initialize called",
            extra={"request_id": request_id, "session_id": session_id},
        )
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "gating": True,
                    "context_size_enforcement": True,
                    "task_type_filtering": True,
                },
                "prompts": {"listChanged": False},
            },
            "serverInfo": {
                "name": "truenas-mcp-server",
                "version": self.server_version,
            },
        }

    # ------------------------------------------------------------------
    async def handle_tools_list(
        self,
        params: dict[str, Any] | None,
        request_id: str,
        session_id: str,
        scopes: Set[str],
        task_type_header: str | None,
    ) -> dict[str, Any]:
        params = params or {}
        task_type = task_type_header or params.get("task_type")
        query = params.get("query")

        detected_task_types = None
        classification_method = "none"

        if (
            query
            and self.intent_classifier
            and http_settings.intent_classification_enabled
        ):
            detected_task_types = self.intent_classifier.classify_intent(query)
            classification_method = "intent"
            if http_settings.intent_precedence == "intent":
                task_type = None
            logger.info(
                "Intent classifier detected %s",
                detected_task_types,
                extra={"request_id": request_id, "session_id": session_id},
            )
        elif task_type:
            classification_method = "explicit"

        context = FilterContext(
            task_type=task_type,
            client_id=None,
            session_id=session_id,
            request_id=request_id,
            query=query,
            detected_task_types=detected_task_types,
        )

        filtered_tools, filters_applied = self.tool_gate_controller.get_available_tools(context)

        # Scope enforcement
        if scopes and "admin" not in scopes:
            filtered_tools = {
                name: tool
                for name, tool in filtered_tools.items()
                if any(scope in scopes for scope in (tool.required_scopes or tool.task_types))
            }
            filters_applied.append("ScopeFilter")

        self.session_tools[session_id] = filtered_tools.copy()

        context_size = self.tool_gate_controller.get_context_size(filtered_tools)

        logger.info(
            "tools/list returned %s tools",
            len(filtered_tools),
            extra={"request_id": request_id, "session_id": session_id},
        )

        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.request_schema
                    or {"type": "object", "properties": {}, "required": []},
                }
                for tool in filtered_tools.values()
            ],
            "_metadata": {
                "context_size": context_size,
                "filters_applied": filters_applied,
                "classification_method": classification_method,
                "query": query,
                "detected_task_types": detected_task_types,
            },
        }

    # ------------------------------------------------------------------
    async def handle_prompts_list(self, request_id: str, session_id: str) -> dict[str, Any]:
        logger.info("prompts/list called", extra={"request_id": request_id, "session_id": session_id})
        return {
            "prompts": [
                {
                    "name": "intent-query-help",
                    "description": "How to use natural language queries for task routing",
                }
            ]
        }

    async def handle_prompts_get(
        self,
        params: dict[str, Any] | None,
        request_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        prompt_name = (params or {}).get("name")
        if prompt_name != "intent-query-help":
            return {
                "error": JSONRPCError.create_error(
                    JSONRPCError.INVALID_PARAMS, f"Unknown prompt name: {prompt_name}"
                )
            }

        return {
            "description": "Guide to using natural language queries",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            "You can supply a natural language query in tools/list params. "
                            "The server will classify it into task types for you."
                        ),
                    },
                }
            ],
        }

    # ------------------------------------------------------------------
    async def handle_tools_call(
        self,
        params: dict[str, Any] | None,
        request_id: str,
        session_id: str,
        scopes: Set[str],
    ) -> dict[str, Any]:
        if not params or "name" not in params:
            return {
                "error": JSONRPCError.create_error(
                    JSONRPCError.INVALID_PARAMS, "Missing 'name' parameter"
                )
            }

        tool_name = params["name"]
        arguments = params.get("arguments", {})

        session_filtered = self.session_tools.get(session_id) or self.tool_registry.get_all_tools()

        if tool_name not in session_filtered:
            return {
                "error": JSONRPCError.create_error(
                    JSONRPCError.METHOD_NOT_FOUND,
                    f"Tool '{tool_name}' not available or blocked by gating",
                )
            }

        tool_meta = session_filtered[tool_name]

        required_scopes = tool_meta.required_scopes or tool_meta.task_types
        if scopes and "admin" not in scopes and not any(scope in scopes for scope in required_scopes):
            return {
                "error": JSONRPCError.create_error(
                    JSONRPCError.METHOD_NOT_FOUND,
                    f"Insufficient permissions. Required scopes: {required_scopes}",
                )
            }

        if tool_meta.request_schema:
            try:
                jsonschema.validate(instance=arguments, schema=tool_meta.request_schema)
            except jsonschema.ValidationError as exc:
                return {
                    "error": JSONRPCError.create_error(
                        JSONRPCError.INVALID_PARAMS,
                        f"Invalid parameters: {exc.message}",
                        {"path": list(exc.absolute_path)},
                    )
                }

        handler = self.tool_registry.get_handler(tool_name)
        if handler is None:
            return {
                "error": JSONRPCError.create_error(
                    JSONRPCError.METHOD_NOT_FOUND,
                    f"Handler for '{tool_name}' not found",
                )
            }

        try:
            result = await _invoke_handler(handler, arguments)
        except Exception as exc:  # pragma: no cover - runtime protection
            logger.exception(
                "Tool execution failed",
                extra={"request_id": request_id, "session_id": session_id, "tool": tool_name},
            )
            return {
                "error": JSONRPCError.create_error(
                    JSONRPCError.INTERNAL_ERROR,
                    f"Tool execution failed: {exc}",
                )
            }

        if tool_meta.response_schema:
            try:
                jsonschema.validate(instance=result, schema=tool_meta.response_schema)
            except jsonschema.ValidationError as exc:
                logger.warning("Response validation failed for %s: %s", tool_name, exc)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, indent=2, default=str),
                }
            ]
        }


async def _invoke_handler(handler, arguments: Dict[str, Any]):
    if asyncio.iscoroutinefunction(handler):
        return await handler(**arguments)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: handler(**arguments))


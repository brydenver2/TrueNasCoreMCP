"""Build tool metadata for the HTTP MCP server from TrueNAS tool definitions."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from .tool_gating import Tool

logger = logging.getLogger(__name__)

# Map tool classes to task types used by gating/intent classification
TASK_TYPE_MAP: dict[str, list[str]] = {
    "UserTools": ["user-ops"],
    "StorageTools": ["storage-ops"],
    "SharingTools": ["sharing-ops"],
    "SnapshotTools": ["snapshot-ops"],
    "AppTools": ["apps-ops"],
    "InstanceTools": ["instance-ops"],
    "LegacyVMTools": ["vm-ops"],
    "DebugTools": ["debug-ops"],
}


class TrueNASToolRegistry:
    """Generate Tool metadata and provide access to handlers."""

    def __init__(self, tool_instances: list[Any]):
        self._tools: dict[str, Tool] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._load_tools(tool_instances)

    # ------------------------------------------------------------------
    def _load_tools(self, tool_instances: list[Any]) -> None:
        for tool in tool_instances:
            class_name = tool.__class__.__name__
            task_types = TASK_TYPE_MAP.get(class_name, ["truenas-ops"])

            try:
                definitions = tool.get_tool_definitions()
            except Exception as exc:
                logger.error("Failed to read tool definitions from %s: %s", class_name, exc)
                continue

            for entry in definitions:
                try:
                    name, handler, description, param_schema = entry
                except ValueError:
                    logger.warning("Unexpected tool definition format for %s", class_name)
                    continue

                schema = self._build_input_schema(param_schema or {})
                tool_meta = Tool(
                    name=name,
                    description=description,
                    method="rpc",
                    path=f"/tools/{name}",
                    request_schema=schema,
                    response_schema={"type": "object"},
                    task_types=task_types,
                    priority=0,
                    required_scopes=task_types,
                )

                self._tools[name] = tool_meta
                self._handlers[name] = handler

        logger.info("Registered %s HTTP tools", len(self._tools))

    # ------------------------------------------------------------------
    def _build_input_schema(self, params: Dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, meta in params.items():
            if not isinstance(meta, dict):
                continue

            json_type = meta.get("type", "string")
            prop: dict[str, Any] = {"type": json_type}

            if "description" in meta:
                prop["description"] = meta["description"]

            for extra_key in ("enum", "items", "format", "default", "minimum", "maximum"):
                if extra_key in meta:
                    prop[extra_key] = meta[extra_key]

            properties[param_name] = prop

            if meta.get("required"):
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    # ------------------------------------------------------------------
    def get_all_tools(self) -> dict[str, Tool]:
        return self._tools.copy()

    def get_handler(self, tool_name: str) -> Callable[..., Any] | None:
        return self._handlers.get(tool_name)

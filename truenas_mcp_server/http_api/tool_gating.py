"""Tool gating utilities shared with the HTTP MCP server."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .settings import http_settings

logger = logging.getLogger(__name__)


class Tool(BaseModel):
    """Metadata for a TrueNAS MCP tool exposed over HTTP."""

    name: str
    description: str
    method: str
    path: str
    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any]
    task_types: list[str]
    priority: int = 0
    required_scopes: list[str] | None = None


class FilterContext(BaseModel):
    task_type: str | None = None
    client_id: str | None = None
    session_id: str | None = None
    request_id: str
    query: str | None = None
    detected_task_types: list[str] | None = None
    intent_confidence: dict[str, float] | None = None


class ToolFilter(ABC):
    @abstractmethod
    def apply(self, tools: dict[str, Tool], context: FilterContext) -> dict[str, Tool]:
        raise NotImplementedError


class TaskTypeFilter(ToolFilter):
    def __init__(self, task_type_allowlists: dict[str, list[str]]):
        self.task_type_allowlists, self._alias_map = self._expand_allowlists(task_type_allowlists)

    def apply(self, tools: dict[str, Tool], context: FilterContext) -> dict[str, Tool]:
        if (
            context.query is not None
            and context.detected_task_types == []
            and (http_settings.strict_context_limit or not http_settings.intent_fallback_to_all)
        ):
            logger.warning(
                "Strict no-match mode: returning empty tool set",
                extra={
                    "request_id": context.request_id,
                    "query": context.query[:100] + "..." if len(context.query or "") > 100 else context.query,
                },
            )
            return {}

        task_types_to_use: list[str] = []
        classification_source = "none"

        if http_settings.intent_precedence == "intent":
            if context.detected_task_types:
                task_types_to_use = context.detected_task_types
                classification_source = "intent"
            elif context.task_type:
                task_types_to_use = [context.task_type]
                classification_source = "explicit"
        else:
            if context.task_type:
                task_types_to_use = [context.task_type]
                classification_source = "explicit"
            elif context.detected_task_types:
                task_types_to_use = context.detected_task_types
                classification_source = "intent"

        task_types_to_use = self._normalize_task_types(task_types_to_use)

        if not task_types_to_use:
            filtered_tools = {
                name: tool for name, tool in tools.items() if "meta-ops" not in tool.task_types
            }
            logger.debug(
                "TaskTypeFilter excluded meta-ops tools by default",
                extra={"request_id": context.request_id, "remaining": len(filtered_tools)},
            )
            return filtered_tools

        merged_allowlist = self._merge_allowlists(task_types_to_use)

        if not merged_allowlist:
            if http_settings.strict_context_limit or not http_settings.intent_fallback_to_all:
                logger.warning(
                    "Unknown task types and strict mode enabled; returning empty set",
                    extra={"request_id": context.request_id, "source": classification_source},
                )
                return {}
            logger.warning(
                "Unknown task types; returning all tools (fallback enabled)",
                extra={"request_id": context.request_id, "source": classification_source},
            )
            return tools

        filtered = {
            name: tool
            for name, tool in tools.items()
            if (name in merged_allowlist) and any(t in tool.task_types for t in task_types_to_use)
        }

        logger.debug(
            "TaskTypeFilter applied",
            extra={
                "request_id": context.request_id,
                "task_types": task_types_to_use,
                "allowlist": merged_allowlist,
                "remaining": len(filtered),
            },
        )

        return filtered

    def _merge_allowlists(self, task_types: list[str]) -> list[str]:
        merged: set[str] = set()
        for task_type in task_types:
            merged.update(self.task_type_allowlists.get(task_type, []))
        return list(merged)

    def _normalize_task_types(self, task_types: list[str]) -> list[str]:
        normalized: list[str] = []
        for task_type in task_types:
            key = self._normalize_key(task_type)
            if not key:
                continue
            if key in self.task_type_allowlists:
                normalized.append(key)
                continue
            if key in self._alias_map:
                normalized.append(self._alias_map[key])
        return normalized

    def _expand_allowlists(
        self, task_type_allowlists: dict[str, list[str]]
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        normalized: dict[str, list[str]] = {}
        alias_map: dict[str, str] = {}

        for raw_key, tools in task_type_allowlists.items():
            canonical = self._normalize_key(raw_key)
            if not canonical:
                continue
            normalized[canonical] = tools

        for canonical in list(normalized.keys()):
            for alias in self._alias_candidates(canonical):
                if alias in normalized or alias in alias_map:
                    continue
                alias_map[alias] = canonical

        return normalized, alias_map

    @staticmethod
    def _normalize_key(value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip().lower()
        return normalized or None

    def _alias_candidates(self, canonical: str) -> set[str]:
        aliases: set[str] = set()

        if canonical.endswith("-ops"):
            trimmed = canonical[: -len("-ops")]
            if trimmed:
                aliases.add(trimmed)

        hyphen_to_underscore = canonical.replace("-", "_")
        if hyphen_to_underscore and hyphen_to_underscore != canonical:
            aliases.add(hyphen_to_underscore)

        compact = hyphen_to_underscore.replace("_", "")
        if compact and compact != canonical:
            aliases.add(compact)

        return aliases


class ResourceFilter(ToolFilter):
    def __init__(self, max_tools: int):
        self.max_tools = max_tools

    def apply(self, tools: dict[str, Tool], context: FilterContext) -> dict[str, Tool]:
        if len(tools) <= self.max_tools:
            return tools

        sorted_tools = sorted(tools.items(), key=lambda item: (-item[1].priority, item[0]))
        filtered = dict(sorted_tools[: self.max_tools])
        logger.debug(
            "ResourceFilter truncated tool list",
            extra={"request_id": context.request_id, "max_tools": self.max_tools},
        )
        return filtered


class SecurityFilter(ToolFilter):
    def __init__(self, blocklist: list[str]):
        self.blocklist = set(blocklist)

    def apply(self, tools: dict[str, Tool], context: FilterContext) -> dict[str, Tool]:
        filtered = {name: tool for name, tool in tools.items() if name not in self.blocklist}
        if len(filtered) != len(tools):
            blocked = set(tools.keys()) - set(filtered.keys())
            logger.debug("SecurityFilter blocked %s", blocked, extra={"request_id": context.request_id})
        return filtered


class FilterConfig(BaseModel):
    task_type_allowlists: dict[str, list[str]]
    max_tools: int
    blocklist: list[str]


class ToolGateController:
    def __init__(self, all_tools: dict[str, Tool], config: FilterConfig):
        self.all_tools = all_tools
        self.config = config
        self.filters: list[ToolFilter] = [
            TaskTypeFilter(config.task_type_allowlists),
            ResourceFilter(config.max_tools or http_settings.default_max_tools),
            SecurityFilter(config.blocklist),
        ]
        self._tool_sizes: dict[str, int] = {}
        self._total_all_tools_size = 0
        self._estimator_type = "unknown"
        self._precompute_tool_sizes()

    def get_available_tools(self, context: FilterContext) -> tuple[dict[str, Tool], list[str]]:
        tools = self.all_tools.copy()
        filters_applied: list[str] = []

        for filter_instance in self.filters:
            before = tools.copy()
            tools = filter_instance.apply(tools, context)
            if tools != before:
                filters_applied.append(filter_instance.__class__.__name__)

        return tools, filters_applied

    def list_active_tools(self) -> list[str]:
        return list(self.all_tools.keys())

    def get_context_size(self, tools: dict[str, Tool], enforce_hard_limit: bool | None = None) -> int:
        if enforce_hard_limit is None:
            enforce_hard_limit = http_settings.strict_context_limit

        if self._tool_sizes and self._estimator_type != "fallback":
            token_count = sum(self._tool_sizes.get(name, 0) for name in tools.keys())
        else:
            serialized = json.dumps([tool.model_dump() for tool in tools.values()])
            if http_settings.log_level == "DEBUG":
                try:
                    import tiktoken  # type: ignore

                    enc = tiktoken.get_encoding("cl100k_base")
                    token_count = len(enc.encode(serialized))
                    self._estimator_type = "tiktoken"
                except Exception:
                    token_count = len(serialized) // 4
                    self._estimator_type = "approx"
            else:
                token_count = len(serialized) // 4
                self._estimator_type = "approx"

        if token_count > 7600:
            message = (
                f"Context size {token_count} tokens exceeds hard limit of 7600 tokens. "
                "Reduce tool count or enable stricter filtering."
            )
            logger.error(message)
            if enforce_hard_limit:
                raise ValueError(message)

        if token_count > 5000:
            logger.warning(
                "Context size %s tokens exceeds recommended threshold",
                token_count,
            )

        return token_count

    def _precompute_tool_sizes(self) -> None:
        try:
            import tiktoken  # type: ignore

            enc = tiktoken.get_encoding("cl100k_base")
            self._estimator_type = "tiktoken"
            for name, tool in self.all_tools.items():
                serialized = json.dumps(tool.model_dump())
                self._tool_sizes[name] = len(enc.encode(serialized))
        except Exception:
            self._estimator_type = "approx"
            for name, tool in self.all_tools.items():
                serialized = json.dumps(tool.model_dump())
                self._tool_sizes[name] = len(serialized) // 4

        self._total_all_tools_size = sum(self._tool_sizes.values())

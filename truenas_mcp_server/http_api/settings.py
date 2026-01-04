"""Environment-driven settings for the HTTP MCP server."""

from __future__ import annotations

import json
import os
from typing import Literal


class HttpServerSettings:
    """Settings loader for the FastAPI/OpenAI-compatible server."""

    def __init__(self) -> None:
        self.mcp_access_token: str = self._read_env_or_file("MCP_ACCESS_TOKEN")
        self.token_scopes_raw: str = os.getenv("TOKEN_SCOPES", "").strip()
        self.mcp_transport: Literal["http", "sse"] = self._parse_transport(
            os.getenv("MCP_TRANSPORT", "http").strip().lower() or "http"
        )
        self.allowed_origins: list[str] = self._parse_origins(os.getenv("ALLOWED_ORIGINS", "*").strip())
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # Intent classification + context controls (match docker-swarm defaults)
        self.intent_classification_enabled: bool = os.getenv(
            "INTENT_CLASSIFICATION_ENABLED", "true"
        ).lower() == "true"
        self.intent_fallback_to_all: bool = os.getenv("INTENT_FALLBACK_TO_ALL", "true").lower() == "true"
        self.intent_precedence: Literal["intent", "explicit"] = self._parse_precedence(
            os.getenv("INTENT_PRECEDENCE", "intent").strip().lower() or "intent"
        )
        self.strict_context_limit: bool = os.getenv("STRICT_CONTEXT_LIMIT", "false").lower() == "true"

        # Tool gating defaults
        self.default_max_tools: int = int(os.getenv("MCP_MAX_TOOLS", "12"))
        self.filter_config_path: str = os.getenv("FILTER_CONFIG_PATH", "filter-config.json")

        self._token_scopes_cache: dict[str, list[str]] | None = None
        self.validate()

    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Validate authentication and option combinations."""
        has_primary_token = bool(self.mcp_access_token)
        has_scope_map = bool(self.token_scopes_raw)

        if not has_primary_token and not has_scope_map:
            raise ValueError(
                "MCP_ACCESS_TOKEN or TOKEN_SCOPES must be configured for the HTTP server."
            )

        if has_scope_map:
            try:
                mapping = json.loads(self.token_scopes_raw)
            except json.JSONDecodeError as exc:  # pragma: no cover - config guard
                raise ValueError(f"TOKEN_SCOPES contains invalid JSON: {exc}") from exc
            if not isinstance(mapping, dict):
                raise ValueError("TOKEN_SCOPES must decode to a JSON object")
            self._token_scopes_cache = {str(k): list(v) for k, v in mapping.items()}

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_origins(raw: str) -> list[str]:
        if not raw:
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @staticmethod
    def _read_env_or_file(env_name: str) -> str:
        direct = os.getenv(env_name)
        file_path = os.getenv(f"{env_name}_FILE")

        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    return handle.read().strip()
            except OSError as exc:  # pragma: no cover - startup validation
                raise ValueError(f"Unable to read {env_name}_FILE: {exc}") from exc

        return (direct or "").strip()

    @staticmethod
    def _parse_transport(value: str) -> Literal["http", "sse"]:
        if value not in {"http", "sse"}:
            raise ValueError("MCP_TRANSPORT must be 'http' or 'sse'")
        return value  # type: ignore[return-value]

    @staticmethod
    def _parse_precedence(value: str) -> Literal["intent", "explicit"]:
        if value not in {"intent", "explicit"}:
            raise ValueError("INTENT_PRECEDENCE must be 'intent' or 'explicit'")
        return value  # type: ignore[return-value]

    # ------------------------------------------------------------------
    def resolve_scopes(self, token: str) -> set[str]:
        """Return scopes for a validated token."""
        if self._token_scopes_cache and token in self._token_scopes_cache:
            return set(self._token_scopes_cache[token])
        # Default: admin scope when using single token
        return {"admin"}


http_settings = HttpServerSettings()

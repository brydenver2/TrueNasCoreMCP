"""JSON-RPC request/response schemas."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class JSONRPCRequest(BaseModel):
    jsonrpc: str = Field(default="2.0", pattern="^2\\.0$")
    method: str
    params: dict[str, Any] | None = None
    id: str | int | None = None


class JSONRPCResponse(BaseModel):
    model_config = ConfigDict(exclude_none=True)

    jsonrpc: str = "2.0"
    result: Any | None = None
    error: dict[str, Any] | None = None
    id: str | int | None = None


class JSONRPCError:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    @staticmethod
    def create_error(code: int, message: str, data: Any | None = None) -> dict[str, Any]:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return error


def serialize_response(response: JSONRPCResponse) -> JSONResponse:
    payload = {"jsonrpc": response.jsonrpc, "id": response.id}
    if response.error is not None:
        payload["error"] = response.error
    else:
        payload["result"] = response.result
    return JSONResponse(content=payload)

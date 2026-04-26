"""
HTTP bridge for remote MCP-style Godot Agent integrations.

This is a deployment-facing wrapper around the same tool contracts used by the
stdio MCP server. It is useful for IDEs, local network gateways, or cloud
reverse proxies that cannot launch a stdio MCP process directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from bridge.mcp_server import execute_mcp_tool
from bridge.tool_contracts import list_tool_definitions


REMOTE_MCP_BRIDGE_SCHEMA_VERSION = "1.0"

app = FastAPI(title="Godot Agent Remote MCP Bridge", version=REMOTE_MCP_BRIDGE_SCHEMA_VERSION)
remote_router: Optional[GodotAgentRouter] = None


class ToolCallRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)


def get_router() -> GodotAgentRouter:
    global remote_router
    if remote_router is None:
        remote_router = GodotAgentRouter()
    return remote_router


def build_remote_bridge_manifest() -> Dict[str, Any]:
    return {
        "schema_version": REMOTE_MCP_BRIDGE_SCHEMA_VERSION,
        "server_name": "godot-agent-remote",
        "transport": "http",
        "tools": list_tool_definitions(),
        "endpoints": {
            "health": "/health",
            "manifest": "/mcp/manifest",
            "tool_call_pattern": "/tools/{tool_name}",
        },
        "notes": [
            "This bridge reuses the stdio MCP tool schemas.",
            "Deploy behind local auth or a private gateway before exposing beyond localhost.",
        ],
    }


def _content_item_to_dict(item: Any) -> Dict[str, Any]:
    item_type = getattr(item, "type", "")
    if item_type == "text":
        return {"type": "text", "text": getattr(item, "text", "")}
    if item_type == "image":
        return {
            "type": "image",
            "mime_type": getattr(item, "mimeType", "image/png"),
            "data": getattr(item, "data", ""),
        }
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return {"type": str(item_type or "unknown"), "value": str(item)}


def _tool_result_to_payload(tool_name: str, result: Any) -> Dict[str, Any]:
    return {
        "schema_version": REMOTE_MCP_BRIDGE_SCHEMA_VERSION,
        "tool_name": tool_name,
        "is_error": bool(getattr(result, "isError", False)),
        "content": [_content_item_to_dict(item) for item in list(getattr(result, "content", []) or [])],
        "structured_content": getattr(result, "structuredContent", None),
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "schema_version": REMOTE_MCP_BRIDGE_SCHEMA_VERSION,
        "status": "ok",
        "router_initialized": remote_router is not None,
        "tool_count": len(list_tool_definitions()),
    }


@app.get("/mcp/manifest")
async def mcp_manifest() -> Dict[str, Any]:
    return build_remote_bridge_manifest()


@app.post("/tools/{tool_name}")
async def call_tool(tool_name: str, request: ToolCallRequest) -> Dict[str, Any]:
    tool_names = {item["name"] for item in list_tool_definitions()}
    if tool_name not in tool_names:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    result = execute_mcp_tool(get_router(), tool_name, request.arguments)
    return _tool_result_to_payload(tool_name, result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)

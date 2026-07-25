"""Skill script: unreal_call_function.

Call a Blueprint-callable UFunction. Requires DCC_MCP_UNREAL_ALLOW_EXECUTE=1.
"""
from __future__ import annotations

from typing import Any


def skill_main(params: dict) -> dict[str, Any]:
    from dcc_mcp_unreal.server import get_server

    server = get_server()
    if server is None:
        return {"error": "UnrealMcpServer is not running"}

    result = server.call_function(
        object_path=params["object_path"],
        function_name=params["function_name"],
        args=params.get("args", {}),
        timeout_ms=params.get("timeout_ms", 10000),
    )

    if result is None:
        return {"error": "call_function failed"}

    return result.to_dict()

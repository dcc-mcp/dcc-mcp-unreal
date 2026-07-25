"""Skill script: unreal_set_property.

Write a single property value. Requires DCC_MCP_UNREAL_ALLOW_WRITE=1.
"""
from __future__ import annotations

from typing import Any


def skill_main(params: dict) -> dict[str, Any]:
    from dcc_mcp_unreal.server import get_server

    server = get_server()
    if server is None:
        return {"error": "UnrealMcpServer is not running"}

    result = server.set_property(
        object_path=params["object_path"],
        property_name=params["property_name"],
        value=params["value"],
    )

    if result is None:
        return {"error": "set_property failed"}

    return result.to_dict()

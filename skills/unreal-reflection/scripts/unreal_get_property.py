"""Skill script: unreal_get_property.

Read a single property value with security checks.
"""
from __future__ import annotations

from typing import Any


def skill_main(params: dict) -> dict[str, Any]:
    from dcc_mcp_unreal.server import get_server

    server = get_server()
    if server is None:
        return {"error": "UnrealMcpServer is not running"}

    result = server.get_property(
        object_path=params["object_path"],
        property_name=params["property_name"],
    )

    if result is None:
        return {"error": "get_property failed"}

    return result.to_dict()

"""Skill script: unreal_describe_object.

Get detailed reflection info for a single UObject.
"""
from __future__ import annotations

from typing import Any


def skill_main(params: dict) -> dict[str, Any]:
    from dcc_mcp_unreal.server import get_server

    server = get_server()
    if server is None:
        return {"error": "UnrealMcpServer is not running"}

    desc = server.describe_object(
        object_path=params["object_path"],
        include_properties=params.get("include_properties", True),
        include_functions=params.get("include_functions", True),
    )

    if desc is None:
        return {"error": f"Object not found: {params['object_path']}"}

    return desc.to_dict()

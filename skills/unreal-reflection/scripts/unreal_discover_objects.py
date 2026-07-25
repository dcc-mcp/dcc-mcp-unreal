"""Skill script: unreal_discover_objects.

Discover UObjects in the current Unreal Editor world with fail-closed security.
"""
from __future__ import annotations

from typing import Any


def skill_main(params: dict) -> dict[str, Any]:
    """Skill entry point called by the dcc-mcp-core dispatcher."""
    from dcc_mcp_unreal.server import get_server

    server = get_server()
    if server is None:
        return {"objects": [], "error": "UnrealMcpServer is not running"}

    objects = server.discover_objects(
        class_filter=params.get("class_filter"),
        outer_filter=params.get("outer_filter"),
        max_results=params.get("max_results", 100),
    )

    return {"objects": [o.to_dict() for o in objects]}

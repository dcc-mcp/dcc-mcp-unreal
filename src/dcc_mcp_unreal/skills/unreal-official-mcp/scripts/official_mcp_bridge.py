"""Bridge DCC MCP calls to Unreal Engine 5.8's optional built-in MCP server."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.official_mcp import DEFAULT_OFFICIAL_MCP_URL, OfficialMcpError, bridge_official_mcp


@skill_entry
def official_mcp_bridge(
    operation: str = "status",
    endpoint: str = DEFAULT_OFFICIAL_MCP_URL,
    toolset_name: str = "",
    tool_name: str = "",
    arguments: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> dict:
    try:
        import unreal  # noqa: F401, PLC0415

        in_unreal = True
    except ImportError:
        in_unreal = False
    if in_unreal and threading.current_thread() is threading.main_thread():
        return skill_error(
            "Epic MCP bridge must run off Unreal's game thread",
            "Call this skill through the DCC MCP gateway with affinity:any to avoid a same-process HTTP deadlock",
        )
    try:
        result = bridge_official_mcp(
            operation=operation,
            endpoint=endpoint,
            toolset_name=toolset_name,
            tool_name=tool_name,
            arguments=arguments,
        )
    except OfficialMcpError as exc:
        return skill_error(
            "Epic Unreal MCP is unavailable or rejected the request",
            str(exc),
            possible_solutions=[
                "Use Unreal Engine 5.8 or newer and enable the Unreal MCP plugin.",
                "Start ModelContextProtocol on its loopback endpoint.",
                "Use the regular DCC MCP Unreal skills as the compatibility fallback.",
            ],
        )
    return skill_success("Epic Unreal MCP bridge request completed.", operation=operation, result=result)

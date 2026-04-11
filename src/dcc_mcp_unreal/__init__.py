"""dcc-mcp-unreal — Unreal Engine plugin for the DCC Model Context Protocol ecosystem.

Embeds a standards-compliant MCP Streamable HTTP server inside Unreal Engine
using dcc-mcp-core. Leverages Unreal Engine's built-in Python plugin (5.0+).

Quickstart (inside Unreal Engine's Python interpreter)::

    import dcc_mcp_unreal
    handle = dcc_mcp_unreal.start_server(port=8765)
    # MCP host connects to http://127.0.0.1:8765/mcp
    handle.shutdown()

Skill authoring helpers::

    from dcc_mcp_unreal.api import (
        unreal_success, unreal_error, unreal_from_exception,
        require_unreal, with_unreal,
    )

Requirements:
    - Unreal Engine 5.0+ with Python Editor Script Plugin enabled
    - dcc-mcp-core >= 0.12.14
"""

from __future__ import annotations

from dcc_mcp_unreal.__version__ import __version__
from dcc_mcp_unreal.api import (
    UnrealNotAvailableError,
    get_unreal,
    is_unreal_available,
    require_unreal,
    unreal_error,
    unreal_from_exception,
    unreal_success,
    with_unreal,
)
from dcc_mcp_unreal.server import UnrealMcpServer, start_server, stop_server

__all__ = [
    "__version__",
    # Server
    "UnrealMcpServer",
    "start_server",
    "stop_server",
    # Skill authoring helpers
    "unreal_success",
    "unreal_error",
    "unreal_from_exception",
    "require_unreal",
    "get_unreal",
    "is_unreal_available",
    "with_unreal",
    "UnrealNotAvailableError",
]

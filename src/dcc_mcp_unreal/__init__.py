"""dcc-mcp-unreal — Unreal Engine plugin for the DCC Model Context Protocol ecosystem.

Embeds a standards-compliant MCP Streamable HTTP server inside Unreal Engine
using dcc-mcp-core. The native baseline supports Unreal Engine 4.18+; Python
skills activate when the engine's Python Editor Script Plugin is available.

Quickstart (inside Unreal Engine's Python interpreter)::

    import dcc_mcp_unreal
    handle = dcc_mcp_unreal.start_server()
    # The instance URL is discovered through the stable gateway or local CLI.
    handle.shutdown()

Skill authoring helpers::

    from dcc_mcp_unreal.api import (
        unreal_success, unreal_error, unreal_warning, unreal_from_exception,
        require_unreal, with_unreal,
        require_param, missing_param_error,
        actor_to_dict, vector_to_list, rotator_to_list,
    )

Requirements:
    - Unreal Engine 4.18+ for the native baseline
    - Python Editor Script Plugin for Python-backed skills
    - dcc-mcp-core >= 0.20.13
"""

from __future__ import annotations

from dcc_mcp_unreal.__version__ import __version__
from dcc_mcp_unreal.api import (
    MissingParamError,
    UnrealNotAvailableError,
    actor_to_dict,
    build_context_dict,
    ensure_valid_name,
    get_param_list,
    get_unreal,
    is_unreal_available,
    missing_param_error,
    require_any_param,
    require_param,
    require_unreal,
    rotator_to_list,
    unreal_error,
    unreal_from_exception,
    unreal_success,
    unreal_warning,
    vector_to_list,
    with_unreal,
)
from dcc_mcp_unreal.capabilities import UNREAL_CAPABILITIES_DICT, unreal_capabilities
from dcc_mcp_unreal.compatibility import unreal_compatibility
from dcc_mcp_unreal.server import UnrealMcpServer, start_server, stop_server

__all__ = [
    "__version__",
    # Server
    "UnrealMcpServer",
    "start_server",
    "stop_server",
    # Core result helpers
    "unreal_success",
    "unreal_error",
    "unreal_warning",
    "unreal_from_exception",
    # Availability helpers
    "require_unreal",
    "get_unreal",
    "is_unreal_available",
    "UnrealNotAvailableError",
    # Decorator
    "with_unreal",
    # Parameter helpers
    "require_param",
    "require_any_param",
    "get_param_list",
    "missing_param_error",
    "MissingParamError",
    # Name and context helpers
    "ensure_valid_name",
    "build_context_dict",
    # Unreal data model helpers
    "vector_to_list",
    "rotator_to_list",
    "actor_to_dict",
    # Capabilities
    "unreal_capabilities",
    "UNREAL_CAPABILITIES_DICT",
    "unreal_compatibility",
]

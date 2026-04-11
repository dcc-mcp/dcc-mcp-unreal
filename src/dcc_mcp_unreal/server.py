"""UnrealMcpServer — embedded MCP Streamable HTTP server for Unreal Engine.

Architecture mirrors dcc-mcp-maya. Uses dcc-mcp-core's create_skill_manager()
factory which wires ActionRegistry + ActionDispatcher + SkillCatalog.

Flow::

    server = UnrealMcpServer(port=8765)
    server.register_builtin_actions()
    handle = server.start()
    print(handle.mcp_url())  # http://127.0.0.1:8765/mcp
    handle.shutdown()

Environment variables:
    DCC_MCP_UNREAL_SKILL_PATHS  — extra skill directories
    DCC_MCP_SKILL_PATHS         — global fallback

Search path resolution (highest to lowest priority):

1. ``extra_skill_paths`` supplied by the caller
2. Built-in skills shipped with this package (``src/dcc_mcp_unreal/skills/``)
3. ``DCC_MCP_UNREAL_SKILL_PATHS`` environment variable
4. ``DCC_MCP_SKILL_PATHS`` environment variable (global fallback)
5. Platform default (``dcc_mcp_core.get_skills_dir()``)

Requirements:
    - Unreal Engine 5.0+ with Python Editor Script Plugin
    - dcc-mcp-core >= 0.12.14
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_BUILTIN_SKILLS_DIR = Path(__file__).parent / "skills"

_server_instance: Optional["UnrealMcpServer"] = None
_server_lock = threading.Lock()


class UnrealMcpServer:
    """Embedded MCP server for Unreal Engine.

    Wraps dcc-mcp-core's create_skill_manager() for Unreal-specific path
    discovery and lifecycle management.

    Example::

        server = UnrealMcpServer(port=8765)
        handle = server.start()
        print(handle.mcp_url())  # http://127.0.0.1:8765/mcp
        # ... agent connects and uses tools ...
        handle.shutdown()
    """

    def __init__(self, port: int = 8765, extra_skill_paths: Optional[List[str]] = None) -> None:
        """Create an UnrealMcpServer.

        Args:
            port: HTTP port to listen on (default 8765).
            extra_skill_paths: Additional skill directories to scan in addition
                to the built-in skills and environment variable paths.
        """
        self._port = port
        self._extra_skill_paths = extra_skill_paths or []
        self._server = None
        self._handle = None

    def _get_skill_paths(self) -> List[str]:
        """Resolve skill search paths in priority order."""
        paths: List[str] = []
        paths.extend(self._extra_skill_paths)
        if _BUILTIN_SKILLS_DIR.exists():
            paths.append(str(_BUILTIN_SKILLS_DIR))
        return paths

    def register_builtin_actions(self) -> None:
        """Discover and load all built-in Unreal skills.

        Called automatically by :meth:`start`. Safe to call manually for
        pre-loading skills before the server starts.
        """
        from dcc_mcp_core import McpHttpConfig, create_skill_manager

        config = McpHttpConfig(port=self._port)
        extra_paths = self._get_skill_paths()
        self._server = create_skill_manager(
            "unreal",
            config=config,
            extra_paths=extra_paths or None,
            dcc_name="unreal",
        )
        logger.info("UnrealMcpServer: registered skills from %d path(s)", len(extra_paths))

    def start(self) -> Any:
        """Start the MCP HTTP server.

        Calls :meth:`register_builtin_actions` if not already done.

        Returns:
            ServerHandle — call ``.mcp_url()`` and ``.shutdown()`` on it.
        """
        if self._server is None:
            self.register_builtin_actions()
        self._handle = self._server.start()
        logger.info("UnrealMcpServer started at %s", self._handle.mcp_url())
        return self._handle

    def stop(self) -> None:
        """Stop the MCP HTTP server."""
        if self._handle is not None:
            self._handle.shutdown()
            self._handle = None
            logger.info("UnrealMcpServer stopped")


def start_server(port: int = 8765, extra_skill_paths: Optional[List[str]] = None) -> Any:
    """Start the module-level singleton MCP server.

    Thread-safe. If a server is already running, returns the existing handle.

    Args:
        port: HTTP port (default 8765).
        extra_skill_paths: Additional skill directories to load.

    Returns:
        ServerHandle with ``.mcp_url()`` and ``.shutdown()`` methods.

    Example::

        import dcc_mcp_unreal
        handle = dcc_mcp_unreal.start_server(port=8765)
        print(handle.mcp_url())  # http://127.0.0.1:8765/mcp
    """
    global _server_instance
    with _server_lock:
        if _server_instance is None:
            _server_instance = UnrealMcpServer(port=port, extra_skill_paths=extra_skill_paths)
        return _server_instance.start()


def stop_server() -> None:
    """Stop the module-level singleton MCP server."""
    global _server_instance
    with _server_lock:
        if _server_instance is not None:
            _server_instance.stop()
            _server_instance = None

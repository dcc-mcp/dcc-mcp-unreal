"""DCC MCP Unreal — manual startup helper script.

This script is an alternative to the full plugin.  Copy it to your project's
``Content/Python/`` directory to start the MCP server without installing the
plugin.

Usage
-----
Add to your project's Python startup scripts (Project Settings → Plugins →
Python → Additional Paths or Startup Scripts), or run manually from the
Unreal Editor Output Log:

    py dcc_mcp_unreal_startup.py

Or import from the Unreal Python console:

    import dcc_mcp_unreal_startup

Configuration (environment variables)
--------------------------------------
``DCC_MCP_UNREAL_PORT``         TCP port.  Default: ``8765``.
``DCC_MCP_UNREAL_SERVER_NAME``  MCP server name.  Default: ``"unreal-mcp"``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def start() -> None:
    """Start the DCC MCP Unreal server."""
    try:
        import dcc_mcp_unreal  # noqa: PLC0415
        import unreal  # noqa: PLC0415

        port = int(os.environ.get("DCC_MCP_UNREAL_PORT", "8765"))
        server_name = os.environ.get("DCC_MCP_UNREAL_SERVER_NAME", "unreal-mcp")
        handle = dcc_mcp_unreal.start_server(port=port, server_name=server_name)
        unreal.log(f"[dcc-mcp-unreal] MCP server running at {handle.mcp_url()}")
    except ImportError as exc:
        logger.error("[dcc-mcp-unreal] Import error: %s", exc)
        logger.error("Install dcc-mcp-unreal: pip install dcc-mcp-unreal")
    except Exception as exc:
        logger.error("[dcc-mcp-unreal] Failed to start: %s", exc)


def stop() -> None:
    """Stop the DCC MCP Unreal server."""
    try:
        import dcc_mcp_unreal  # noqa: PLC0415

        dcc_mcp_unreal.stop_server()
    except Exception as exc:
        logger.warning("[dcc-mcp-unreal] Stop failed: %s", exc)


# Auto-start when script is executed or imported
start()

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
``DCC_MCP_UNREAL_PORT``         Optional fixed MCP instance port.
``DCC_MCP_UNREAL_SERVER_NAME``  MCP server name.  Default: ``"unreal-mcp"``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _bootstrap_log_dir() -> Path:
    plugin_root = _plugin_root()
    project_root = plugin_root.parent.parent if plugin_root.parent.name == "Plugins" else plugin_root.parent
    return project_root / ".dcc-mcp" / "bootstrap-errors"


def _adapter_version() -> str:
    try:
        descriptor = json.loads((_plugin_root() / "DccMcpUnreal.uplugin").read_text(encoding="utf-8"))
        return str(descriptor.get("VersionName") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def start() -> None:
    """Start the DCC MCP Unreal server."""
    try:
        from dcc_mcp_core import capture_bootstrap_errors  # noqa: PLC0415

        with capture_bootstrap_errors(
            "unreal",
            adapter_version=_adapter_version(),
            min_core_version="0.20.0",
            phase="bootstrap",
            log_dir=str(_bootstrap_log_dir()),
            metadata={"runtime_mode": "manual-python"},
        ):
            import dcc_mcp_unreal  # noqa: PLC0415
            import unreal  # noqa: PLC0415

            server_name = os.environ.get("DCC_MCP_UNREAL_SERVER_NAME", "unreal-mcp")
            handle = dcc_mcp_unreal.start_server(server_name=server_name)
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

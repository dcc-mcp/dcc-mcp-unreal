"""Bootstrap script for embedding dcc-mcp-unreal inside Unreal Editor.

This is the main entry point that Unreal Editor's Python Plugin runs at startup.
Place this file in your project's ``Content/Python/`` directory and add::

    import dcc_mcp_unreal.bootstrap

to your ``init_unreal.py``.

Alternatively, configure the Python Plugin to execute::

    py dcc_mcp_unreal.bootstrap

at editor startup via Project Settings → Python → Additional Startup Scripts.

Environment variables:
    DCC_MCP_UNREAL_PORT: TCP port for the MCP HTTP server (default: 0 = OS-assigned).
    DCC_MCP_UNREAL_GATEWAY_PORT: Gateway competition port.
    DCC_MCP_UNREAL_SKILL_PATHS: Extra skill directories (semicolon-separated on Windows).
    DCC_MCP_UNREAL_ALLOW_WRITE: Set to "1" to enable property writes.
    DCC_MCP_UNREAL_ALLOW_EXECUTE: Set to "1" to enable UFunction calls.
    DCC_MCP_UNREAL_BRIDGE_URL: URL of the C++ plugin bridge (default: http://127.0.0.1:19876).
"""

from __future__ import annotations

import os
import sys

import dcc_mcp_unreal


def _resolve_env_port(default: int = 0) -> int:
    """Resolve port from environment."""
    val = os.environ.get("DCC_MCP_UNREAL_PORT", "")
    if val.isdigit():
        return int(val)
    return default


def _resolve_security_policy():
    """Build the initial security policy from environment variables."""
    from dcc_mcp_unreal.security import default_full_policy, default_read_policy

    allow_write = os.environ.get("DCC_MCP_UNREAL_ALLOW_WRITE", "") == "1"
    allow_execute = os.environ.get("DCC_MCP_UNREAL_ALLOW_EXECUTE", "") == "1"

    if allow_write or allow_execute:
        policy = default_full_policy()
        if not allow_write:
            policy.allow_write = False
        if not allow_execute:
            policy.allow_execute = False
        return policy

    return default_read_policy()


def _resolve_skill_paths() -> list:
    """Resolve extra skill paths from environment."""
    env_val = os.environ.get("DCC_MCP_UNREAL_SKILL_PATHS", "")
    if not env_val:
        return []
    separator = ";" if sys.platform == "win32" else ":"
    return [p.strip() for p in env_val.split(separator) if p.strip()]


def boot() -> dcc_mcp_unreal.UnrealMcpServer:
    """Bootstrap the dcc-mcp-unreal server inside Unreal Editor.

    Call this from your ``init_unreal.py`` or editor startup script.

    Returns:
        The running :class:`UnrealMcpServer` instance.
    """
    port = _resolve_env_port()
    security = _resolve_security_policy()
    extra_paths = _resolve_skill_paths()
    bridge_url = os.environ.get("DCC_MCP_UNREAL_BRIDGE_URL")

    server = dcc_mcp_unreal.start_server(
        port=port,
        extra_skill_paths=extra_paths,
        security_policy=security,
        bridge_url=bridge_url,
        register_builtins=True,
    )

    # Log startup info
    try:
        import unreal  # noqa: PLC0415

        unreal.log(f"[dcc-mcp-unreal] Server started on port {server.port}")
        unreal.log(f"[dcc-mcp-unreal] Security: write={security.allow_write}, execute={security.allow_execute}")
    except ImportError:
        print(f"[dcc-mcp-unreal] Server started on port {server.port}")

    return server


def boot_standalone():
    """Bootstrap for headless/standalone mode (no Unreal Editor running).

    Use this for testing and development workflows outside Unreal Editor.
    """
    from dcc_mcp_core.host import QueueDispatcher

    from dcc_mcp_unreal.host import UnrealHost

    boot()
    dispatcher = QueueDispatcher()

    host = UnrealHost(dispatcher)
    try:
        host.run_headless()
    except KeyboardInterrupt:
        pass
    finally:
        dcc_mcp_unreal.stop_server()


# ── Auto-boot when this module is executed directly ─────────────────────────

if __name__ == "__main__":
    boot_standalone()

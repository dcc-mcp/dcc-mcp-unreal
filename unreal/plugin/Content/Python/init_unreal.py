"""DCC MCP Unreal — Unreal Engine plugin Python entry point.

This file is automatically executed by Unreal Engine when the plugin is
loaded, because it is named ``init_unreal.py`` inside the plugin's
``Content/Python/`` directory.

Unreal Engine Python Plugin loading order
------------------------------------------
1. Engine-level ``init_unreal.py`` files (Engine/Plugins/.../Content/Python/)
2. Project-level ``init_unreal.py`` files (ProjectRoot/Plugins/.../Content/Python/)
3. ``startup`` scripts configured in Project Settings → Python

This file performs the equivalent of Maya's ``initializePlugin``:
1. Ensures ``dcc_mcp_unreal`` is importable (adds the plugin's ``python/``
   directory to ``sys.path`` if needed).
2. Starts the MCP HTTP server.
3. Registers Editor menu items via ``unreal.ToolMenus``.

Configuration (environment variables)
--------------------------------------
``DCC_MCP_UNREAL_PORT``
    TCP port for the MCP HTTP server.  Default: ``8765``.

``DCC_MCP_UNREAL_SERVER_NAME``
    Name advertised in the MCP ``initialize`` response.  Default: ``"unreal-mcp"``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure dcc_mcp_unreal package is importable
# ---------------------------------------------------------------------------


def _ensure_package_importable() -> None:
    """Add the plugin's python/ directory to sys.path.

    When the plugin is installed as a project plugin, the ``python/``
    subdirectory contains the ``dcc_mcp_unreal`` package and its dependency
    ``dcc_mcp_core``.  Unreal does not automatically add plugin subdirectories
    to sys.path, so we do it here.
    """
    # This script lives in <plugin_root>/Content/Python/
    # The python/ package directory is at <plugin_root>/python/
    content_python_dir = Path(__file__).resolve().parent
    plugin_root = content_python_dir.parent.parent  # Content/Python -> Content -> plugin root
    python_dir = plugin_root / "python"

    # Development fallback for this repository's local test project:
    # <repo>/Plugins/DccMcpUnreal/Content/Python/init_unreal.py
    # should be able to import <repo>/src and ../dcc-mcp-core/src even when
    # packaging is run with --skip-python-deps.
    project_root = plugin_root.parent.parent if plugin_root.parent.name == "Plugins" else None
    if project_root is not None:
        _add_sys_path(project_root / "src", prepend=False)
        _add_sys_path(project_root.parent / "dcc-mcp-core" / "src", prepend=False)
        _add_sys_path(project_root.parent / "dcc-mcp-core" / "python", prepend=False)

    # Packaged dependencies must win over source checkout paths and globally
    # installed packages; otherwise a smoke test can pass against stale local
    # code instead of the distributable plugin.
    if python_dir.is_dir():
        _add_sys_path(python_dir, prepend=True)

    try:
        import dcc_mcp_unreal  # noqa: F401, PLC0415

        return
    except ImportError:
        logger.warning(
            "[dcc-mcp-unreal] dcc_mcp_unreal could not be imported. "
            "Install a packaged plugin with python/ dependencies or run from a source checkout.",
        )


def _add_sys_path(path: Path, *, prepend: bool = True) -> None:
    if path.is_dir():
        path_str = str(path)
        if path_str not in sys.path:
            if prepend:
                sys.path.insert(0, path_str)
            else:
                sys.path.append(path_str)
            logger.debug("[dcc-mcp-unreal] Added %s to sys.path", path_str)


_ensure_package_importable()

# ---------------------------------------------------------------------------
# Module-level server handle and menu state
# ---------------------------------------------------------------------------

_handle = None
_menus_registered = False


# ---------------------------------------------------------------------------
# Version helper
# ---------------------------------------------------------------------------


def _get_version() -> str:
    try:
        from dcc_mcp_unreal.__version__ import __version__  # noqa: PLC0415

        return __version__
    except Exception:
        return "0.0.0"


VERSION = _get_version()

# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------


def _start() -> None:
    global _handle
    try:
        import dcc_mcp_unreal  # noqa: PLC0415

        port = int(os.environ.get("DCC_MCP_UNREAL_PORT", "8765"))
        server_name = os.environ.get("DCC_MCP_UNREAL_SERVER_NAME", "unreal-mcp")
        _handle = dcc_mcp_unreal.start_server(port=port, server_name=server_name)
        import unreal as ue  # noqa: PLC0415

        ue.log(f"[dcc-mcp-unreal] v{VERSION} MCP server started at {_handle.mcp_url()}")
    except Exception as exc:
        logger.error("[dcc-mcp-unreal] Failed to start MCP server: %s", exc)
        try:
            import unreal as ue  # noqa: PLC0415

            ue.log_warning(f"[dcc-mcp-unreal] Failed to start MCP server: {exc}")
        except Exception:
            pass
        raise


def _stop() -> None:
    global _handle
    try:
        import dcc_mcp_unreal  # noqa: PLC0415

        dcc_mcp_unreal.stop_server()
        _handle = None
        import unreal as ue  # noqa: PLC0415

        ue.log("[dcc-mcp-unreal] MCP server stopped")
    except Exception as exc:
        logger.warning("[dcc-mcp-unreal] Failed to stop MCP server: %s", exc)


def _server_url() -> str:
    if _handle is not None:
        try:
            return _handle.mcp_url()
        except Exception:
            pass
    return "<not running>"


def _restart() -> None:
    _stop()
    _start()
    try:
        import unreal as ue  # noqa: PLC0415

        ue.log(f"[dcc-mcp-unreal] MCP server restarted at {_server_url()}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Unreal Editor menu integration
# ---------------------------------------------------------------------------


def _register_menus() -> None:
    """Register DCC MCP entries in the Unreal Editor menu bar.

    Creates a top-level "DCC MCP" menu under the main menu bar with items for:
    - Showing the MCP server URL
    - Restarting the server
    - Stopping the server

    Uses ``unreal.ToolMenus`` (UE 5.0+).
    """
    global _menus_registered
    if _menus_registered:
        return

    try:
        import unreal  # noqa: PLC0415

        tool_menus = unreal.ToolMenus.get()
        if tool_menus is None:
            logger.debug("[dcc-mcp-unreal] ToolMenus unavailable; skipping editor menu registration")
            return

        # Add a top-level "DCC MCP" menu under the main menu bar
        main_menu = tool_menus.extend_menu("MainFrame.MainMenu")
        if main_menu is None:
            logger.debug("[dcc-mcp-unreal] MainFrame.MainMenu unavailable; skipping editor menu registration")
            return

        section = main_menu.add_section("DccMcpSection", unreal.Text("DCC MCP"))

        # ── Show MCP URL ──────────────────────────────────────────────────
        show_url_entry = unreal.ToolMenuEntry(
            name="DccMcp.ShowUrl",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        show_url_entry.set_label(unreal.Text("Show MCP Server URL"))
        show_url_entry.set_tool_tip(unreal.Text("Display the URL to connect your MCP agent to"))

        def _on_show_url(context):
            url = _server_url()
            _show_notification(f"MCP Server URL: {url}")

        show_url_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._show_url_dialog()",
        )
        section.add_menu_entry("DccMcp.ShowUrl", show_url_entry)

        # ── Restart Server ────────────────────────────────────────────────
        restart_entry = unreal.ToolMenuEntry(
            name="DccMcp.Restart",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        restart_entry.set_label(unreal.Text("Restart MCP Server"))
        restart_entry.set_tool_tip(unreal.Text("Stop and restart the MCP HTTP server"))
        restart_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._restart()",
        )
        section.add_menu_entry("DccMcp.Restart", restart_entry)

        # ── Stop Server ───────────────────────────────────────────────────
        stop_entry = unreal.ToolMenuEntry(
            name="DccMcp.Stop",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        stop_entry.set_label(unreal.Text("Stop MCP Server"))
        stop_entry.set_tool_tip(unreal.Text("Stop the MCP HTTP server"))
        stop_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._stop()",
        )
        section.add_menu_entry("DccMcp.Stop", stop_entry)

        tool_menus.refresh_all_widgets()
        _menus_registered = True
        logger.debug("[dcc-mcp-unreal] Editor menus registered")

    except Exception as exc:
        logger.warning("[dcc-mcp-unreal] Could not register editor menus: %s", exc)


def _unregister_menus() -> None:
    global _menus_registered
    try:
        import unreal  # noqa: PLC0415

        tool_menus = unreal.ToolMenus.get()
        tool_menus.remove_menu("MainFrame.MainMenu.DccMcpSection")
        tool_menus.refresh_all_widgets()
        _menus_registered = False
    except Exception as exc:
        logger.debug("[dcc-mcp-unreal] Menu unregister skipped: %s", exc)


# ---------------------------------------------------------------------------
# Notification helpers (callable from menu string commands)
# ---------------------------------------------------------------------------


def _show_notification(message: str) -> None:
    """Show a brief on-screen notification in the Unreal Editor viewport."""
    try:
        import unreal  # noqa: PLC0415

        unreal.EditorDialog.show_message(
            title="DCC MCP",
            message=message,
            message_type=unreal.AppMsgType.OK,
        )
    except Exception:
        logger.info("[dcc-mcp-unreal] %s", message)


def _show_url_dialog() -> None:
    """Show a dialog with the current MCP server URL."""
    _show_notification(
        f"Connect your MCP agent to:\n\n{_server_url()}\n\n"
        "Add this URL as an MCP server in Claude Desktop, Cursor, or any\n"
        "MCP-compatible host using the 'streamable-http' transport."
    )


# ---------------------------------------------------------------------------
# Plugin entry point — called automatically by Unreal when init_unreal.py loads
# ---------------------------------------------------------------------------


def _initialize() -> None:
    """Plugin initialisation: start server and register menus."""
    try:
        _start()
    except Exception as exc:
        logger.error("[dcc-mcp-unreal] Initialisation failed: %s", exc)
        return

    # Register menus only when running in editor (not commandlet / game)
    if os.environ.get("DCC_MCP_UNREAL_DISABLE_MENUS", "").lower() in ("1", "true", "yes"):
        return

    try:
        import unreal  # noqa: PLC0415

        if unreal.is_editor():
            # Defer menu registration until after the main menu bar is ready
            unreal.register_slate_post_tick_callback(_on_first_tick)
    except Exception as exc:
        logger.debug("[dcc-mcp-unreal] Menu registration deferred: %s", exc)


# One-shot tick callback to register menus after the editor is fully initialised
_tick_handle = None


def _on_first_tick(delta: float) -> None:
    global _tick_handle
    _register_menus()
    # Unregister this callback after first run
    try:
        import unreal  # noqa: PLC0415

        if _tick_handle is not None:
            unreal.unregister_slate_post_tick_callback(_tick_handle)
            _tick_handle = None
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Run initialisation
# ---------------------------------------------------------------------------

_initialize()

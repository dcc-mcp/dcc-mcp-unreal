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
    Optional fixed MCP instance port.  By default the OS assigns a free port.

``DCC_MCP_UNREAL_SERVER_NAME``
    Name advertised in the MCP ``initialize`` response.  Default: ``"unreal-mcp"``.

``DCC_MCP_UNREAL_RUNTIME``
    Runtime selection: ``auto`` (default), ``python``, or ``sidecar``.

``DCC_MCP_UI_CONTROL_BACKEND``
    UI automation backend.  Defaults to ``"windows-uia"`` on Windows while
    preserving an explicit user override.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _configure_app_ui() -> None:
    """Make the bundled app-ui skill target this Unreal Editor process."""
    if sys.platform == "win32":
        os.environ.setdefault("DCC_MCP_UI_CONTROL_BACKEND", "windows-uia")
        os.environ.setdefault("DCC_MCP_UI_CONTROL_UIA_PROCESS_ID", str(os.getpid()))


_configure_app_ui()

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

        server_name = os.environ.get("DCC_MCP_UNREAL_SERVER_NAME", "unreal-mcp")
        _handle = dcc_mcp_unreal.start_server(server_name=server_name)
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


def _resolve_instance_id() -> Optional[str]:
    """Return the Unreal MCP instance UUID for the active server, if available.

    Used by the Copy Instance ID and Server Info menu actions.
    Returns ``None`` when the server is not running or the instance id
    is not yet assigned.
    """
    try:
        import dcc_mcp_unreal.server as server_mod  # noqa: PLC0415

        server = getattr(server_mod, "_server_instance", None)
        if server is not None:
            instance_id = getattr(server, "instance_id", None)
            if instance_id:
                return str(instance_id)
    except Exception as exc:
        logger.debug("[dcc-mcp-unreal] instance id lookup failed: %s", exc)
    return None


def _set_clipboard_text(text: str) -> None:
    """Set the system clipboard text, trying PySide2 then platform CLI fallback."""
    # PySide2 is available inside Unreal Engine 5 (Qt5 bindings).
    try:
        from PySide2 import QtWidgets  # noqa: PLC0415

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.clipboard().setText(text)
            return
    except Exception:
        pass

    # Platform CLI fallback for environments without Qt bindings.
    import subprocess  # noqa: PLC0415

    if sys.platform == "win32":
        subprocess.run(["clip"], input=text.encode("utf-16"), check=False)
    elif sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text.encode(), check=False)
    else:
        try:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=False)
        except FileNotFoundError:
            raise RuntimeError("Unable to access system clipboard (no PySide2, clip, pbcopy, or xclip available)")


def _copy_instance_id() -> None:
    """Copy the DCC MCP instance UUID to the system clipboard."""
    instance_id = _resolve_instance_id()
    if not instance_id:
        _show_notification("DCC MCP: Instance ID not available. Is the server running?")
        return
    try:
        _set_clipboard_text(instance_id)
    except RuntimeError as exc:
        _show_notification(str(exc))
        return

    try:
        import unreal as ue  # noqa: PLC0415

        ue.log(f"DCC MCP: Instance ID copied to clipboard: {instance_id}")
    except Exception:
        pass
    _show_notification("DCC MCP: Instance ID copied to clipboard")


def _show_server_info() -> None:
    """Show server status information in a dialog."""
    instance_id = _resolve_instance_id()
    url = _server_url()

    dcc_version = "unknown"
    try:
        import unreal as ue  # noqa: PLC0415

        system_library = getattr(ue, "SystemLibrary", None)
        if system_library is not None and hasattr(system_library, "get_engine_version"):
            dcc_version = str(system_library.get_engine_version())
    except Exception:
        pass

    gateway = os.environ.get("DCC_MCP_GATEWAY_PORT", "")
    gateway_display = gateway if gateway else "disabled"

    core_version = "unknown"
    try:
        from dcc_mcp_core.server_base import _package_version  # noqa: PLC0415

        core_version = _package_version() or "unknown"
    except Exception:
        pass

    msg = (
        f"Instance UUID: {instance_id or 'N/A'}\n"
        f"DCC: Unreal Engine {dcc_version}\n"
        f"PID: {os.getpid()}\n"
        f"MCP URL: {url}\n"
        f"Gateway Port: {gateway_display}\n"
        f"Core Version: {core_version}\n"
        f"Adapter Version: {VERSION}\n"
        f"Python: {sys.version.split()[0]}"
    )
    _show_notification(msg)


def _show_about() -> None:
    """Show about dialog with version information."""
    dcc_version = "unknown"
    try:
        import unreal as ue  # noqa: PLC0415

        system_library = getattr(ue, "SystemLibrary", None)
        if system_library is not None and hasattr(system_library, "get_engine_version"):
            dcc_version = str(system_library.get_engine_version())
    except Exception:
        pass

    msg = (
        f"dcc-mcp-unreal v{VERSION}\n"
        f"Unreal Engine {dcc_version}\n"
        f"Python {sys.version.split()[0]}\n\n"
        "DCC MCP — AI-driven DCC automation.\n"
        "https://github.com/dcc-mcp/dcc-mcp-unreal"
    )
    _show_notification(msg)


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
    - Copy Instance ID — copy the instance UUID to clipboard
    - Server Info — show instance metadata and server status
    - Show MCP Server URL — display the MCP URL
    - Restart / Stop MCP Server — lifecycle controls
    - About DCC MCP — version information

    Uses ``unreal.ToolMenus`` (UE 5.0+).  Sections provide visual dividers
    between groups.
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

        dcc_menu = main_menu.add_sub_menu(
            owner="DccMcp",
            section_name="",
            name="DccMcp",
            label="DCC MCP",
            tool_tip="DCC MCP server controls",
        )

        # ── Section: Instance ─────────────────────────────────────────────
        dcc_menu.add_section("DccMcpInstance", unreal.Text("Instance"))

        # Copy Instance ID
        copy_id_entry = unreal.ToolMenuEntry(
            name="DccMcp.CopyInstanceId",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        copy_id_entry.set_label(unreal.Text("Copy Instance ID"))
        copy_id_entry.set_tool_tip(unreal.Text("Copy the DCC MCP instance UUID to clipboard"))
        copy_id_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._copy_instance_id()",
        )
        dcc_menu.add_menu_entry("DccMcpInstance", copy_id_entry)

        # Server Info
        server_info_entry = unreal.ToolMenuEntry(
            name="DccMcp.ServerInfo",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        server_info_entry.set_label(unreal.Text("Server Info"))
        server_info_entry.set_tool_tip(unreal.Text("Show instance metadata and server status"))
        server_info_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._show_server_info()",
        )
        dcc_menu.add_menu_entry("DccMcpInstance", server_info_entry)

        # ── Section: Server ───────────────────────────────────────────────
        dcc_menu.add_section("DccMcpServer", unreal.Text("Server"))

        # Show MCP URL
        show_url_entry = unreal.ToolMenuEntry(
            name="DccMcp.ShowUrl",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        show_url_entry.set_label(unreal.Text("Show MCP Server URL"))
        show_url_entry.set_tool_tip(unreal.Text("Display the URL to connect your MCP agent to"))
        show_url_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._show_url_dialog()",
        )
        dcc_menu.add_menu_entry("DccMcpServer", show_url_entry)

        # ── Section: Control ──────────────────────────────────────────────
        dcc_menu.add_section("DccMcpControl", unreal.Text("Control"))

        # Restart Server
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
        dcc_menu.add_menu_entry("DccMcpControl", restart_entry)

        # Stop Server
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
        dcc_menu.add_menu_entry("DccMcpControl", stop_entry)

        # ── Section: About ────────────────────────────────────────────────
        dcc_menu.add_section("DccMcpAbout", unreal.Text("About"))

        # About DCC MCP
        about_entry = unreal.ToolMenuEntry(
            name="DccMcp.About",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        about_entry.set_label(unreal.Text("About DCC MCP"))
        about_entry.set_tool_tip(unreal.Text("Show version information"))
        about_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=unreal.Name(""),
            string="import init_unreal; init_unreal._show_about()",
        )
        dcc_menu.add_menu_entry("DccMcpAbout", about_entry)

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
        tool_menus.remove_menu("MainFrame.MainMenu.DccMcp")
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
    global _tick_handle
    if os.environ.get("DCC_MCP_UNREAL_RUNTIME", "auto").lower() == "sidecar":
        logger.info("[dcc-mcp-unreal] Standalone sidecar selected; skipping the embedded server")
        return
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
            _tick_handle = unreal.register_slate_post_tick_callback(_on_first_tick)
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

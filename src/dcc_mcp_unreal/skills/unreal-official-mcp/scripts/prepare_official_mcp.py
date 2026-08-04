"""Enable Unreal Engine 5.8's built-in MCP plugins for the current project."""

from __future__ import annotations

import configparser
import ctypes
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_PLUGIN_RELATIVE_PATHS = {
    "ModelContextProtocol": Path("Experimental/ModelContextProtocol/ModelContextProtocol.uplugin"),
    "EditorToolset": Path("Experimental/Toolsets/EditorToolset/EditorToolset.uplugin"),
    "NiagaraToolsets": Path("Experimental/Toolsets/NiagaraToolsets/NiagaraToolsets.uplugin"),
}
_MCP_SECTION = "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings"


def _process_arguments() -> list[str]:
    if os.name != "nt":
        return list(sys.argv)

    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    get_command_line = ctypes.windll.kernel32.GetCommandLineW
    get_command_line.argtypes = []
    get_command_line.restype = ctypes.c_wchar_p
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    argc = ctypes.c_int()
    argv = command_line_to_argv(get_command_line(), ctypes.byref(argc))
    if not argv:
        return list(sys.argv)
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        local_free(ctypes.cast(argv, ctypes.c_void_p))


def _resolve_project_context(arguments: Iterable[str]) -> tuple[Path, Path]:
    raw_arguments = list(arguments)
    project_arguments = [
        argument.split("=", 1)[1] for argument in raw_arguments[1:] if argument.lower().startswith("-project=")
    ]
    paths = [Path(argument) for argument in raw_arguments if not argument.lower().startswith("-project=")]
    project_file = next((path for path in paths[1:] if path.suffix.lower() == ".uproject"), None)
    if project_file is None:
        project_file = next(
            (Path(argument) for argument in project_arguments if Path(argument).suffix.lower() == ".uproject"),
            None,
        )
    if project_file is None:
        raise ValueError("The Unreal Editor process command line does not contain a .uproject path")
    project_file = project_file.resolve()

    executable = paths[0].resolve()
    engine_dir = next((parent for parent in executable.parents if parent.name.lower() == "engine"), None)
    if engine_dir is None:
        raise ValueError("The Unreal Engine directory could not be resolved from the editor executable")
    return project_file, engine_dir / "Plugins"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _upsert_plugins(project_data: dict[str, Any], plugin_names: Iterable[str]) -> list[str]:
    plugins = project_data.setdefault("Plugins", [])
    if not isinstance(plugins, list):
        raise ValueError("The .uproject Plugins field must be an array")

    changed: list[str] = []
    entries = {entry.get("Name"): entry for entry in plugins if isinstance(entry, dict)}
    for name in plugin_names:
        entry = entries.get(name)
        if entry is None:
            plugins.append({"Name": name, "Enabled": True})
            changed.append(name)
        elif entry.get("Enabled") is not True:
            entry["Enabled"] = True
            changed.append(name)
    return changed


def _configure_autostart(config_path: Path) -> bool:
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    if config_path.is_file():
        parser.read(config_path, encoding="utf-8-sig")
    if not parser.has_section(_MCP_SECTION):
        parser.add_section(_MCP_SECTION)

    desired = {
        "ServerPortNumber": "8000",
        "ServerUrlPath": "/mcp",
        "bAutoStartServer": "True",
        "bEnableToolSearch": "True",
    }
    changed = any(parser.get(_MCP_SECTION, key, fallback=None) != value for key, value in desired.items())
    if not changed:
        return False
    for key, value in desired.items():
        parser.set(_MCP_SECTION, key, value)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as stream:
        parser.write(stream, space_around_delimiters=False)
        stream.seek(0)
        _atomic_write_text(config_path, stream.read())
    return True


@skill_entry
def prepare_official_mcp(
    include_editor_toolset: bool = True,
    include_niagara_toolsets: bool = False,
    **kwargs,
) -> dict:
    """Enable official MCP plugins and autostart for the current project."""
    try:
        project_file, engine_plugins_dir = _resolve_project_context(_process_arguments())
    except (OSError, ValueError) as exc:
        return skill_error(
            "The current Unreal project could not be resolved",
            str(exc),
            possible_solutions=["Launch Unreal Editor with an explicit .uproject path."],
        )
    if not project_file.is_file():
        return skill_error(
            "The current Unreal project file could not be found",
            str(project_file),
            possible_solutions=["Open a saved .uproject before enabling the official MCP plugin."],
        )

    plugin_names = ["ModelContextProtocol"]
    if include_editor_toolset:
        plugin_names.append("EditorToolset")
    if include_niagara_toolsets:
        plugin_names.append("NiagaraToolsets")

    missing = [name for name in plugin_names if not (engine_plugins_dir / _PLUGIN_RELATIVE_PATHS[name]).is_file()]
    if missing:
        return skill_error(
            "Epic Unreal MCP plugins are not installed in this engine",
            f"Missing plugin descriptors: {', '.join(missing)}",
            possible_solutions=[
                "Use Unreal Engine 5.8 or newer with the ModelContextProtocol plugin installed.",
                "Use the regular DCC MCP Unreal skills as the compatibility fallback.",
            ],
        )

    try:
        project_data = json.loads(project_file.read_text(encoding="utf-8-sig"))
        if not isinstance(project_data, dict):
            raise ValueError("The .uproject root must be an object")
        changed_plugins = _upsert_plugins(project_data, plugin_names)
        if changed_plugins:
            _atomic_write_text(
                project_file,
                json.dumps(project_data, ensure_ascii=False, indent="\t") + "\n",
            )
        config_path = project_file.parent / "Config" / "DefaultEditorPerProjectUserSettings.ini"
        config_changed = _configure_autostart(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return skill_error(
            "Failed to configure Epic Unreal MCP for this project",
            str(exc),
            possible_solutions=["Check that the project and Config directory are writable."],
        )

    restart_required = bool(changed_plugins)
    message = (
        "Epic Unreal MCP project configuration is ready; restart Unreal Editor to load newly enabled plugins."
        if restart_required
        else "Epic Unreal MCP project configuration is ready."
    )
    return skill_success(
        message,
        prompt=(
            "Restart Unreal Editor, verify the DCC MCP instance, then call official_mcp_bridge with operation=status."
            if restart_required
            else "Call official_mcp_bridge with operation=status to verify the live endpoint."
        ),
        project_file=str(project_file),
        config_file=str(config_path),
        enabled_plugins=plugin_names,
        changed_plugins=changed_plugins,
        config_changed=config_changed,
        restart_required=restart_required,
    )

"""Enable Unreal Engine 5.8's built-in MCP plugins for the current project."""

from __future__ import annotations

import configparser
import ctypes
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_PLUGIN_RELATIVE_PATHS = {
    "ModelContextProtocol": Path("Experimental/ModelContextProtocol/ModelContextProtocol.uplugin"),
    "EditorToolset": Path("Experimental/Toolsets/EditorToolset/EditorToolset.uplugin"),
    "NiagaraToolsets": Path("Experimental/Toolsets/NiagaraToolsets/NiagaraToolsets.uplugin"),
    "PCGToolset": Path("Experimental/Toolsets/PCGToolset/PCGToolset.uplugin"),
}
# Inspect supported installed locations, never infer availability from an engine version.
_PCG_DEPENDENCY_PATHS = (Path("PCG/PCG.uplugin"), Path("Experimental/PCG/PCG.uplugin"))
_MCP_SECTION = "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings"
_AUTOSTART_SETTINGS = {
    "ServerPortNumber": "8000",
    "ServerUrlPath": "/mcp",
    "bAutoStartServer": "True",
    "bEnableToolSearch": "True",
}


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


def _atomic_write_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
        if path.exists():
            os.chmod(temporary_name, path.stat().st_mode & 0o777)
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


def _read_optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _render_autostart(original: bytes | None) -> bytes:
    """Validate without reserializing Unreal's comments, arrays or duplicate keys.

    Unreal merges repeated sections and the last scalar assignment wins. Append
    only our four scalar overrides when necessary, retaining every original byte.
    """
    contents = original or b""
    text = contents.decode("utf-8-sig")
    parser = configparser.RawConfigParser(strict=False, delimiters=("=",), default_section="\0")
    parser.optionxform = str.casefold
    # Unreal section names are case-insensitive; DEFAULT is an ordinary section.
    validation_text = re.sub(r"(?m)^([ \t]*\[)([^\]\r\n]+)(\])", lambda match: match[0].casefold(), text)
    parser.read_string(validation_text)
    # A later Unreal array/remove command can invalidate an earlier scalar value;
    # ConfigParser alone would consider those to be unrelated option names.
    pending_commands = set()
    scalar_names = {name.casefold() for name in _AUTOSTART_SETTINGS}
    section_name = ""
    for line in validation_text.splitlines():
        stripped = line.strip()
        header = parser.SECTCRE.match(stripped)
        if header:
            section_name = header.group("header")
        elif section_name == _MCP_SECTION.casefold() and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().casefold()
            scalar = key.lstrip("+-.!")
            if scalar in scalar_names:
                if scalar != key:
                    pending_commands.add(scalar)
                else:
                    pending_commands.discard(scalar)
    if not pending_commands and parser.has_section(_MCP_SECTION.casefold()) and all(
        parser.get(_MCP_SECTION.casefold(), key, fallback=None) == value for key, value in _AUTOSTART_SETTINGS.items()
    ):
        return contents

    newline = "\r\n" if "\r\n" in text else "\n"
    separator = newline if not text or text.endswith(("\n", "\r")) else newline * 2
    section = newline.join([f"[{_MCP_SECTION}]", *[f"{key}={value}" for key, value in _AUTOSTART_SETTINGS.items()]])
    return contents + (separator + section + newline).encode("utf-8")


def _configure_autostart(config_path: Path) -> bool:
    original = _read_optional_bytes(config_path)
    configured = _render_autostart(original)
    if configured == original:
        return False
    _atomic_write_bytes(config_path, configured)
    return True


def _read_plugin_descriptor(path: Path) -> dict[str, Any]:
    descriptor = json.loads(path.read_bytes().decode("utf-8-sig"))
    if (
        not isinstance(descriptor, dict)
        or type(descriptor.get("FileVersion")) is not int
        or descriptor["FileVersion"] < 1
    ):
        raise ValueError(f"Invalid plugin descriptor (expected an object with FileVersion): {path}")
    return descriptor


def _validate_pcg_dependencies(engine_plugins_dir: Path, project_data: dict[str, Any]) -> list[str]:
    """Preflight the installed PCGToolset's direct requirements without scanning the engine."""
    descriptor = _read_plugin_descriptor(engine_plugins_dir / _PLUGIN_RELATIVE_PATHS["PCGToolset"])
    references = descriptor.get("Plugins", [])
    if not isinstance(references, list) or any(
        not isinstance(ref, dict)
        or not isinstance(ref.get("Name"), str)
        or not ref["Name"].strip()
        or type(ref.get("Enabled")) is not bool
        or ("Optional" in ref and type(ref["Optional"]) is not bool)
        for ref in references
    ):
        raise ValueError("PCGToolset has invalid plugin dependency declarations")
    if not any(ref["Name"] == "PCG" and ref["Enabled"] and not ref.get("Optional", False) for ref in references):
        raise ValueError("The installed PCGToolset descriptor does not declare its required enabled PCG dependency")

    required = list(dict.fromkeys(ref["Name"] for ref in references if ref["Enabled"] and not ref.get("Optional", False)))
    project_plugins = project_data.get("Plugins", [])
    if not isinstance(project_plugins, list):
        raise ValueError("The .uproject Plugins field must be an array")
    for name in required:
        if any(
            isinstance(entry, dict) and entry.get("Name") == name and entry.get("Enabled") is False
            for entry in project_plugins
        ):
            raise ValueError(f"Required PCGToolset dependency {name} is explicitly disabled in the project")
        relative_paths = (
            _PCG_DEPENDENCY_PATHS
            if name == "PCG"
            else (_PLUGIN_RELATIVE_PATHS[name],) if name in _PLUGIN_RELATIVE_PATHS else ()
        )
        installed = [engine_plugins_dir / path for path in relative_paths if (engine_plugins_dir / path).is_file()]
        if len(installed) != 1:
            raise ValueError(f"Cannot verify one installed descriptor for required PCGToolset dependency {name}")
        _read_plugin_descriptor(installed[0])
    return required


class _ConfigurationWriteError(OSError):
    def __init__(self, cause: Exception, rollback_errors: list[dict[str, str]]):
        super().__init__(str(cause))
        self.rollback_errors = rollback_errors


def _write_configuration(changes: list[tuple[Path, bytes | None, bytes]]) -> None:
    attempted: list[tuple[Path, bytes | None]] = []
    try:
        for path, original, configured in changes:
            attempted.append((path, original))
            _atomic_write_bytes(path, configured)
    except Exception as exc:
        rollback_errors = []
        for path, original in reversed(attempted):
            try:
                if _read_optional_bytes(path) == original:
                    continue
                if original is None:
                    path.unlink()
                else:
                    _atomic_write_bytes(path, original)
            except Exception as rollback_exc:
                rollback_errors.append({"path": str(path), "error": str(rollback_exc)})
        raise _ConfigurationWriteError(exc, rollback_errors) from exc


@skill_entry
def prepare_official_mcp(
    include_editor_toolset: bool = True,
    include_niagara_toolsets: bool = False,
    include_pcg_toolset: bool = False,
    **kwargs,
) -> dict:
    """Enable official MCP plugins and autostart for the current project."""
    flags = {
        "include_editor_toolset": include_editor_toolset,
        "include_niagara_toolsets": include_niagara_toolsets,
        "include_pcg_toolset": include_pcg_toolset,
    }
    invalid_flags = [name for name, value in flags.items() if type(value) is not bool]
    if invalid_flags:
        return skill_error(
            "Official MCP include flags must be booleans",
            "invalid_include_flags",
            invalid_flags=invalid_flags,
            possible_solutions=["Use true or false, not strings, numbers, or null, for include flags."],
        )
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
    if include_pcg_toolset:
        plugin_names.append("PCGToolset")

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
        # Snapshot and validate both files before any write, including directory creation.
        project_original = project_file.read_bytes()
        project_data = json.loads(project_original.decode("utf-8-sig"))
        if not isinstance(project_data, dict):
            raise ValueError("The .uproject root must be an object")
        config_path = project_file.parent / "Config" / "DefaultEditorPerProjectUserSettings.ini"
        config_original = _read_optional_bytes(config_path)
        config_contents = _render_autostart(config_original)
        required_dependencies = _validate_pcg_dependencies(engine_plugins_dir, project_data) if include_pcg_toolset else []
        changed_plugins = _upsert_plugins(project_data, plugin_names)
        changes = []
        if changed_plugins:
            project_contents = (json.dumps(project_data, ensure_ascii=False, indent="\t") + "\n").encode("utf-8")
            changes.append((project_file, project_original, project_contents))
        config_changed = config_contents != config_original
        if config_changed:
            changes.append((config_path, config_original, config_contents))
        _write_configuration(changes)
    except _ConfigurationWriteError as exc:
        return skill_error(
            "Failed to configure Epic Unreal MCP; rollback is incomplete"
            if exc.rollback_errors
            else "Failed to configure Epic Unreal MCP; original files were restored",
            "configuration_rollback_failed" if exc.rollback_errors else "configuration_write_failed",
            details=str(exc),
            rollback_complete=not exc.rollback_errors,
            rollback_errors=exc.rollback_errors,
            possible_solutions=["Review the reported files and restore them before retrying."],
        )
    except (OSError, ValueError, configparser.Error) as exc:
        return skill_error(
            "Failed to configure Epic Unreal MCP for this project",
            str(exc),
            possible_solutions=[
                "Check project JSON, editor INI syntax, installed plugin descriptors, and file permissions.",
                "Resolve missing or explicitly disabled PCGToolset dependencies before opting in.",
            ],
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
        required_dependencies=required_dependencies,
        config_changed=config_changed,
        restart_required=restart_required,
        runtime_verified=False,
    )

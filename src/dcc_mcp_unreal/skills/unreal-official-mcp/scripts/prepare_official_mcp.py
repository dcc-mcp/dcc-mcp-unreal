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
    "ToolsetRegistry": Path("Experimental/ToolsetRegistry/ToolsetRegistry.uplugin"),
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
        # Embedded Python's sys.argv is not the complete Editor command line.
        if sys.platform == "linux":
            contents = Path("/proc/self/cmdline").read_bytes()
            if contents and contents.endswith(b"\0"):
                return [os.fsdecode(argument) for argument in contents[:-1].split(b"\0")]
        raise OSError("The complete native Editor command line cannot be verified on this platform")

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
    command_line = get_command_line()
    if not command_line:
        raise OSError("GetCommandLineW could not read the native Editor command line")
    argv = command_line_to_argv(command_line, ctypes.byref(argc))
    if not argv:
        raise OSError("CommandLineToArgvW could not parse the native Editor command line")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        local_free(ctypes.cast(argv, ctypes.c_void_p))


def _validate_port_override(arguments: list[str], server_port: int) -> None:
    """Accept only one unambiguous, matching documented startup override."""
    # Keyword-only paths are not options; nested assignments remain ambiguous.
    candidate = r"^[-/]+ModelContextProtocolPort(?=$|[=\s:])|ModelContextProtocolPort\s*="
    overrides = [argument for argument in arguments[1:] if re.search(candidate, argument, flags=re.IGNORECASE)]
    if not overrides:
        return
    match = re.fullmatch(r"-ModelContextProtocolPort=([0-9]+)", overrides[0], flags=re.IGNORECASE)
    if len(overrides) != 1 or match is None or int(match[1]) != server_port:
        raise ValueError(
            "ModelContextProtocolPort startup override is invalid, ambiguous, or conflicts with server_port"
        )


def _resolve_project_context(arguments: Iterable[str]) -> tuple[Path, Path]:
    raw_arguments = list(arguments)
    if not raw_arguments or not raw_arguments[0]:
        raise ValueError("The native Editor command line is empty")
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


def _autostart_values(contents: bytes) -> dict[str, str | None]:
    """Read this INI's effective scalars, not the engine's merged runtime config."""
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
    return {
        key: parser.get(_MCP_SECTION.casefold(), key, fallback=None) if key.casefold() not in pending_commands else None
        for key in _AUTOSTART_SETTINGS
    }


def _render_autostart(original: bytes | None, server_port: int = 8000) -> bytes:
    """Append only needed scalar overrides, retaining every original INI byte."""
    contents = original or b""
    settings = {**_AUTOSTART_SETTINGS, "ServerPortNumber": str(server_port)}
    if _autostart_values(contents) == settings:
        return contents

    text = contents.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    separator = newline if not text or text.endswith(("\n", "\r")) else newline * 2
    section = newline.join([f"[{_MCP_SECTION}]", *[f"{key}={value}" for key, value in settings.items()]])
    return contents + (separator + section + newline).encode("utf-8")


def _configure_autostart(config_path: Path, server_port: int = 8000) -> bool:
    original = _read_optional_bytes(config_path)
    configured = _render_autostart(original, server_port)
    _write_configuration([(config_path, original, configured)])
    return configured != original


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

    required = list(
        dict.fromkeys(ref["Name"] for ref in references if ref["Enabled"] and not ref.get("Optional", False))
    )
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
            else (_PLUGIN_RELATIVE_PATHS[name],)
            if name in _PLUGIN_RELATIVE_PATHS
            else ()
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


def _write_configuration(configuration: list[tuple[Path, bytes | None, bytes]]) -> dict[Path, bytes]:
    attempted: list[tuple[Path, bytes | None, bytes]] = []
    try:
        for path, original, configured in configuration:
            if _read_optional_bytes(path) != original:
                raise OSError(f"Configuration changed before write: {path}")
            if configured != original:
                attempted.append((path, original, configured))
                _atomic_write_bytes(path, configured)
        verified = {}
        for path, original, configured in configuration:
            actual = _read_optional_bytes(path)
            if actual != configured:
                raise OSError(f"Configuration readback mismatch: {path}")
            verified[path] = actual
        return verified
    except Exception as exc:
        rollback_errors = []
        for path, original, configured in reversed(attempted):
            try:
                current = _read_optional_bytes(path)
                if current == original:
                    continue
                if current != configured:
                    raise OSError("Configuration changed externally; left untouched")
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
    server_port: int = 8000,
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
    if type(server_port) is not int or not 1 <= server_port <= 65535:
        return skill_error(
            "Official MCP server_port must be an integer from 1 to 65535",
            "invalid_server_port",
            possible_solutions=["Specify the intended port explicitly; automatic port selection is not supported."],
        )
    try:
        arguments = _process_arguments()
        _validate_port_override(arguments, server_port)
        project_file, engine_plugins_dir = _resolve_project_context(arguments)
    except (OSError, ValueError) as exc:
        return skill_error(
            "The current Unreal project or MCP port override could not be verified",
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
        config_contents = _render_autostart(config_original, server_port)
        required_dependencies = (
            _validate_pcg_dependencies(engine_plugins_dir, project_data) if include_pcg_toolset else []
        )
        changed_plugins = _upsert_plugins(project_data, plugin_names)
        project_contents = project_original
        if changed_plugins:
            project_contents = (json.dumps(project_data, ensure_ascii=False, indent="\t") + "\n").encode("utf-8")
        config_changed = config_contents != config_original
        verified = _write_configuration(
            [(project_file, project_original, project_contents), (config_path, config_original, config_contents)]
        )
        configured_port = int(_autostart_values(verified[config_path])["ServerPortNumber"])
    except _ConfigurationWriteError as exc:
        return skill_error(
            "Failed to configure Epic Unreal MCP; rollback is incomplete"
            if exc.rollback_errors
            else "Failed to configure Epic Unreal MCP; no owned writes remain",
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

    restart_required = bool(changed_plugins) or config_changed
    configured_endpoint = f"http://127.0.0.1:{configured_port}/mcp"
    message = (
        "Epic Unreal MCP project configuration is ready; restart Unreal Editor to apply plugin or settings changes."
        if restart_required
        else "Epic Unreal MCP project configuration is ready."
    )
    return skill_success(
        message,
        prompt=(
            "Verify the isolated project's ownership, intended port availability and effective loopback binding before "
            "any authorized restart. Then verify the DCC MCP instance and call official_mcp_bridge with "
            f"operation=status, endpoint={configured_endpoint}. Stop on conflicts or unknown ownership/binding."
        ),
        project_file=str(project_file),
        config_file=str(config_path),
        enabled_plugins=plugin_names,
        changed_plugins=changed_plugins,
        required_dependencies=required_dependencies,
        config_changed=config_changed,
        configured_port=configured_port,
        configured_endpoint=configured_endpoint,
        configuration_verified=True,
        restart_required=restart_required,
        runtime_verified=False,
    )

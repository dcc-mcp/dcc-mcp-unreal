"""Agent-first Unreal Engine plugin lifecycle CLI.

The Python entry point owns the project-plugin transaction only. Native
sidecar acquisition stays in the checksummed standalone installer and runtime
handoff stays in :mod:`dcc_mcp_unreal._standalone_entry`.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import unquote, urlsplit

from .__version__ import __version__

try:
    from dcc_mcp_core.deployment import (
        INSTALL_EXIT_ACQUIRE,
        INSTALL_EXIT_INSTALL,
        INSTALL_EXIT_OK,
        INSTALL_EXIT_PREFLIGHT,
        INSTALL_EXIT_REQUIRES_RESTART,
        INSTALL_EXIT_VERIFY,
        INSTALL_SOP_SCHEMA_VERSION,
    )
except ImportError:  # Core PR #2320 compatibility until its foundation ships.
    INSTALL_SOP_SCHEMA_VERSION = 1
    INSTALL_EXIT_OK = 0
    INSTALL_EXIT_PREFLIGHT = 10
    INSTALL_EXIT_ACQUIRE = 20
    INSTALL_EXIT_INSTALL = 30
    INSTALL_EXIT_VERIFY = 40
    INSTALL_EXIT_REQUIRES_RESTART = 50


DCC_TYPE = "unreal"
PLUGIN_NAME = "DccMcpUnreal"
MIN_CORE_VERSION = "0.20.13"
MIN_HOST_VERSION = (4, 18, 0)
RECEIPT_SCHEMA_VERSION = 1
MAX_VERSION_LENGTH = 64
MAX_VERSION_COMPONENT = 999999
MAX_PROBE_OUTPUT_BYTES = 64 * 1024
MAX_EDITOR_BYTES = 4 * 1024 * 1024 * 1024
MAX_TRANSACTION_SNAPSHOT_BYTES = 8 * 1024 * 1024
_VERSION_RE = re.compile(r"(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})")


class LifecycleError(RuntimeError):
    """Failure with a stable Install SOP exit/stage classification."""

    def __init__(self, message: str, *, exit_code: int, stage: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stage = stage


def _core_version() -> str:
    try:
        return metadata.version("dcc-mcp-core")
    except metadata.PackageNotFoundError:
        return "unknown"


def _version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_VERSION_LENGTH or _VERSION_RE.fullmatch(value) is None:
        raise ValueError("version must be a bounded canonical three-component final version")
    parsed = tuple(int(component) for component in value.split("."))
    if any(component > MAX_VERSION_COMPONENT for component in parsed):
        raise ValueError("version must be a bounded canonical three-component final version")
    return parsed


def _project_association_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_VERSION_LENGTH:
        raise ValueError("Project EngineAssociation is not a bounded numeric version")
    if re.fullmatch(r"(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){0,2}", value) is None:
        raise ValueError("Project EngineAssociation is not a bounded numeric version")
    components = [int(component) for component in value.split(".")]
    if any(component > MAX_VERSION_COMPONENT for component in components):
        raise ValueError("Project EngineAssociation is not a bounded numeric version")
    padded = components + [0, 0]
    return padded[0], padded[1], padded[2]


def _run_bounded_probe(command: Sequence[str], *, timeout: float = 15.0) -> dict[str, Any]:
    """Run one read-only child probe with bounded time and captured output."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
        try:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=creationflags,
            )
        except OSError as exc:
            return {"success": False, "reason": f"launch failed: {exc.__class__.__name__}"}
        try:
            process.wait(timeout=max(0.1, min(float(timeout), 30.0)))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
            return {"success": False, "reason": "probe timed out"}
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(MAX_PROBE_OUTPUT_BYTES + 1)
        stderr = stderr_file.read(MAX_PROBE_OUTPUT_BYTES + 1)
    return {
        "success": process.returncode == 0,
        "returncode": int(process.returncode or 0),
        "stdout": stdout[:MAX_PROBE_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr": stderr[:MAX_PROBE_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(stdout) > MAX_PROBE_OUTPUT_BYTES or len(stderr) > MAX_PROBE_OUTPUT_BYTES,
    }


def _engine_root(value: str) -> Path:
    candidate = Path(value).expanduser().resolve()
    if candidate.is_file():
        for parent in candidate.parents:
            if (parent / "Engine" / "Build" / "Build.version").is_file():
                return parent
    return candidate


def _engine_version(engine_root: Path) -> str:
    build_version = engine_root / "Engine" / "Build" / "Build.version"
    data = json.loads(build_version.read_text(encoding="utf-8-sig"))
    components = [data[key] for key in ("MajorVersion", "MinorVersion", "PatchVersion")]
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_VERSION_COMPONENT
        for value in components
    ):
        raise ValueError("Unreal Build.version contains a noncanonical version")
    version = ".".join(str(value) for value in components)
    _version_tuple(version)
    return version


def _discover_engine_root(override: Optional[str]) -> tuple[Path, str]:
    if override:
        return _engine_root(override), "flag"
    configured = os.environ.get("UE_ROOT")
    if configured:
        return _engine_root(configured), "environment"
    search_roots = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Epic Games",
        Path("/Users/Shared/Epic Games"),
        Path("/opt"),
    ]
    candidates: list[tuple[tuple[int, ...], Path]] = []
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for pattern in ("UE_*", "UnrealEngine*"):
            for candidate in search_root.glob(pattern):
                try:
                    version = _engine_version(candidate)
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue
                candidates.append((_version_tuple(version), candidate.resolve()))
    if not candidates:
        raise ValueError("No Unreal Engine installation was found; pass --dcc-path with the exact engine root")
    return max(candidates, key=lambda item: item[0])[1], "discovery"


def _project_file(value: str) -> Path:
    candidate = Path(value).expanduser().resolve()
    if candidate.is_file() and candidate.suffix.lower() == ".uproject":
        return candidate
    matches = sorted(candidate.glob("*.uproject")) if candidate.is_dir() else []
    if len(matches) == 1:
        return matches[0].resolve()
    raise ValueError("--project must identify one .uproject file")


def _embedded_python(engine_root: Path) -> Optional[Path]:
    candidates = (
        engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Win64" / "python.exe",
        engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Mac" / "bin" / "python3",
        engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Linux" / "bin" / "python3",
    )
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _resolve_python(args: argparse.Namespace, engine_root: Path) -> tuple[Path, str]:
    if args.python:
        return Path(args.python).expanduser().resolve(), "flag"
    configured = os.environ.get("DCC_MCP_INSTALL_PYTHON")
    if configured:
        return Path(configured).expanduser().resolve(), "environment"
    discovered = _embedded_python(engine_root)
    if discovered is not None:
        return discovered, "host"
    raise ValueError("No Unreal target interpreter was found; pass --python with the exact executable")


def _target_runtime(python_path: Path) -> dict[str, str]:
    probe = r"""
import importlib.metadata as m
import json
import pathlib
import sys
import dcc_mcp_core as core
import dcc_mcp_unreal as adapter

def identity(distribution_name, module):
    distribution = m.distribution(distribution_name)
    files = tuple(distribution.files or ())
    owned = {str(pathlib.Path(distribution.locate_file(item)).resolve()): str(item) for item in files}
    origin = pathlib.Path(module.__file__).resolve()
    direct_url_text = distribution.read_text("direct_url.json")
    return {
        "version": distribution.version,
        "module_version": getattr(module, "__version__", None),
        "origin": str(origin),
        "distribution_root": str(pathlib.Path(distribution.locate_file("")).resolve()),
        "record": owned.get(str(origin)),
        "direct_url": json.loads(direct_url_text) if direct_url_text else None,
    }

print(json.dumps({
    "python_executable": str(pathlib.Path(sys.executable).resolve()),
    "python_version": ".".join(map(str, sys.version_info[:3])),
    "adapter": identity("dcc-mcp-unreal", adapter),
    "core": identity("dcc-mcp-core", core),
}))
""".strip()
    completed = _run_bounded_probe([str(python_path), "-c", probe])
    if not completed.get("success") or completed.get("truncated"):
        error_lines = str(completed.get("stderr") or completed.get("reason") or "").strip().splitlines()
        diagnostic = error_lines[-1] if error_lines else "import probe failed"
        raise ValueError(f"Target interpreter cannot import the adapter and Core: {diagnostic}")
    try:
        runtime = json.loads(str(completed.get("stdout") or ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Target interpreter returned an invalid import probe") from exc
    if not isinstance(runtime, dict):
        raise ValueError("Target interpreter returned an invalid import probe")
    adapter = runtime.get("adapter")
    core = runtime.get("core")
    if not isinstance(adapter, dict) or not isinstance(core, dict):
        # Preserve an actionable version-floor result for old synthetic probes.
        core_version = str(runtime.get("core_version", "unknown"))
        try:
            if _version_tuple(core_version) < _version_tuple(MIN_CORE_VERSION):
                raise ValueError(f"Target interpreter has dcc-mcp-core {core_version}; {MIN_CORE_VERSION}+ is required")
        except ValueError as exc:
            if "required" in str(exc):
                raise
        raise ValueError("Target interpreter returned an invalid distribution identity probe")
    adapter_version = str(adapter.get("version") or "unknown")
    module_version = str(adapter.get("module_version") or "unknown")
    if adapter_version != __version__ or module_version != __version__:
        raise ValueError(
            f"Target interpreter has dcc-mcp-unreal {adapter_version}/{module_version}, expected {__version__}"
        )
    core_version = str(core.get("version") or "unknown")
    if _version_tuple(core_version) < _version_tuple(MIN_CORE_VERSION):
        raise ValueError(f"Target interpreter has dcc-mcp-core {core_version}; {MIN_CORE_VERSION}+ is required")
    python_version = str(runtime.get("python_version") or "unknown")
    _version_tuple(python_version)
    if Path(str(runtime.get("python_executable") or "")).resolve() != python_path.resolve():
        raise ValueError("Target interpreter identity changed during the import probe")
    adapter_origin = _owned_module_origin(adapter, "dcc-mcp-unreal", "dcc_mcp_unreal")
    core_origin = _owned_module_origin(core, "dcc-mcp-core", "dcc_mcp_core")
    return {
        "python_executable": str(python_path.resolve()),
        "python_version": python_version,
        "adapter_version": adapter_version,
        "core_version": core_version,
        "adapter_origin": adapter_origin,
        "core_origin": core_origin,
        "adapter_distribution_root": str(Path(str(adapter["distribution_root"])).resolve()),
        "core_distribution_root": str(Path(str(core["distribution_root"])).resolve()),
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _editable_root(value: object) -> Optional[Path]:
    if not isinstance(value, dict) or not isinstance(value.get("dir_info"), dict):
        return None
    url = value.get("url")
    if value["dir_info"].get("editable") is not True or not isinstance(url, str) or not 0 < len(url) <= 2048:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.query or parsed.fragment:
        return None
    raw_path = unquote(parsed.path)
    if re.fullmatch(r"/[A-Za-z]:/.*", raw_path):
        raw_path = raw_path[1:]
    root = Path(raw_path).resolve()
    return root if root.is_dir() else None


def _owned_module_origin(identity: dict[str, Any], distribution: str, package: str) -> str:
    origin = Path(str(identity.get("origin") or "")).resolve()
    root = Path(str(identity.get("distribution_root") or "")).resolve()
    record = identity.get("record")
    valid = (
        origin.is_file()
        and origin.stat().st_size > 0
        and origin.name == "__init__.py"
        and origin.parent.name == package
    )
    if not valid or not root.is_dir():
        raise ValueError(f"{distribution} module origin is missing or unloadable")
    if isinstance(record, str) and 0 < len(record) <= 1024:
        if (root / record).resolve() != origin or not _is_within(origin, root):
            raise ValueError(f"{distribution} module origin is outside distribution ownership")
    else:
        editable = _editable_root(identity.get("direct_url"))
        candidates = () if editable is None else (editable / "src" / package, editable / package)
        if not any(origin == (candidate / "__init__.py").resolve() for candidate in candidates):
            raise ValueError(f"{distribution} module origin is not owned by its distribution")
    return str(origin)


def _plugin_source() -> tuple[Path, str]:
    packaged = Path(__file__).resolve().parent / "_plugin"
    source_checkout = Path(__file__).resolve().parents[2] / "unreal" / "plugin"
    if (packaged / "DccMcpUnreal.uplugin").is_file():
        return packaged, "wheel"
    if (source_checkout / "DccMcpUnreal.uplugin").is_file():
        return source_checkout, "source-checkout"
    raise LifecycleError(
        "The installed wheel does not contain the Unreal plugin payload",
        exit_code=INSTALL_EXIT_ACQUIRE,
        stage="acquire",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_manifest(root: Path) -> list[dict[str, Any]]:
    """Describe every owned directory, file, and bounded relative symlink."""
    manifest: list[dict[str, Any]] = []
    if not root.is_dir():
        return manifest
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in list(directory_names):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                directory_names.remove(name)
                manifest.append(_link_manifest(path, relative, root))
            else:
                manifest.append({"path": relative, "type": "directory"})
        for name in file_names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                manifest.append(_link_manifest(path, relative, root))
            elif path.is_file():
                size = path.stat().st_size
                manifest.append({"path": relative, "type": "file", "size": size, "sha256": _sha256(path)})
            else:
                raise ValueError(f"unsupported plugin path type: {relative}")
    return sorted(manifest, key=lambda item: str(item["path"]))


def _link_manifest(path: Path, relative: str, root: Path) -> dict[str, Any]:
    target = os.readlink(path)
    if not target or len(target) > 4096 or os.path.isabs(target):
        raise ValueError(f"unsafe plugin symlink: {relative}")
    resolved = (path.parent / target).resolve()
    if not _is_within(resolved, root.resolve()):
        raise ValueError(f"plugin symlink escapes the managed root: {relative}")
    return {"path": relative, "type": "symlink", "target": target}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _plugin_entry(project: dict[str, Any]) -> Optional[dict[str, Any]]:
    for entry in project.get("Plugins", []):
        if isinstance(entry, dict) and entry.get("Name") == PLUGIN_NAME:
            return dict(entry)
    return None


def _set_plugin_entry(project: dict[str, Any], entry: Optional[dict[str, Any]]) -> None:
    plugins = [
        item for item in project.get("Plugins", []) if not (isinstance(item, dict) and item.get("Name") == PLUGIN_NAME)
    ]
    if entry is not None:
        plugins.append(entry)
    if plugins:
        project["Plugins"] = plugins
    else:
        project.pop("Plugins", None)


def _read_receipt(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        receipt = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return None
    return receipt


def _manifest_matches(plugin_root: Path, receipt: dict[str, Any]) -> tuple[bool, str, bool]:
    expected = receipt.get("ownership")
    if not isinstance(expected, list):
        return False, "receipt ownership manifest is missing", False
    if any(not isinstance(item, dict) or not isinstance(item.get("path"), str) for item in expected):
        return False, "receipt ownership manifest is invalid", False
    expected_paths = {str(item["path"]): item for item in expected}
    if len(expected_paths) != len(expected):
        return False, "receipt ownership manifest contains duplicate paths", False
    try:
        actual_manifest = _file_manifest(plugin_root)
    except (OSError, ValueError) as exc:
        return False, str(exc), False
    actual = {str(item["path"]): item for item in actual_manifest}
    unreceipted = sorted(set(actual) - set(expected_paths))
    if unreceipted:
        return False, f"plugin contains unreceipted paths: {', '.join(unreceipted)}", True
    if expected_paths != actual:
        return False, "installed plugin paths differ from the receipt", False
    return True, "", False


def _inspect_state(context: dict[str, Any]) -> tuple[str, Optional[dict[str, Any]], Optional[str]]:
    plugin_root: Path = context["plugin_root"]
    receipt_path: Path = context["receipt_path"]
    plugin_exists = plugin_root.is_dir()
    receipt_exists = receipt_path.is_file()
    if not plugin_exists and not receipt_exists:
        return "fresh", None, None
    if plugin_exists != receipt_exists:
        return "partial", None, "plugin and receipt presence do not match"
    receipt = _read_receipt(receipt_path)
    if receipt is None:
        return "partial", None, "the install receipt is invalid"
    if receipt.get("plugin_root") != str(plugin_root) or receipt.get("project_file") != str(context["project_file"]):
        return "partial", receipt, "the receipt identifies another project or plugin root"
    if receipt.get("engine") != {
        "root": str(context["engine_root"]),
        "version": context["engine_version"],
        "editor": context["editor"],
    }:
        return "partial", receipt, "the receipt identifies another Unreal engine or editor"
    if receipt.get("target_runtime") != context["runtime"]:
        return "partial", receipt, "the receipt identifies another target Python runtime"
    matches, reason, has_unreceipted_files = _manifest_matches(plugin_root, receipt)
    if not matches:
        if has_unreceipted_files:
            return "partial", receipt, reason
        return "repair", receipt, reason
    if receipt.get("adapter_version") != __version__:
        return "upgrade", receipt, None
    return "current", receipt, None


def _failure_next_step(args: argparse.Namespace, stage: str) -> dict[str, Any]:
    command = ["dcc-mcp-unreal", args.verb, "--json"]
    if args.dcc_path:
        command.extend(["--dcc-path", str(Path(args.dcc_path).expanduser().resolve())])
    if args.python:
        command.extend(["--python", str(Path(args.python).expanduser().resolve())])
    if args.project:
        command.extend(["--project", str(Path(args.project).expanduser().resolve())])
    if args.instance_id:
        command.extend(["--instance-id", args.instance_id])
    return {
        "id": f"retry-{stage}",
        "description": f"Retry {args.verb} after correcting the reported {stage} failure.",
        "command": command,
        "why": f"The {stage} contract failed before the operation could complete.",
    }


def _editor_executable(engine_root: Path) -> Optional[Path]:
    if sys.platform == "win32":
        candidates = (
            engine_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe",
            engine_root / "Engine" / "Binaries" / "Win64" / "UE4Editor.exe",
        )
    elif sys.platform == "darwin":
        candidates = (
            engine_root / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" / "Contents" / "MacOS" / "UnrealEditor",
            engine_root / "Engine" / "Binaries" / "Mac" / "UE4Editor.app" / "Contents" / "MacOS" / "UE4Editor",
        )
    else:
        candidates = (
            engine_root / "Engine" / "Binaries" / "Linux" / "UnrealEditor",
            engine_root / "Engine" / "Binaries" / "Linux" / "UE4Editor",
        )
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _editor_identity(engine_root: Path) -> dict[str, Any]:
    editor = _editor_executable(engine_root)
    if editor is None:
        raise ValueError("The selected Unreal Engine root has no editor executable")
    size = editor.stat().st_size
    if not 0 < size <= MAX_EDITOR_BYTES:
        raise ValueError("The selected Unreal editor executable is empty or unbounded")
    with editor.open("rb") as stream:
        magic = stream.read(4)
    native = (
        magic.startswith(b"MZ")
        or magic == b"\x7fELF"
        or magic
        in {
            b"\xfe\xed\xfa\xce",
            b"\xfe\xed\xfa\xcf",
            b"\xce\xfa\xed\xfe",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
        }
    )
    if not native:
        raise ValueError("The selected Unreal editor executable is not a loadable native image")
    return {"path": str(editor), "size": size, "sha256": _sha256(editor)}


def _readiness_next_step(args: argparse.Namespace, context: dict[str, Any]) -> dict[str, Any]:
    editor = _editor_executable(context["engine_root"])
    if editor is None:
        return _failure_next_step(args, "readiness")
    return {
        "id": "launch-unreal-editor",
        "description": "Launch the selected Unreal Editor project so its DCC MCP plugin can become ready.",
        "command": [str(editor), str(context["project_file"])],
        "why": "The installed plugin passed static checks, but no typed Unreal readiness probe succeeded.",
    }


def _result(
    *,
    status: str,
    steps: list[dict[str, Any]],
    next_steps: list[dict[str, Any]],
    receipt_path: Optional[Path],
    verify: Optional[dict[str, Any]] = None,
    **extra: Any,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": INSTALL_SOP_SCHEMA_VERSION,
        "status": status,
        "dcc_type": DCC_TYPE,
        "adapter_version": __version__,
        "core_version": _core_version(),
        "steps": steps,
        "next_steps": next_steps,
        "receipt_path": str(receipt_path) if receipt_path is not None else None,
        "verify": verify or {"directly_usable": False, "failure_stage": None, "failure_reason": None},
    }
    document.update(extra)
    return document


def _resolve_context(args: argparse.Namespace) -> dict[str, Any]:
    cli_core_version = _core_version()
    if _version_tuple(cli_core_version) < _version_tuple(MIN_CORE_VERSION):
        raise ValueError(f"Lifecycle CLI has dcc-mcp-core {cli_core_version}; {MIN_CORE_VERSION}+ is required")
    engine_root, engine_source = _discover_engine_root(args.dcc_path)
    engine_version = _engine_version(engine_root)
    if _version_tuple(engine_version) < MIN_HOST_VERSION:
        raise ValueError(f"Unreal Engine {engine_version} is unsupported; 4.18+ is required")
    editor = _editor_identity(engine_root)
    project_file = _project_file(args.project)
    project = _read_json(project_file)
    association = str(project.get("EngineAssociation") or "").strip()
    if association:
        associated_version = _project_association_tuple(association)
        selected_version = _version_tuple(engine_version)
        if associated_version[:2] != selected_version[:2]:
            raise ValueError(
                f"Project EngineAssociation {association} does not match selected Unreal Engine {engine_version}"
            )
    python_path, python_source = _resolve_python(args, engine_root)
    if not python_path.is_file():
        raise ValueError("The selected target interpreter does not exist")
    runtime = _target_runtime(python_path)
    instance_id = str(uuid.UUID(args.instance_id)) if args.instance_id else None
    plugin_root = project_file.parent / "Plugins" / PLUGIN_NAME
    receipt_path = project_file.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    return {
        "engine_root": engine_root,
        "engine_version": engine_version,
        "engine_source": engine_source,
        "editor_path": Path(editor["path"]),
        "editor": editor,
        "project_file": project_file,
        "project": project,
        "python_path": python_path,
        "python_source": python_source,
        "runtime": runtime,
        "instance_id": instance_id,
        "plugin_root": plugin_root,
        "receipt_path": receipt_path,
        "bootstrap_log_dir": project_file.parent / ".dcc-mcp" / "bootstrap-errors",
    }


def _context_fields(context: dict[str, Any], install_state: str) -> dict[str, Any]:
    return {
        "host": {
            "path": str(context["engine_root"]),
            "version": context["engine_version"],
            "source": context["engine_source"],
        },
        "target_python": {
            "path": str(context["python_path"]),
            "version": context["runtime"]["python_version"],
            "source": context["python_source"],
        },
        "project": {"path": str(context["project_file"])},
        "install_state": install_state,
    }


def _preflight(args: argparse.Namespace) -> tuple[Optional[dict[str, Any]], Optional[tuple[int, dict[str, Any]]]]:
    try:
        context = _resolve_context(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        reason = str(exc)
        document = _result(
            status="failed",
            steps=[{"id": "preflight", "status": "failed", "message": reason}],
            next_steps=[_failure_next_step(args, "preflight")],
            receipt_path=None,
            verify={"directly_usable": False, "failure_stage": "preflight", "failure_reason": reason},
        )
        return None, (INSTALL_EXIT_PREFLIGHT, document)
    return context, None


def _next_command(args: argparse.Namespace, context: dict[str, Any], *, verb: Optional[str] = None) -> list[str]:
    command = [
        "dcc-mcp-unreal",
        verb or args.verb,
        "--json",
        "--yes",
        "--dcc-path",
        str(context["engine_root"]),
        "--python",
        str(context["python_path"]),
        "--project",
        str(context["project_file"]),
    ]
    if context["instance_id"]:
        command.extend(["--instance-id", context["instance_id"]])
    return command


def _plan(
    args: argparse.Namespace, context: dict[str, Any], state: str, state_reason: Optional[str]
) -> tuple[int, dict[str, Any]]:
    if state == "partial":
        reason = state_reason or "the existing install is incomplete"
        return INSTALL_EXIT_PREFLIGHT, _result(
            status="partial",
            steps=[{"id": "preflight", "status": "failed", "message": reason}],
            next_steps=[_failure_next_step(args, "partial-state")],
            receipt_path=context["receipt_path"],
            verify={"directly_usable": False, "failure_stage": "preflight", "failure_reason": reason},
            **_context_fields(context, state),
        )
    steps = [
        {"id": "preflight", "status": "ok"},
        {"id": "stage-plugin", "status": "planned"},
        {"id": "enable-plugin", "status": "planned"},
        {"id": "write-receipt", "status": "planned"},
        {"id": "verify", "status": "planned"},
    ]
    next_steps = [
        {
            "id": f"execute-{args.verb}",
            "description": f"Execute the validated Unreal {args.verb} plan.",
            "command": _next_command(args, context),
            "why": f"The plan is valid but {'dry-run' if args.dry_run else 'planning'} never mutates the project.",
        }
    ]
    return INSTALL_EXIT_OK, _result(
        status="planned",
        steps=steps,
        next_steps=next_steps,
        receipt_path=context["receipt_path"],
        **_context_fields(context, state),
    )


def _write_receipt(
    context: dict[str, Any],
    previous_entry: Optional[dict[str, Any]],
    provenance: str,
    runtime_identity: Optional[dict[str, Any]] = None,
    transaction: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    installed_entry = _plugin_entry(_read_json(context["project_file"]))
    project_bytes = context["project_file"].read_bytes()
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "adapter_version": __version__,
        "dcc_type": DCC_TYPE,
        "dcc_version": context["engine_version"],
        "engine_root": str(context["engine_root"]),
        "project_file": str(context["project_file"]),
        "plugin_root": str(context["plugin_root"]),
        "target_python": str(context["python_path"]),
        "target_python_version": context["runtime"]["python_version"],
        "core_version": context["runtime"]["core_version"],
        "engine": {
            "root": str(context["engine_root"]),
            "version": context["engine_version"],
            "editor": context["editor"],
        },
        "target_runtime": context["runtime"],
        "ownership": _file_manifest(context["plugin_root"]),
        "registration": {
            "previous_plugin_entry": previous_entry,
            "installed_plugin_entry": installed_entry,
            "installed_project_sha256": _sha256_bytes(project_bytes),
        },
        "instance_selector": context["instance_id"],
        "runtime_identity": runtime_identity,
        "transaction": transaction,
        "bootstrap_log_dir": str(context["bootstrap_log_dir"]),
        "sidecar": {
            "runtime_handoff": "dcc-mcp-server sidecar --dcc unreal",
            "readiness_probe": "unreal_automation__mcp_self_check",
        },
        "payload_provenance": provenance,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(context["receipt_path"], receipt)
    return receipt


def _encode_snapshot(value: Optional[bytes]) -> Optional[str]:
    if value is None:
        return None
    if len(value) > MAX_TRANSACTION_SNAPSHOT_BYTES:
        raise LifecycleError(
            "The prior project transaction snapshot is too large",
            exit_code=INSTALL_EXIT_INSTALL,
            stage="install",
        )
    return base64.b64encode(value).decode("ascii")


def _decode_snapshot(value: object) -> Optional[bytes]:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > (MAX_TRANSACTION_SNAPSHOT_BYTES * 4 // 3) + 8:
        raise LifecycleError(
            "The pending transaction snapshot is invalid", exit_code=INSTALL_EXIT_INSTALL, stage="verify"
        )
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise LifecycleError(
            "The pending transaction snapshot is invalid", exit_code=INSTALL_EXIT_INSTALL, stage="verify"
        ) from exc
    if len(decoded) > MAX_TRANSACTION_SNAPSHOT_BYTES:
        raise LifecycleError(
            "The pending transaction snapshot is invalid", exit_code=INSTALL_EXIT_INSTALL, stage="verify"
        )
    return decoded


def _pending_backup(context: dict[str, Any], receipt: dict[str, Any]) -> Optional[Path]:
    transaction = receipt.get("transaction")
    if transaction is None:
        return None
    if not isinstance(transaction, dict) or transaction.get("state") != "awaiting-bound-verify":
        raise LifecycleError(
            "The pending transaction receipt is invalid", exit_code=INSTALL_EXIT_INSTALL, stage="verify"
        )
    raw = transaction.get("backup_plugin")
    backup = Path(str(raw or "")).resolve()
    parent = context["plugin_root"].parent.resolve()
    if backup.parent != parent or not backup.name.startswith(f".{PLUGIN_NAME}.backup-") or not backup.is_dir():
        raise LifecycleError(
            "The pending transaction backup is missing or unsafe", exit_code=INSTALL_EXIT_INSTALL, stage="verify"
        )
    return backup


def _rollback_pending(context: dict[str, Any], receipt: dict[str, Any]) -> None:
    backup = _pending_backup(context, receipt)
    if backup is None:
        return
    transaction = receipt["transaction"]
    old_project = _decode_snapshot(transaction.get("previous_project"))
    old_receipt = _decode_snapshot(transaction.get("previous_receipt"))
    if old_project is None:
        raise LifecycleError("The pending project snapshot is missing", exit_code=INSTALL_EXIT_INSTALL, stage="verify")
    plugin_root: Path = context["plugin_root"]
    if plugin_root.exists():
        _remove_tree(plugin_root)
    os.replace(backup, plugin_root)
    context["project_file"].write_bytes(old_project)
    receipt_path: Path = context["receipt_path"]
    if old_receipt is None:
        receipt_path.unlink(missing_ok=True)
    else:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_bytes(old_receipt)


def _finalize_pending(context: dict[str, Any], receipt: dict[str, Any], identity: dict[str, Any]) -> None:
    backup = _pending_backup(context, receipt)
    finalized = dict(receipt)
    finalized["runtime_identity"] = identity
    finalized["transaction"] = None
    _atomic_json(context["receipt_path"], finalized)
    if backup is not None:
        _remove_tree(backup)


def _readiness_identity(
    args: argparse.Namespace,
    context: dict[str, Any],
    receipt: dict[str, Any],
    readiness: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Validate that a typed probe belongs to the exact selected editor instance."""
    selector = context.get("instance_id")
    if not selector:
        return None, "an exact --instance-id is required before the install can be directly usable"
    if readiness.get("success") is not True or readiness.get("ready") is not True:
        reason = readiness.get("message") or readiness.get("recommended_next_action") or readiness
        return None, str(reason)
    entry = readiness.get("entry")
    probe = readiness.get("probe")
    if not isinstance(entry, dict) or entry.get("instance_id") != selector:
        return None, "readiness entry instance_id does not match the selected instance"
    entry_pid = entry.get("parent_pid")
    if isinstance(entry_pid, bool) or not isinstance(entry_pid, int) or not 0 < entry_pid <= 2**31 - 1:
        return None, "readiness entry parent_pid is invalid"
    if not isinstance(probe, dict) or probe.get("success") is not True:
        return None, "the selected instance did not return a successful typed readiness probe"
    result = probe.get("result")
    probe_context = result.get("context") if isinstance(result, dict) and result.get("success") is True else None
    identity = probe_context.get("install_identity") if isinstance(probe_context, dict) else None
    if not isinstance(identity, dict):
        return None, "typed readiness probe is missing context.install_identity"

    expected = {
        "instance_id": selector,
        "host_pid": entry_pid,
        "editor_executable": str(context["editor_path"]),
        "project_file": str(context["project_file"]),
        "plugin_root": str(context["plugin_root"]),
        "engine_version": context["engine_version"],
        "adapter_version": __version__,
        "core_version": context["runtime"]["core_version"],
        "adapter_origin": context["runtime"]["adapter_origin"],
        "core_origin": context["runtime"]["core_origin"],
    }
    for field, expected_value in expected.items():
        actual = identity.get(field)
        if field in {"editor_executable", "project_file", "plugin_root", "adapter_origin", "core_origin"}:
            try:
                matches = Path(str(actual)).resolve() == Path(str(expected_value)).resolve()
            except (OSError, ValueError):
                matches = False
        else:
            matches = actual == expected_value
        if not matches:
            return None, f"typed readiness {field} does not match the selected install"
    token = identity.get("process_start_token")
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", token) is None:
        return None, "typed readiness process_start_token is missing or invalid"
    previous = receipt.get("runtime_identity")
    if previous is not None and previous != identity:
        return None, "typed readiness identity changed from the receipted editor process"
    if receipt.get("instance_selector") not in {None, selector}:
        return None, "receipt instance selector does not match the selected instance"
    return dict(identity), None


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    from dcc_mcp_core import safe_remove_tree

    outcome = safe_remove_tree(path)
    if not outcome.get("success"):
        raise OSError(str(outcome.get("recommended_next_action") or outcome))


def _inspect_locks(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    from dcc_mcp_core import inspect_install_root

    outcome = inspect_install_root(path)
    if outcome.get("requires_restart"):
        return str(outcome.get("locked_path") or "loaded native plugin artifact")
    return None


def _install(
    args: argparse.Namespace, context: dict[str, Any], state: str, receipt: Optional[dict[str, Any]]
) -> tuple[int, dict[str, Any]]:
    if state == "current":
        return _verify(args, context, state, receipt)
    source, provenance = _plugin_source()
    plugin_root: Path = context["plugin_root"]
    plugin_parent = plugin_root.parent
    plugin_parent.mkdir(parents=True, exist_ok=True)
    lock_reason = _inspect_locks(plugin_root)
    if lock_reason:
        reason = f"Unreal has loaded a plugin artifact: {lock_reason}"
        return INSTALL_EXIT_REQUIRES_RESTART, _result(
            status="requires_restart",
            steps=[{"id": "preflight", "status": "failed", "message": reason}],
            next_steps=[_failure_next_step(args, "requires-restart")],
            receipt_path=context["receipt_path"],
            verify={"directly_usable": False, "failure_stage": "install", "failure_reason": reason},
            **_context_fields(context, state),
        )

    staging = plugin_parent / f".{PLUGIN_NAME}.staging-{uuid.uuid4().hex}"
    backup = plugin_parent / f".{PLUGIN_NAME}.backup-{uuid.uuid4().hex}"
    receipt_path: Path = context["receipt_path"]
    old_receipt = receipt_path.read_bytes() if receipt_path.is_file() else None
    project_file: Path = context["project_file"]
    old_project_bytes = project_file.read_bytes()
    project = _read_json(project_file)
    previous_entry = receipt.get("registration", {}).get("previous_plugin_entry") if receipt else _plugin_entry(project)
    installed_entry = _plugin_entry(project) or {"Name": PLUGIN_NAME}
    installed_entry["Enabled"] = True
    moved_previous = False
    committed = False
    preserve_backup = False
    verification: Optional[tuple[int, dict[str, Any]]] = None
    try:
        shutil.copytree(source, staging)
        if not (staging / "DccMcpUnreal.uplugin").is_file():
            raise LifecycleError(
                "Staged payload is missing DccMcpUnreal.uplugin",
                exit_code=INSTALL_EXIT_ACQUIRE,
                stage="acquire",
            )
        descriptor_version = str(_read_json(staging / "DccMcpUnreal.uplugin").get("VersionName") or "")
        if descriptor_version != __version__:
            raise LifecycleError(
                f"Staged plugin version {descriptor_version or 'unknown'} does not match adapter {__version__}",
                exit_code=INSTALL_EXIT_ACQUIRE,
                stage="acquire",
            )
        if plugin_root.exists():
            os.replace(plugin_root, backup)
            moved_previous = True
        os.replace(staging, plugin_root)
        _set_plugin_entry(project, installed_entry)
        _atomic_json(project_file, project)
        pending_transaction = None
        if moved_previous and not context["instance_id"]:
            pending_transaction = {
                "state": "awaiting-bound-verify",
                "backup_plugin": str(backup),
                "previous_project": _encode_snapshot(old_project_bytes),
                "previous_receipt": _encode_snapshot(old_receipt),
            }
        new_receipt = _write_receipt(context, previous_entry, provenance, transaction=pending_transaction)
        new_state, new_receipt, _ = _inspect_state(context)
        verification = _verify(args, context, new_state, new_receipt)
        verify_code, _ = verification
        if verify_code == INSTALL_EXIT_OK:
            runtime_identity = context.pop("_verified_runtime_identity", None)
            _write_receipt(context, previous_entry, provenance, runtime_identity)
            committed = True
        elif not context["instance_id"]:
            # A host that is not yet running cannot provide its instance UUID.
            # Preserve the static install, but keep directly_usable=false and
            # require the exact selector on the executable verify command.
            committed = True
            preserve_backup = pending_transaction is not None
    except LifecycleError:
        raise
    except PermissionError as exc:
        raise LifecycleError(
            f"A loaded Unreal plugin artifact requires restart: {exc}",
            exit_code=INSTALL_EXIT_REQUIRES_RESTART,
            stage="install",
        ) from exc
    except OSError as exc:
        raise LifecycleError(
            f"Plugin transaction failed: {exc}", exit_code=INSTALL_EXIT_INSTALL, stage="install"
        ) from exc
    finally:
        if not committed:
            if plugin_root.exists():
                _remove_tree(plugin_root)
            if moved_previous and backup.exists():
                os.replace(backup, plugin_root)
            project_file.write_bytes(old_project_bytes)
            if old_receipt is None:
                receipt_path.unlink(missing_ok=True)
            else:
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                receipt_path.write_bytes(old_receipt)
        if staging.exists():
            _remove_tree(staging)
        if committed and backup.exists() and not preserve_backup:
            _remove_tree(backup)

    assert verification is not None
    return verification


def _bootstrap_error(context: dict[str, Any]) -> Optional[str]:
    log_dir: Path = context["bootstrap_log_dir"]
    logs = sorted(log_dir.glob("dcc-mcp-unreal.*.host-errors.log")) if log_dir.is_dir() else []
    for log in logs:
        if log.stat().st_size:
            return f"captured Unreal bootstrap error: {log.name}"
    return None


def _verify(
    args: argparse.Namespace,
    context: dict[str, Any],
    state: str,
    receipt: Optional[dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None
    verified_identity: Optional[dict[str, Any]] = None
    steps: list[dict[str, Any]] = []
    if state not in {"current", "upgrade"} or receipt is None:
        failure_stage = "receipt"
        failure_reason = f"install state is {state}; a valid receipt and plugin are required"
        steps.append({"id": "receipt", "status": "failed", "message": failure_reason})
    else:
        steps.append({"id": "receipt", "status": "ok"})
        matches, reason, _ = _manifest_matches(context["plugin_root"], receipt)
        if not matches:
            failure_stage = "artifact"
            failure_reason = reason
            steps.append({"id": "artifact", "status": "failed", "message": reason})
        else:
            steps.append({"id": "artifact", "status": "ok"})
    if failure_stage is None:
        project_entry = _plugin_entry(_read_json(context["project_file"]))
        expected_entry = receipt.get("registration", {}).get("installed_plugin_entry") if receipt else None
        expected_project_hash = receipt.get("registration", {}).get("installed_project_sha256") if receipt else None
        project_hash = _sha256(context["project_file"])
        if (
            project_entry != expected_entry
            or not project_entry
            or project_entry.get("Enabled") is not True
            or expected_project_hash != project_hash
        ):
            failure_stage = "host-enablement"
            failure_reason = "the .uproject plugin registration or project digest differs from the receipt"
            steps.append({"id": "host-enablement", "status": "failed", "message": failure_reason})
        else:
            steps.append({"id": "host-enablement", "status": "ok"})
    if failure_stage is None:
        bootstrap_error = _bootstrap_error(context)
        if bootstrap_error:
            failure_stage = "bootstrap"
            failure_reason = bootstrap_error
            steps.append({"id": "bootstrap", "status": "failed", "message": bootstrap_error})
        else:
            steps.append({"id": "bootstrap", "status": "ok"})
    if failure_stage is None:
        try:
            from dcc_mcp_core import wait_for_sidecar_ready

            readiness = wait_for_sidecar_ready(
                dcc_type=DCC_TYPE,
                instance_id=context["instance_id"],
                timeout_secs=args.timeout,
                probe_tool="unreal_automation__mcp_self_check",
            )
        except (ImportError, OSError, ValueError) as exc:
            readiness = {"success": False, "message": str(exc)}
        identity, readiness_reason = _readiness_identity(args, context, receipt or {}, readiness)
        if readiness_reason is not None:
            failure_stage = "readiness"
            failure_reason = readiness_reason
            steps.append({"id": "readiness", "status": "failed", "message": failure_reason})
        else:
            verified_identity = identity
            context["_verified_runtime_identity"] = identity
            steps.append({"id": "readiness", "status": "ok"})

    directly_usable = failure_stage is None
    if receipt is not None and receipt.get("transaction") is not None and context["instance_id"]:
        try:
            if directly_usable and verified_identity is not None:
                _finalize_pending(context, receipt, verified_identity)
            else:
                _rollback_pending(context, receipt)
        except (OSError, ValueError) as exc:
            raise LifecycleError(
                f"Pending install verification transaction failed: {exc}",
                exit_code=INSTALL_EXIT_INSTALL,
                stage="verify",
            ) from exc
    status = "ok" if directly_usable else "failed"
    if directly_usable:
        next_steps = []
    elif failure_stage == "readiness":
        next_steps = [_readiness_next_step(args, context)]
    else:
        next_steps = [_failure_next_step(args, failure_stage or "verify")]
    document = _result(
        status=status,
        steps=steps,
        next_steps=next_steps,
        receipt_path=context["receipt_path"],
        verify={
            "directly_usable": directly_usable,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
        },
        **_context_fields(context, state),
    )
    return (INSTALL_EXIT_OK if directly_usable else INSTALL_EXIT_VERIFY), document


def _status(
    args: argparse.Namespace,
    context: dict[str, Any],
    state: str,
    state_reason: Optional[str],
    receipt: Optional[dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    failed = state == "partial"
    pending_verify = isinstance(receipt, dict) and receipt.get("transaction") is not None
    verify = {
        "directly_usable": False,
        "failure_stage": "preflight" if failed else ("readiness" if pending_verify else None),
        "failure_reason": (
            state_reason
            if failed
            else ("upgrade is awaiting an exact-instance bound verify" if pending_verify else None)
        ),
    }
    return (INSTALL_EXIT_PREFLIGHT if failed else INSTALL_EXIT_OK), _result(
        status="partial" if failed else "ok",
        steps=[{"id": "status", "status": "failed" if failed else "ok", "message": state_reason or ""}],
        next_steps=(
            [_failure_next_step(args, "partial-state")]
            if failed
            else ([_readiness_next_step(args, context)] if pending_verify else [])
        ),
        receipt_path=context["receipt_path"] if context["receipt_path"].is_file() else None,
        verify=verify,
        **_context_fields(context, state),
    )


def _uninstall(
    args: argparse.Namespace,
    context: dict[str, Any],
    state: str,
    receipt: Optional[dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    if state == "fresh":
        return INSTALL_EXIT_OK, _result(
            status="ok",
            steps=[{"id": "uninstall", "status": "already-absent"}],
            next_steps=[],
            receipt_path=None,
            **_context_fields(context, "absent"),
        )
    if state in {"partial", "repair"} or receipt is None:
        reason = "uninstall refuses state that is not fully described by a valid receipt"
        return INSTALL_EXIT_PREFLIGHT, _result(
            status="partial",
            steps=[{"id": "preflight", "status": "failed", "message": reason}],
            next_steps=[_failure_next_step(args, "partial-state")],
            receipt_path=context["receipt_path"],
            verify={"directly_usable": False, "failure_stage": "preflight", "failure_reason": reason},
            **_context_fields(context, state),
        )
    if receipt.get("transaction") is not None:
        reason = "uninstall refuses an upgrade that is still awaiting exact-instance verification"
        return INSTALL_EXIT_PREFLIGHT, _result(
            status="partial",
            steps=[{"id": "preflight", "status": "failed", "message": reason}],
            next_steps=[_readiness_next_step(args, context)],
            receipt_path=context["receipt_path"],
            verify={"directly_usable": False, "failure_stage": "preflight", "failure_reason": reason},
            **_context_fields(context, state),
        )
    if args.dry_run or not args.yes:
        return _plan(args, context, state, None)

    plugin_root: Path = context["plugin_root"]
    lock_reason = _inspect_locks(plugin_root)
    if lock_reason:
        reason = f"Unreal has loaded a plugin artifact: {lock_reason}"
        return INSTALL_EXIT_REQUIRES_RESTART, _result(
            status="requires_restart",
            steps=[{"id": "uninstall", "status": "requires_restart", "message": reason}],
            next_steps=[_failure_next_step(args, "requires-restart")],
            receipt_path=context["receipt_path"],
            verify={"directly_usable": False, "failure_stage": "install", "failure_reason": reason},
            **_context_fields(context, state),
        )
    backup = plugin_root.parent / f".{PLUGIN_NAME}.uninstall-{uuid.uuid4().hex}"
    recovery = plugin_root.parent / f".{PLUGIN_NAME}.recovery-{uuid.uuid4().hex}"
    project_file: Path = context["project_file"]
    old_project = project_file.read_bytes()
    receipt_path: Path = context["receipt_path"]
    old_receipt = receipt_path.read_bytes()
    committed = False
    moved = False
    try:
        shutil.copytree(plugin_root, recovery, symlinks=True)
        os.replace(plugin_root, backup)
        moved = True
        project = _read_json(project_file)
        installed_entry = receipt.get("registration", {}).get("installed_plugin_entry")
        if _plugin_entry(project) != installed_entry:
            raise LifecycleError(
                "The project plugin entry changed after install; refusing to overwrite it",
                exit_code=INSTALL_EXIT_INSTALL,
                stage="uninstall",
            )
        _set_plugin_entry(project, receipt.get("registration", {}).get("previous_plugin_entry"))
        _atomic_json(project_file, project)
        receipt_path.unlink()
        _remove_tree(backup)
        committed = True
    except PermissionError as exc:
        raise LifecycleError(
            f"A loaded Unreal plugin artifact requires restart: {exc}",
            exit_code=INSTALL_EXIT_REQUIRES_RESTART,
            stage="uninstall",
        ) from exc
    except OSError as exc:
        raise LifecycleError(
            f"Receipt-driven uninstall failed: {exc}",
            exit_code=INSTALL_EXIT_INSTALL,
            stage="uninstall",
        ) from exc
    finally:
        if not committed:
            project_file.write_bytes(old_project)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_bytes(old_receipt)
            if plugin_root.exists():
                _remove_tree(plugin_root)
            if recovery.exists():
                os.replace(recovery, plugin_root)
            elif moved and backup.exists():
                os.replace(backup, plugin_root)
        if committed and recovery.exists():
            _remove_tree(recovery)
    return INSTALL_EXIT_OK, _result(
        status="ok",
        steps=[{"id": "uninstall", "status": "ok"}],
        next_steps=[],
        receipt_path=None,
        **_context_fields(context, "absent"),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dcc-mcp-unreal")
    parser.add_argument("verb", choices=("install", "status", "verify", "uninstall", "upgrade"))
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dcc-path")
    parser.add_argument("--python")
    parser.add_argument("--project", default=os.environ.get("DCC_MCP_UNREAL_PROJECT", os.getcwd()))
    parser.add_argument("--instance-id")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def _execute(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    context, preflight_failure = _preflight(args)
    if preflight_failure is not None:
        return preflight_failure
    assert context is not None
    state, receipt, state_reason = _inspect_state(context)
    if args.verb == "status":
        return _status(args, context, state, state_reason, receipt)
    if args.verb == "verify":
        return _verify(args, context, state, receipt)
    try:
        if args.verb == "uninstall":
            return _uninstall(args, context, state, receipt)
        if state == "partial":
            return _plan(args, context, state, state_reason)
        if args.dry_run or not args.yes:
            return _plan(args, context, state, state_reason)
        return _install(args, context, state, receipt)
    except LifecycleError as exc:
        return exc.exit_code, _result(
            status="requires_restart" if exc.exit_code == INSTALL_EXIT_REQUIRES_RESTART else "failed",
            steps=[{"id": exc.stage, "status": "failed", "message": str(exc)}],
            next_steps=[_failure_next_step(args, exc.stage)],
            receipt_path=context["receipt_path"] if context["receipt_path"].is_file() else None,
            verify={"directly_usable": False, "failure_stage": exc.stage, "failure_reason": str(exc)},
            **_context_fields(context, state),
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    exit_code, document = _execute(args)
    if args.json_output:
        print(json.dumps(document, sort_keys=True))
    else:
        print(json.dumps(document, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

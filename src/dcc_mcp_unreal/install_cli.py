"""Agent-first Unreal Engine plugin lifecycle CLI.

The Python entry point owns the project-plugin transaction only. Native
sidecar acquisition stays in the checksummed standalone installer and runtime
handoff stays in :mod:`dcc_mcp_unreal._standalone_entry`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Optional, Sequence

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
MIN_CORE_VERSION = "0.20.0"
MIN_HOST_VERSION = (4, 18, 0)
RECEIPT_SCHEMA_VERSION = 1


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
    parts: list[int] = []
    for component in value.split("."):
        digits = "".join(character for character in component if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


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
    return ".".join(str(data[key]) for key in ("MajorVersion", "MinorVersion", "PatchVersion"))


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
                except (OSError, KeyError, json.JSONDecodeError):
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
    probe = (
        "import json,sys,dcc_mcp_core,dcc_mcp_unreal;"
        "print(json.dumps({'python_version':'.'.join(map(str,sys.version_info[:3])),"
        "'adapter_version':dcc_mcp_unreal.__version__,"
        "'core_version':getattr(dcc_mcp_core,'__version__','unknown')}))"
    )
    completed = subprocess.run(
        [str(python_path), "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "import probe failed"
        raise ValueError(f"Target interpreter cannot import the adapter and Core: {diagnostic}")
    try:
        runtime = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Target interpreter returned an invalid import probe") from exc
    if runtime.get("adapter_version") != __version__:
        raise ValueError(
            f"Target interpreter has dcc-mcp-unreal {runtime.get('adapter_version')}, expected {__version__}"
        )
    core_version = str(runtime.get("core_version", "unknown"))
    if _version_tuple(core_version) < _version_tuple(MIN_CORE_VERSION):
        raise ValueError(f"Target interpreter has dcc-mcp-core {core_version}; {MIN_CORE_VERSION}+ is required")
    return {str(key): str(value) for key, value in runtime.items()}


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


def _file_manifest(root: Path) -> list[dict[str, str]]:
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    ]


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
    expected = receipt.get("files")
    if not isinstance(expected, list):
        return False, "receipt file manifest is missing", False
    expected_paths = {str(item.get("path")): str(item.get("sha256")) for item in expected if isinstance(item, dict)}
    actual = {item["path"]: item["sha256"] for item in _file_manifest(plugin_root)}
    unreceipted = sorted(set(actual) - set(expected_paths))
    if unreceipted:
        return False, f"plugin contains unreceipted files: {', '.join(unreceipted)}", True
    if expected_paths != actual:
        return False, "installed plugin files differ from the receipt", False
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
    project_file = _project_file(args.project)
    project = _read_json(project_file)
    association = str(project.get("EngineAssociation") or "").strip()
    if association and re.fullmatch(r"\d+(?:\.\d+){0,2}", association):
        associated_version = _version_tuple(association)
        selected_version = _version_tuple(engine_version)
        if associated_version[:2] != selected_version[:2]:
            raise ValueError(
                f"Project EngineAssociation {association} does not match selected Unreal Engine {engine_version}"
            )
    python_path, python_source = _resolve_python(args, engine_root)
    if not python_path.is_file():
        raise ValueError("The selected target interpreter does not exist")
    runtime = _target_runtime(python_path)
    plugin_root = project_file.parent / "Plugins" / PLUGIN_NAME
    receipt_path = project_file.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    return {
        "engine_root": engine_root,
        "engine_version": engine_version,
        "engine_source": engine_source,
        "project_file": project_file,
        "project": project,
        "python_path": python_path,
        "python_source": python_source,
        "runtime": runtime,
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
    return [
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
    context: dict[str, Any], previous_entry: Optional[dict[str, Any]], provenance: str
) -> dict[str, Any]:
    installed_entry = _plugin_entry(_read_json(context["project_file"]))
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
        "files": _file_manifest(context["plugin_root"]),
        "registration": {
            "previous_plugin_entry": previous_entry,
            "installed_plugin_entry": installed_entry,
        },
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
        _write_receipt(context, previous_entry, provenance)
        committed = True
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
        if committed and backup.exists():
            _remove_tree(backup)

    new_state, new_receipt, _ = _inspect_state(context)
    return _verify(args, context, new_state, new_receipt)


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
        if project_entry != expected_entry or not project_entry or project_entry.get("Enabled") is not True:
            failure_stage = "host-enablement"
            failure_reason = "the .uproject plugin enablement differs from the receipt"
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
                timeout_secs=args.timeout,
                probe_tool="unreal_automation__mcp_self_check",
            )
        except (ImportError, OSError, ValueError) as exc:
            readiness = {"success": False, "message": str(exc)}
        if not readiness.get("success"):
            failure_stage = "readiness"
            failure_reason = str(readiness.get("message") or readiness.get("recommended_next_action") or readiness)
            steps.append({"id": "readiness", "status": "failed", "message": failure_reason})
        else:
            steps.append({"id": "readiness", "status": "ok"})

    directly_usable = failure_stage is None
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
) -> tuple[int, dict[str, Any]]:
    failed = state == "partial"
    verify = {
        "directly_usable": False,
        "failure_stage": "preflight" if failed else None,
        "failure_reason": state_reason if failed else None,
    }
    return (INSTALL_EXIT_PREFLIGHT if failed else INSTALL_EXIT_OK), _result(
        status="partial" if failed else "ok",
        steps=[{"id": "status", "status": "failed" if failed else "ok", "message": state_reason or ""}],
        next_steps=[_failure_next_step(args, "partial-state")] if failed else [],
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
    project_file: Path = context["project_file"]
    old_project = project_file.read_bytes()
    receipt_path: Path = context["receipt_path"]
    old_receipt = receipt_path.read_bytes()
    committed = False
    moved = False
    try:
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
            if moved and backup.exists() and not plugin_root.exists():
                os.replace(backup, plugin_root)
        if committed and backup.exists():
            _remove_tree(backup)
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
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def _execute(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    context, preflight_failure = _preflight(args)
    if preflight_failure is not None:
        return preflight_failure
    assert context is not None
    state, receipt, state_reason = _inspect_state(context)
    if args.verb == "status":
        return _status(args, context, state, state_reason)
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

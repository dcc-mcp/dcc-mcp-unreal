"""Shared process and path helpers for Unreal build/package tools."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Sequence

from dcc_mcp_core.skills_helper import CancelledError, check_dcc_cancelled, skill_error, skill_success

_CORE_SPEC = "dcc-mcp-core>=0.19.45,<1.0.0"
_PLUGIN_MODES = {"native", "source", "python-only"}
_CONFIGURATIONS = {"Development", "Shipping"}


def _tail(path: Path, limit: int = 65536) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        return stream.read().decode("utf-8", errors="replace")


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_logged(command: Sequence[str], cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    process_kwargs = {}
    if os.name == "nt":
        process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_kwargs["start_new_session"] = True

    with log_path.open("wb") as log:
        log.write(("command: " + subprocess.list2cmdline(list(command)) + "\n\n").encode("utf-8"))
        log.flush()
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            **process_kwargs,
        )
        try:
            while process.poll() is None:
                check_dcc_cancelled()
                time.sleep(0.25)
        except CancelledError:
            _terminate_process_tree(process)
            raise
    return int(process.returncode or 0)


def _resolve_engine_root(raw_path: str) -> Path:
    if raw_path:
        engine_root = Path(raw_path).expanduser().resolve()
    else:
        engine_root = _infer_engine_root()
    if not (engine_root / "Engine").is_dir():
        raise FileNotFoundError("Unreal Engine root does not contain Engine/: {}".format(engine_root))
    return engine_root


def _infer_engine_root() -> Path:
    for value in [sys.executable] + list(sys.argv):
        path = Path(value).expanduser()
        for parent in [path] + list(path.parents):
            if parent.name.lower() == "engine":
                return parent.parent.resolve()
    raise ValueError("Unreal Engine root could not be inferred from the current process")


def _resolve_uat(engine_root: Path) -> Path:
    batch_files = engine_root / "Engine" / "Build" / "BatchFiles"
    for name in ("RunUAT.bat", "RunUAT.sh"):
        candidate = batch_files / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("RunUAT was not found under {}".format(batch_files))


def _resolve_python(engine_root: Path, raw_path: str) -> Path:
    candidates = []
    if raw_path:
        candidates.append(Path(raw_path).expanduser())
    candidates.extend(
        [
            engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Win64" / "python.exe",
            engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Linux" / "bin" / "python3",
            engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Mac" / "bin" / "python3",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("An external Python executable was not found; pass python_executable explicitly")


def build_plugin_package_impl(
    repository_root: str,
    ue_root: str,
    mode: str = "native",
    python_executable: str = "",
    core_wheel: str = "",
    core_spec: str = _CORE_SPEC,
    vctoolchain_version: str = "",
) -> dict:
    try:
        if mode not in _PLUGIN_MODES:
            raise ValueError("mode must be one of: {}".format(", ".join(sorted(_PLUGIN_MODES))))
        repository = Path(repository_root).expanduser().resolve()
        build_script = repository / "packaging" / "build_distributable.py"
        if not build_script.is_file():
            raise FileNotFoundError("Plugin build script not found: {}".format(build_script))
        engine_root = _resolve_engine_root(ue_root)
        if mode == "native":
            _resolve_uat(engine_root)
        python = _resolve_python(engine_root, python_executable)
        wheel = Path(core_wheel).expanduser().resolve() if core_wheel else None
        if wheel is not None and not wheel.is_file():
            raise FileNotFoundError("dcc-mcp-core wheel not found: {}".format(wheel))
        if not core_spec.strip():
            raise ValueError("core_spec must not be empty")
    except (OSError, ValueError) as exc:
        return skill_error("Plugin package inputs are invalid", str(exc))

    command = [
        str(python),
        str(build_script),
        "--ue-root",
        str(engine_root),
        "--python",
        str(python),
        "--mode",
        mode,
        "--core-spec",
        core_spec,
    ]
    if wheel is not None:
        command.extend(["--core-wheel", str(wheel)])
    if vctoolchain_version:
        command.extend(["--vctoolchain-version", vctoolchain_version])

    log_path = repository / "dist" / "build-plugin.log"
    try:
        return_code = _run_logged(command, repository, log_path)
    except CancelledError as exc:
        return skill_error("Plugin packaging was cancelled", str(exc), log_path=str(log_path))
    except OSError as exc:
        return skill_error("Plugin packaging could not start", str(exc), log_path=str(log_path))
    if return_code:
        return skill_error(
            "Plugin packaging failed",
            "Build process exited with code {}".format(return_code),
            log_path=str(log_path),
            log_tail=_tail(log_path),
        )

    suffix = "win64" if mode == "native" else mode
    archives = sorted((repository / "dist").glob("DccMcpUnreal-*-{}.zip".format(suffix)))
    if not archives:
        return skill_error(
            "Plugin packaging did not produce an archive",
            "No matching ZIP was found in {}".format(repository / "dist"),
            log_path=str(log_path),
        )
    archive = max(archives, key=lambda path: path.stat().st_mtime)
    return skill_success(
        "Unreal plugin package built successfully",
        prompt="Distribute or install the returned ZIP after reviewing the build log.",
        artifacts=[str(archive)],
        archive_path=str(archive),
        plugin_directory=str(repository / "dist" / "package" / "DccMcpUnreal"),
        log_path=str(log_path),
        mode=mode,
    )


def package_project_executable_impl(
    project_path: str,
    output_directory: str,
    ue_root: str = "",
    configuration: str = "Shipping",
    target_platform: str = "Win64",
) -> dict:
    try:
        project = Path(project_path).expanduser().resolve()
        if project.suffix.lower() != ".uproject" or not project.is_file():
            raise FileNotFoundError("Saved .uproject file not found: {}".format(project))
        output = Path(output_directory).expanduser().resolve()
        if output == project.parent:
            raise ValueError("output_directory must not be the Unreal project root")
        if configuration not in _CONFIGURATIONS:
            raise ValueError("configuration must be Development or Shipping")
        if target_platform != "Win64":
            raise ValueError("target_platform must be Win64")
        engine_root = _resolve_engine_root(ue_root)
        uat = _resolve_uat(engine_root)
    except (OSError, ValueError) as exc:
        return skill_error("Project package inputs are invalid", str(exc))

    command = [
        str(uat),
        "BuildCookRun",
        "-project={}".format(project),
        "-noP4",
        "-unattended",
        "-utf8output",
        "-platform={}".format(target_platform),
        "-clientconfig={}".format(configuration),
        "-build",
        "-cook",
        "-stage",
        "-package",
        "-pak",
        "-archive",
        "-archivedirectory={}".format(output),
    ]
    log_path = output.parent / "{}.build.log".format(output.name)
    try:
        return_code = _run_logged(command, project.parent, log_path)
    except CancelledError as exc:
        return skill_error("Project packaging was cancelled", str(exc), log_path=str(log_path))
    except OSError as exc:
        return skill_error("Project packaging could not start", str(exc), log_path=str(log_path))
    if return_code:
        return skill_error(
            "Project packaging failed",
            "BuildCookRun exited with code {}".format(return_code),
            log_path=str(log_path),
            log_tail=_tail(log_path),
        )

    executables = sorted(output.rglob("*.exe")) if output.is_dir() else []
    if not executables:
        return skill_error(
            "Project packaging completed without a Windows executable",
            "No .exe was found under {}".format(output),
            log_path=str(log_path),
        )
    package_files: List[Path] = []
    for pattern in ("*.exe", "*.pak", "*.ucas", "*.utoc"):
        package_files.extend(output.rglob(pattern))
    artifacts = sorted({str(path) for path in package_files})
    return skill_success(
        "Unreal project packaged successfully",
        prompt="Launch the returned executable and smoke-test the packaged build.",
        artifacts=artifacts,
        executable_paths=[str(path) for path in executables],
        output_directory=str(output),
        log_path=str(log_path),
        configuration=configuration,
        target_platform=target_platform,
    )

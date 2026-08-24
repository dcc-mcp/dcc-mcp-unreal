"""Shared process and path helpers for Unreal build/package tools."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List, Sequence

from dcc_mcp_core.skills_helper import CancelledError, check_dcc_cancelled, skill_error, skill_success

_CORE_SPEC = "dcc-mcp-core>=0.20.13,<1.0.0"
_PLUGIN_MODES = {"native", "source", "python-only"}
_CONFIGURATIONS = {"Development", "Shipping"}
_RELEASE_PROFILES = {"archive", "installer", "steam", "wegame"}


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


def _resolve_iscc(raw_path: str) -> Path:
    candidates = [Path(raw_path).expanduser()] if raw_path else []
    discovered = shutil.which("ISCC.exe") or shutil.which("iscc")
    if discovered:
        candidates.append(Path(discovered))
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Inno Setup 6" / "ISCC.exe")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Inno Setup 6 ISCC.exe was not found; install it or pass installer_compiler_path")


def _copy_prerequisites(engine_root: Path, stage_root: Path) -> List[Path]:
    source = engine_root / "Engine" / "Extras" / "Redist" / "en-us"
    destination = stage_root / "Engine" / "Extras" / "Redist" / "en-us"
    copied = []
    for name in (
        "vc_redist.x64.exe",
        "GameInputRedist.msi",
        "UEPrereqSetup_x64.exe",
        "UE4PrereqSetup_x64.exe",
    ):
        candidate = source / name
        if candidate.is_file():
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / name
            shutil.copy2(str(candidate), str(target))
            copied.append(target)
    if not copied:
        raise FileNotFoundError("No Win64 Unreal prerequisite installer was found under {}".format(source))
    return copied


def _find_game_executable(output: Path, project_name: str) -> Path:
    executables = [
        path
        for path in output.rglob("*.exe")
        if "engine" not in {part.lower() for part in path.relative_to(output).parts}
    ]
    if not executables:
        raise FileNotFoundError("No game executable was found under {}".format(output))
    named = [path for path in executables if path.name.lower() == "{}.exe".format(project_name.lower())]
    return min(named or executables, key=lambda path: len(path.relative_to(output).parts))


def _stage_root(output: Path, executable: Path) -> Path:
    relative = executable.relative_to(output)
    return output / relative.parts[0] if len(relative.parts) > 1 else output


def _inno_value(value: str) -> str:
    return value.replace("{", "{{").replace('"', '""')


def _windows_file_version(value: str) -> str:
    parts = value.split(".")
    if not 1 <= len(parts) <= 4 or not all(part.isdigit() for part in parts):
        return "1.0.0.0"
    return ".".join(parts + ["0"] * (4 - len(parts)))


def _build_installer(
    output: Path,
    stage_root: Path,
    executable: Path,
    product_name: str,
    product_version: str,
    publisher: str,
    compiler: Path,
) -> tuple:
    installer_dir = output / "Installer"
    installer_dir.mkdir(parents=True, exist_ok=True)
    relative_executable = executable.relative_to(stage_root)
    file_product_name = "".join(
        character if character.isalnum() or character in "-_." else "-" for character in product_name
    ).strip("-.")
    file_product_version = "".join(
        character if character.isalnum() or character in "-_." else "-" for character in product_version
    ).strip("-.")
    base_name = "{}-Setup-{}".format(file_product_name or "Game", file_product_version or "1.0.0")
    app_id = uuid.uuid5(uuid.NAMESPACE_URL, "dcc-mcp-unreal:{}:{}".format(publisher, product_name))
    script = installer_dir / "game-installer.iss"
    script.write_text(
        """[Setup]
AppId=dcc-mcp-unreal-{app_id}
AppName={product_name}
AppVersion={product_version}
AppPublisher={publisher}
VersionInfoVersion={version_info_version}
VersionInfoCompany={publisher}
VersionInfoProductName={product_name}
VersionInfoProductVersion={product_version}
DefaultDirName={{autopf}}\\{product_name}
DefaultGroupName={product_name}
OutputDir={output_dir}
OutputBaseFilename={base_name}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{source}\\*"; DestDir: "{{app}}"; Excludes: "Installer\\*,*.pdb,vc_redist.arm64.exe"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{autoprograms}}\\{product_name}"; Filename: "{{app}}\\{executable}"
Name: "{{autodesktop}}\\{product_name}"; Filename: "{{app}}\\{executable}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\Engine\\Extras\\Redist\\en-us\\UEPrereqSetup_x64.exe"; Parameters: "/quiet /norestart"; Flags: runhidden waituntilterminated; Check: FileExists(ExpandConstant('{{app}}\\Engine\\Extras\\Redist\\en-us\\UEPrereqSetup_x64.exe'))
Filename: "{{app}}\\Engine\\Extras\\Redist\\en-us\\UE4PrereqSetup_x64.exe"; Parameters: "/quiet /norestart"; Flags: runhidden waituntilterminated; Check: FileExists(ExpandConstant('{{app}}\\Engine\\Extras\\Redist\\en-us\\UE4PrereqSetup_x64.exe'))
Filename: "{{app}}\\Engine\\Extras\\Redist\\en-us\\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; Flags: runhidden waituntilterminated; Check: FileExists(ExpandConstant('{{app}}\\Engine\\Extras\\Redist\\en-us\\vc_redist.x64.exe'))
Filename: "{{sys}}\\msiexec.exe"; Parameters: "/i ""{{app}}\\Engine\\Extras\\Redist\\en-us\\GameInputRedist.msi"" /quiet /norestart"; Flags: runhidden waituntilterminated; Check: FileExists(ExpandConstant('{{app}}\\Engine\\Extras\\Redist\\en-us\\GameInputRedist.msi'))
Filename: "{{app}}\\{executable}"; Description: "Launch {product_name}"; Flags: nowait postinstall skipifsilent
""".format(
            app_id=app_id,
            product_name=_inno_value(product_name),
            product_version=_inno_value(product_version),
            publisher=_inno_value(publisher),
            version_info_version=_windows_file_version(product_version),
            output_dir=_inno_value(str(installer_dir)),
            base_name=_inno_value(base_name),
            source=_inno_value(str(stage_root)),
            executable=_inno_value(str(relative_executable)),
        ),
        encoding="utf-8-sig",
    )
    log_path = installer_dir / "build-installer.log"
    return_code = _run_logged([str(compiler), str(script)], output, log_path)
    installer = installer_dir / "{}.exe".format(base_name)
    if return_code or not installer.is_file():
        raise RuntimeError("Inno Setup failed; inspect {}".format(log_path))
    return installer, script, log_path


def _write_steam_pipe(
    output: Path,
    stage_root: Path,
    product_name: str,
    product_version: str,
    app_id: str,
    depot_id: str,
) -> List[Path]:
    if not app_id.isdigit() or not depot_id.isdigit():
        raise ValueError("steam_app_id and steam_depot_id must contain digits only")
    root = output / "SteamPipe"
    scripts = root / "scripts"
    build_output = root / "output"
    scripts.mkdir(parents=True, exist_ok=True)
    build_output.mkdir(parents=True, exist_ok=True)
    depot = scripts / "depot_build_{}.vdf".format(depot_id)
    app = scripts / "app_build_{}.vdf".format(app_id)
    depot.write_text(
        """"DepotBuildConfig"
{{
    "DepotID" "{depot_id}"
    "ContentRoot" "{content_root}"
    "FileMapping"
    {{
        "LocalPath" "*"
        "DepotPath" "."
        "recursive" "1"
    }}
    "FileExclusion" "*.pdb"
}}
""".format(depot_id=depot_id, content_root=str(stage_root).replace("\\", "/")),
        encoding="utf-8",
    )
    app.write_text(
        """"AppBuild"
{{
    "AppID" "{app_id}"
    "Desc" "{description}"
    "BuildOutput" "{build_output}"
    "ContentRoot" "{content_root}"
    "Preview" "1"
    "Depots"
    {{
        "{depot_id}" "{depot_script}"
    }}
}}
""".format(
            app_id=app_id,
            description="{} {}".format(product_name, product_version).replace('"', "'"),
            build_output=str(build_output).replace("\\", "/"),
            content_root=str(stage_root).replace("\\", "/"),
            depot_id=depot_id,
            depot_script=depot.name,
        ),
        encoding="utf-8",
    )
    readme = root / "README.txt"
    readme.write_text(
        'Run steamcmd +login <account> +run_app_build "{}" +quit.\n'
        "Keep Preview=1 until the build is verified. Enable Microsoft Visual C++ 2015-2022 "
        "under Steamworks Installation > Redistributables before release.\n".format(app),
        encoding="utf-8",
    )
    return [app, depot, readme]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_wegame_release(
    output: Path,
    stage_root: Path,
    executable: Path,
    product_name: str,
    product_version: str,
) -> List[Path]:
    root = output / "WeGame"
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "release-preflight.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "dcc-mcp-unreal.wegame-preflight.v1",
                "product_name": product_name,
                "product_version": product_version,
                "content_root": os.path.relpath(str(stage_root), str(root)).replace("\\", "/"),
                "executable": str(executable.relative_to(stage_root)),
                "executable_sha256": _sha256(executable),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    checklist = root / "README.txt"
    checklist.write_text(
        "This directory is a local preflight record, not a WeGame-owned manifest.\n"
        "Before portal submission: obtain project approval, integrate the Rail SDK, test with the "
        "developer WeGame client, then upload the packaged content root through the authenticated portal.\n"
        "Developer portal: https://developer.wegame.com/\n",
        encoding="utf-8",
    )
    return [manifest, checklist]


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
    release_profile: str = "archive",
    product_name: str = "",
    product_version: str = "1.0.0",
    publisher: str = "",
    installer_compiler_path: str = "",
    steam_app_id: str = "",
    steam_depot_id: str = "",
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
        if release_profile not in _RELEASE_PROFILES:
            raise ValueError("release_profile must be one of: {}".format(", ".join(sorted(_RELEASE_PROFILES))))
        resolved_product_name = product_name.strip() or project.stem
        resolved_publisher = publisher.strip() or resolved_product_name
        for field_name, value in (
            ("product_name", resolved_product_name),
            ("product_version", product_version),
            ("publisher", resolved_publisher),
        ):
            if not value.strip() or any(character in value for character in "\r\n\0"):
                raise ValueError("{} must be a non-empty single line".format(field_name))
        engine_root = _resolve_engine_root(ue_root)
        uat = _resolve_uat(engine_root)
        installer_compiler = _resolve_iscc(installer_compiler_path) if release_profile == "installer" else None
        if release_profile == "steam" and (not steam_app_id or not steam_depot_id):
            raise ValueError("steam_app_id and steam_depot_id are required for the steam profile")
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
    if release_profile != "steam":
        command.append("-prereqs")
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

    try:
        executable = _find_game_executable(output, project.stem)
        stage_root = _stage_root(output, executable)
        prerequisites = _copy_prerequisites(engine_root, stage_root) if release_profile != "steam" else []
        release_artifacts = []
        installer_log_path = ""
        if release_profile == "installer":
            installer, script, installer_log = _build_installer(
                output,
                stage_root,
                executable,
                resolved_product_name,
                product_version,
                resolved_publisher,
                installer_compiler,
            )
            release_artifacts.extend([installer, script])
            installer_log_path = str(installer_log)
        elif release_profile == "steam":
            release_artifacts.extend(
                _write_steam_pipe(
                    output,
                    stage_root,
                    resolved_product_name,
                    product_version,
                    steam_app_id,
                    steam_depot_id,
                )
            )
        elif release_profile == "wegame":
            release_artifacts.extend(
                _write_wegame_release(
                    output,
                    stage_root,
                    executable,
                    resolved_product_name,
                    product_version,
                )
            )
    except (OSError, RuntimeError, ValueError) as exc:
        return skill_error(
            "Project packaging completed but release preparation failed",
            str(exc),
            log_path=str(log_path),
        )
    package_files: List[Path] = []
    for pattern in ("*.exe", "*.pak", "*.ucas", "*.utoc"):
        package_files.extend(output.rglob(pattern))
    artifacts = sorted({str(path) for path in package_files + prerequisites + release_artifacts})
    prompt = "Launch the returned executable and smoke-test the packaged build."
    if release_profile == "installer":
        prompt = "Install and smoke-test the returned Setup executable on a clean Windows machine."
    elif release_profile == "steam":
        prompt = "Run the SteamPipe app VDF as a preview build, then configure Steam common redistributables."
    elif release_profile == "wegame":
        prompt = "Complete Rail SDK testing, then submit the packaged content root through the WeGame developer portal."
    return skill_success(
        "Unreal project packaged successfully",
        prompt=prompt,
        artifacts=artifacts,
        executable_paths=[str(executable)],
        game_executable_path=str(executable),
        stage_root=str(stage_root),
        output_directory=str(output),
        log_path=str(log_path),
        installer_log_path=installer_log_path,
        configuration=configuration,
        target_platform=target_platform,
        release_profile=release_profile,
    )

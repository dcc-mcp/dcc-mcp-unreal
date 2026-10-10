#!/usr/bin/env python3
"""Build a distributable Unreal plugin zip.

This script creates a package suitable for users to drop into a project's
``Plugins/`` directory. It supports three modes:

* ``native``: runs Unreal AutomationTool ``BuildPlugin``, builds an adapter
  wheel containing the complete native payload, then vendors that wheel and
  writes ``dist/DccMcpUnreal-<version>-<ue-version>-win64.zip``. UE4 native packages
  use the standalone sidecar and omit the incompatible embedded dependencies.
* ``source``: vendors Python and keeps the C++ source module for engines that
  should compile the plugin locally.
* ``python-only``: vendors Python and strips the C++ module for legacy/internal
  engines that provide their own Python bridge.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = REPO_ROOT / "unreal" / "plugin" / "DccMcpUnreal.uplugin"
DEFAULT_UE_ROOT = Path(os.environ.get("UE_ROOT", r"C:\Program Files\Epic Games\UE_5.7"))
DEFAULT_CORE_WHEEL = os.environ.get("DCC_MCP_CORE_WHEEL")
DEFAULT_CORE_WHEEL_URL = os.environ.get("DCC_MCP_CORE_WHEEL_URL")
DEFAULT_CORE_SPEC = os.environ.get("DCC_MCP_CORE_SPEC", "dcc-mcp-core>=0.20.13,<0.21.0")
GENERATED_HEADER_COMPAT_ENV = "DCC_MCP_UNREAL_GENERATED_HEADER_COMPAT"
PACKAGE_HEADER_ID = "FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h"


def run(cmd: List[str], *, cwd: Optional[Path] = None) -> None:
    print("[build-uplugin] " + " ".join(_quote(part) for part in cmd))
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)


def _quote(value: str) -> str:
    return '"{}"'.format(value) if " " in value else value


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve()
    dist_root = (REPO_ROOT / "dist").resolve()
    if resolved == dist_root or dist_root not in resolved.parents:
        raise ValueError("Refusing to remove path outside dist/: {}".format(resolved))
    shutil.rmtree(str(resolved))


def download_file(url: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    print("[build-uplugin] download {} -> {}".format(url, dst))
    req = urllib.request.Request(url, headers={"User-Agent": "dcc-mcp-unreal-build"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with dst.open("wb") as handle:
            shutil.copyfileobj(resp, handle)
    return dst


def read_engine_tag(ue_root: Path) -> str:
    build_version = ue_root / "Engine" / "Build" / "Build.version"
    if not build_version.exists():
        return "ue"
    data = json.loads(build_version.read_text(encoding="utf-8"))
    return "ue{}.{}".format(data.get("MajorVersion", ""), data.get("MinorVersion", ""))


def read_engine_version(ue_root: Path) -> Tuple[int, int, int]:
    build_version = ue_root / "Engine" / "Build" / "Build.version"
    if not build_version.exists():
        return (0, 0, 0)
    data = json.loads(build_version.read_text(encoding="utf-8"))
    return tuple(int(data.get(key, 0)) for key in ("MajorVersion", "MinorVersion", "PatchVersion"))


def create_generated_header_compat(ue_root: Path, work_dir: Path) -> Optional[Path]:
    """Bridge stale UE 5.8.0 generated macros after an in-place 5.8.1 update.

    Epic installed builds do not regenerate engine reflection output. Some
    launcher updates replace ``Package.h`` with the 5.8.1 source while leaving
    the 5.8.0 ``Package.generated.h`` behind. Reflection macro names encode
    source line numbers, so the mixed installation cannot compile a plugin.
    Keep the engine immutable and create aliases only when the exact mismatch
    is observed.
    """
    if read_engine_version(ue_root)[:2] != (5, 8):
        return None

    source = ue_root / "Engine" / "Source" / "Runtime" / "CoreUObject" / "Public" / "UObject" / "Package.h"
    generated = (
        ue_root
        / "Engine"
        / "Intermediate"
        / "Build"
        / "Win64"
        / "UnrealEditor"
        / "Inc"
        / "CoreUObject"
        / "UHT"
        / "Package.generated.h"
    )
    if not source.is_file() or not generated.is_file():
        return None

    source_lines = source.read_text(encoding="utf-8").splitlines()
    prolog_line = next(
        (index for index, line in enumerate(source_lines, 1) if line == "UCLASS(MinimalAPI, Config=Engine)"),
        None,
    )
    body_line = next(
        (index for index, line in enumerate(source_lines, 1) if line.strip() == "GENERATED_BODY()"),
        None,
    )
    generated_text = generated.read_text(encoding="utf-8")
    prolog_match = re.search(r"#define {}_(\d+)_PROLOG\b".format(PACKAGE_HEADER_ID), generated_text)
    body_match = re.search(r"#define {}_(\d+)_GENERATED_BODY\b".format(PACKAGE_HEADER_ID), generated_text)
    if prolog_line is None or body_line is None or prolog_match is None or body_match is None:
        return None

    generated_prolog_line = int(prolog_match.group(1))
    generated_body_line = int(body_match.group(1))
    if (prolog_line, body_line) == (generated_prolog_line, generated_body_line):
        return None
    observed = (prolog_line, body_line, generated_prolog_line, generated_body_line)
    if observed != (215, 218, 214, 217):
        raise RuntimeError(
            "Unsupported UE Package.h reflection macro drift: source {}, {}; generated {}, {}".format(*observed)
        )

    compat = work_dir / "ue-installed-generated-header-compat.h"
    compat.parent.mkdir(parents=True, exist_ok=True)
    compat.write_text(
        "// Generated by dcc-mcp-unreal; do not edit.\n"
        "// Keeps an in-place UE 5.8 installed-engine update immutable.\n"
        "#define {id}_{new}_PROLOG {id}_{old}_PROLOG\n"
        "#define {id}_{new_body}_GENERATED_BODY {id}_{old_body}_GENERATED_BODY\n".format(
            id=PACKAGE_HEADER_ID,
            new=prolog_line,
            old=generated_prolog_line,
            new_body=body_line,
            old_body=generated_body_line,
        ),
        encoding="utf-8",
    )
    print("[build-uplugin] Detected stale UE 5.8 installed generated headers; using job-scoped compatibility aliases")
    return compat


def read_plugin_version(plugin_root: Path) -> str:
    data = json.loads((plugin_root / "DccMcpUnreal.uplugin").read_text(encoding="utf-8"))
    return str(data.get("VersionName") or "0.0.0")


def resolve_uat(ue_root: Path) -> Path:
    candidates = [
        ue_root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat",
        ue_root / "Engine" / "Build" / "BatchFiles" / "RunUAT.sh",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("RunUAT not found under {}".format(ue_root))


@contextlib.contextmanager
def temporarily_clear_legacy_ubt_user_config(work_dir: Path):
    """Hide cross-version UBT settings while an old engine is running."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        yield
        return

    config_path = Path(appdata) / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    if not config_path.is_file():
        yield
        return

    backup_path = work_dir / "legacy-ubt-user-BuildConfiguration.xml.backup"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(config_path), str(backup_path))
    config_path.write_text(
        '<?xml version="1.0" encoding="utf-8" ?>\n'
        '<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">\n'
        "</Configuration>\n",
        encoding="utf-8",
    )
    print("[build-uplugin] Temporarily cleared cross-version UBT config: {}".format(config_path))
    try:
        yield
    finally:
        shutil.copy2(str(backup_path), str(config_path))
        backup_path.unlink()
        print("[build-uplugin] Restored UBT config: {}".format(config_path))


def build_python_payload(args: argparse.Namespace, payload_dir: Path, adapter_wheel: Optional[Path] = None) -> None:
    core_wheel = args.core_wheel
    if not core_wheel and args.core_wheel_url:
        filename = args.core_wheel_url.rstrip("/").rsplit("/", 1)[-1] or "dcc_mcp_core.whl"
        core_wheel = download_file(args.core_wheel_url, args.work_dir / "downloads" / filename)

    cmd = [
        sys.executable,
        str(REPO_ROOT / "packaging" / "build_plugin.py"),
        "--ue-root",
        str(args.ue_root),
        "--out-dir",
        str(payload_dir),
        "--clean",
        "--python-plugin-name",
        str(args.python_plugin_name),
    ]
    if args.mode == "python-only":
        cmd.append("--no-native")
    if args.mode == "native" and read_engine_tag(args.ue_root).startswith("ue4."):
        cmd.append("--skip-python-deps")
    if args.python:
        cmd += ["--python", str(args.python)]
    if adapter_wheel is not None:
        cmd += ["--adapter-wheel", str(adapter_wheel)]
    if core_wheel:
        cmd += ["--core-wheel", str(core_wheel)]
    elif args.skip_core:
        cmd += ["--skip-core"]
    elif args.use_local_core:
        cmd += ["--use-local-core", "--core-root", str(args.core_root)]
    else:
        cmd += ["--core-spec", str(args.core_spec)]
    run(cmd)


def _msvc_toolchain_roots() -> List[Path]:
    """Return paths to installed MSVC toolchains under VS Build Tools."""
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"),
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC"),
    ]
    roots = []
    for p in candidates:
        if p.is_dir():
            roots.extend(sorted(p.iterdir()))
    return roots


def _check_msvc_toolchain(version: str) -> None:
    """Verify the requested MSVC toolchain version is installed.

    Prints available toolchains and a helpful install suggestion when the
    requested version is not found. This is best-effort — UBT does its own
    resolution and may fall back to a different version.
    """
    if not version:
        return
    installed = [d.name for d in _msvc_toolchain_roots() if d.is_dir()]
    if not installed:
        # Runner may be configured differently — skip check
        return
    if not any(v.startswith(version) for v in installed):
        print("[build-uplugin] WARNING: MSVC toolchain {} not found".format(version), file=sys.stderr)
        print("[build-uplugin] Installed: {}".format(", ".join(sorted(installed))), file=sys.stderr)
        print(
            "[build-uplugin] Install: vs_BuildTools.exe modify --add Microsoft.VisualStudio.Component.VC.{}.17.6.x86.x64".format(
                version.replace(".", ".")
            ),
            file=sys.stderr,
        )


def build_precompiled_plugin(args: argparse.Namespace, uat_dir: Path) -> None:
    _check_msvc_toolchain(args.vctoolchain_version)
    uat = resolve_uat(args.ue_root)
    cmd = [str(uat)]
    engine_tag = read_engine_tag(args.ue_root)
    is_ue4 = engine_tag.startswith("ue4.")
    uses_legacy_ubt_config = is_ue4 or engine_tag in {"ue5.0", "ue5.1", "ue5.2", "ue5.3", "ue5.4", "ue5.5", "ue5.6"}
    if is_ue4:
        precompiled_uat = args.ue_root / "Engine" / "Binaries" / "DotNET" / "AutomationTool.exe"
        if precompiled_uat.is_file():
            cmd.append("-nocompile")
        # Installed UE4 builds default to an AutomationTool log directory under
        # the engine installation. A service account may not own stale logs
        # created there by another user, so keep all UAT writes job-scoped.
        uat_log_dir = uat_dir.parent / "uat-logs"
        uat_log_dir.mkdir(parents=True, exist_ok=True)
        os.environ["uebp_LogFolder"] = str(uat_log_dir)
        print("[build-uplugin] UE4 UAT log folder: {}".format(uat_log_dir))
    cmd += [
        "BuildPlugin",
        "-Plugin={}".format(PLUGIN_SOURCE),
        "-Package={}".format(uat_dir),
        "-TargetPlatforms=Win64",
    ]
    ubtargs = []
    max_parallel_actions = getattr(args, "max_parallel_actions", None)
    if max_parallel_actions is not None:
        if (
            isinstance(max_parallel_actions, bool)
            or not isinstance(max_parallel_actions, int)
            or max_parallel_actions <= 0
        ):
            raise ValueError("max_parallel_actions must be a positive integer")
        ubtargs.append("-MaxParallelActions={}".format(max_parallel_actions))
    if args.vctoolchain_version:
        ubtargs.append("-VCToolchainVersion={}".format(args.vctoolchain_version))
    if args.patched_headers_dir:
        patched = Path(args.patched_headers_dir)
        if patched.is_dir():
            # Write a force-include header to suppress __has_feature issues
            # with MSVC 14.44+. UE 5.2's ConcurrentLinearAllocator.h uses
            # __has_feature in #if directives; MSVC does not define it as
            # a preprocessor macro, causing C4668/C4067.
            # /FI is used instead of /I because UE's build system sets its
            # own include paths that take precedence over /I additions, so
            # the original engine header is found first.
            fi_header = patched / "suppress_msvc_has_feature.h"
            fi_header.write_text(
                "// Generated by build_distributable.py\n"
                "// Suppress __has_feature for MSVC (UE 5.2 compat)\n"
                "#if defined(_MSC_VER) && !defined(__has_feature)\n"
                "#define __has_feature(x) 0\n"
                "#endif\n"
            )
            ubtargs.append('-AdditionalCompilerArguments=/FI"{}" /wd4668'.format(fi_header))
            print("[build-uplugin] Force-include header: {}".format(fi_header))
        else:
            print("[build-uplugin] WARNING: patched headers dir not found: {}".format(patched))
    if ubtargs:
        cmd.append("-ubtargs=" + " ".join(ubtargs))
    # _CL_ tells MSVC cl.exe to suppress C4668 unconditionally,
    # bypassing UBT's internal compiler argument management.
    # /FI ensures suppress_msvc_has_feature.h is included in EVERY
    # cl.exe invocation, including Shared PCH generation (which UBT's
    # -AdditionalCompilerArguments does not reach).
    if args.patched_headers_dir:
        fi_header = Path(args.patched_headers_dir) / "suppress_msvc_has_feature.h"
        if fi_header.exists():
            os.environ["_CL_"] = '/FI"{}" /wd4668'.format(fi_header)
        else:
            os.environ["_CL_"] = "/wd4668"
    else:
        os.environ["_CL_"] = "/wd4668"
    compat_header = create_generated_header_compat(args.ue_root, uat_dir.parent)
    previous_compat = os.environ.get(GENERATED_HEADER_COMPAT_ENV)
    if compat_header is not None:
        os.environ[GENERATED_HEADER_COMPAT_ENV] = str(compat_header)
    else:
        os.environ.pop(GENERATED_HEADER_COMPAT_ENV, None)
    previous_ubt_args = os.environ.get("UBT_EXTRA_ARGS")
    if max_parallel_actions is not None:
        # BuildPlugin ignores -ubtargs; UBT reads this inherited env and keeps the first scalar value.
        os.environ["UBT_EXTRA_ARGS"] = "-MaxParallelActions={}".format(max_parallel_actions) + (
            " " + previous_ubt_args if previous_ubt_args else ""
        )
    try:
        if uses_legacy_ubt_config:
            with temporarily_clear_legacy_ubt_user_config(uat_dir.parent):
                run(cmd)
        else:
            run(cmd)
    finally:
        if previous_ubt_args is None:
            os.environ.pop("UBT_EXTRA_ARGS", None)
        else:
            os.environ["UBT_EXTRA_ARGS"] = previous_ubt_args
        if previous_compat is None:
            os.environ.pop(GENERATED_HEADER_COMPAT_ENV, None)
        else:
            os.environ[GENERATED_HEADER_COMPAT_ENV] = previous_compat


def merge_payload(payload_dir: Path, uat_dir: Path, final_plugin_dir: Path) -> None:
    remove_tree(final_plugin_dir)
    final_plugin_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(uat_dir), str(final_plugin_dir), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))

    python_src = payload_dir / "python"
    if python_src.is_dir():
        python_dst = final_plugin_dir / "python"
        if python_dst.exists():
            shutil.rmtree(str(python_dst))
        shutil.copytree(
            str(python_src), str(python_dst), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        )

    build_info = payload_dir / "BUILD_INFO.txt"
    if build_info.exists():
        shutil.copy2(str(build_info), str(final_plugin_dir / "BUILD_INFO.txt"))


def tree_hashes(root: Path) -> dict:
    """Capture build inputs, excluding only ordinary Python runtime caches."""
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        details = path.lstat()
        if path.is_symlink() or getattr(details, "st_file_attributes", 0) & 0x400:
            raise ValueError("Build input crosses a link: {}".format(path))
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def native_source_lock() -> dict:
    for name in ("Binaries", "Intermediate", "python"):
        if (PLUGIN_SOURCE.parent / name).exists():
            raise RuntimeError("Native build requires canonical source without generated {}".format(name))
    if (REPO_ROOT / "src" / "dcc_mcp_unreal" / "_plugin").exists():
        raise RuntimeError("Native build cannot use a previously packaged adapter as source")
    return {
        "src": tree_hashes(REPO_ROOT / "src"),
        "plugin": tree_hashes(PLUGIN_SOURCE.parent),
        "metadata": {
            name: hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest()
            for name in ("pyproject.toml", "README.md", "LICENSE")
            if name != "LICENSE" or (REPO_ROOT / name).exists()
        },
    }


def validate_native_output(args: argparse.Namespace, uat_dir: Path, source_lock: dict) -> dict:
    if native_source_lock() != source_lock:
        raise RuntimeError("Native build source changed during UAT")
    expected_source = {
        path[len("Source/") :]: digest for path, digest in source_lock["plugin"].items() if path.startswith("Source/")
    }
    if not expected_source or tree_hashes(uat_dir / "Source") != expected_source:
        raise RuntimeError("UAT output Source does not match the locked native source")
    editor = "UE4Editor" if read_engine_version(args.ue_root)[0] == 4 else "UnrealEditor"
    modules_name = editor + ".modules"
    engine_modules = args.ue_root / "Engine" / "Binaries" / "Win64" / modules_name
    engine_build_id = json.loads(engine_modules.read_text(encoding="utf-8"))["BuildId"]
    modules = json.loads((uat_dir / "Binaries" / "Win64" / modules_name).read_text(encoding="utf-8"))
    dll_name = editor + "-DccMcpUnreal.dll"
    if (
        not engine_build_id
        or modules.get("BuildId") != engine_build_id
        or modules.get("Modules", {}).get("DccMcpUnreal") != dll_name
    ):
        raise RuntimeError("UAT native module does not match the selected engine BuildId")
    dll = uat_dir / "Binaries" / "Win64" / dll_name
    if not dll.is_file() or not dll.stat().st_size:
        raise RuntimeError("UAT did not produce the native editor DLL")
    return {
        "engine_build_id": engine_build_id,
        "dll": dll.relative_to(uat_dir).as_posix(),
        "dll_sha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
        "payload": tree_hashes(uat_dir),
    }


def verify_native_wheel(wheel: Path, plugin_dir: Path) -> None:
    """Verify Hatch's complete RECORD and exact native payload, without modifying it."""
    prefix = "dcc_mcp_unreal/_plugin/"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        records = [
            name for name in names if name.endswith(".dist-info/RECORD") and "/" not in name.split(".dist-info/")[0]
        ]
        if len(names) != len(set(names)) or len(records) != 1:
            raise RuntimeError("Native wheel has duplicate members or invalid RECORD")
        rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode("utf-8"))))
        if len(rows) != len(names) or {row[0] for row in rows} != set(names):
            raise RuntimeError("Native wheel RECORD does not cover every member exactly")
        for name, digest, size in rows:
            data = archive.read(name)
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            if name == records[0]:
                if digest or size:
                    raise RuntimeError("Native wheel RECORD self-entry must be unhashed")
            elif digest != expected or size != str(len(data)):
                raise RuntimeError("Native wheel RECORD hash mismatch: {}".format(name))
        payload = {
            name[len(prefix) :]: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith(prefix)
        }
        if payload != tree_hashes(plugin_dir):
            raise RuntimeError("Native wheel payload does not equal the complete staged plugin")


def build_native_wheel(args: argparse.Namespace, plugin_dir: Path, source_lock: dict) -> Path:
    """Use a disposable source stage and the ordinary pip/Hatch wheel backend."""
    if native_source_lock() != source_lock:
        raise RuntimeError("Native build source changed before wheel construction")
    if not read_engine_tag(args.ue_root).startswith("ue4."):
        adapter = plugin_dir / "python" / "dcc_mcp_unreal"
        actual_adapter = tree_hashes(adapter)
        expected_adapter = {
            path[len("dcc_mcp_unreal/") :]: digest
            for path, digest in source_lock["src"].items()
            if path.startswith("dcc_mcp_unreal/")
        }
        actual_source = {path: digest for path, digest in actual_adapter.items() if not path.startswith("_plugin/")}
        if not expected_adapter or actual_source != expected_adapter:
            raise RuntimeError("Bootstrap adapter does not match the locked Python source")
        if tree_hashes(adapter / "_plugin") != source_lock["plugin"]:
            raise RuntimeError("Bootstrap adapter must contain only the canonical source plugin")
    stage = args.work_dir / "native-wheel-source"
    stage.mkdir()
    shutil.copytree(
        str(REPO_ROOT / "src"), str(stage / "src"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    )
    for name in source_lock["metadata"]:
        shutil.copy2(str(REPO_ROOT / name), str(stage / name))
    if tree_hashes(stage / "src") != source_lock["src"] or any(
        hashlib.sha256((stage / name).read_bytes()).hexdigest() != digest
        for name, digest in source_lock["metadata"].items()
    ):
        raise RuntimeError("Native wheel source stage differs from the locked source")
    shutil.copytree(
        str(plugin_dir),
        str(stage / "unreal" / "plugin"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    # Keep the repository's default wheel configuration intact. Only this
    # native build stage uses Hatch's standard platform-tag build hook.
    with (stage / "pyproject.toml").open("a", encoding="utf-8") as config:
        config.write('\n[tool.hatch.build.targets.wheel.hooks.custom]\npath = "_native_wheel_hook.py"\n')
    (stage / "_native_wheel_hook.py").write_text(
        "from hatchling.builders.hooks.plugin.interface import BuildHookInterface\n"
        "class CustomBuildHook(BuildHookInterface):\n"
        "    def initialize(self, version, build_data):\n"
        "        build_data['tag'] = 'py3-none-win_amd64'\n"
        "        build_data['pure_python'] = False\n",
        encoding="utf-8",
    )
    wheels = args.out_dir / "native-wheels"
    remove_tree(wheels)
    wheels.parent.mkdir(parents=True, exist_ok=True)
    wheels.mkdir()
    run([str(args.python or sys.executable), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), str(stage)])
    built = list(wheels.glob("dcc_mcp_unreal-*-py3-none-win_amd64.whl"))
    if len(built) != 1 or native_source_lock() != source_lock:
        raise RuntimeError("Native wheel output is ambiguous or build source changed")
    verify_native_wheel(built[0], plugin_dir)
    return built[0]


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def zip_final(final_plugin_dir: Path, ue_root: Path, mode: str) -> Path:
    version = read_plugin_version(final_plugin_dir)
    suffix = "win64" if mode == "native" else mode
    archive_base = REPO_ROOT / "dist" / "DccMcpUnreal-{}-{}-{}".format(version, read_engine_tag(ue_root), suffix)
    archive_path = Path(
        shutil.make_archive(str(archive_base), "zip", root_dir=str(final_plugin_dir.parent), base_dir="DccMcpUnreal")
    )
    return archive_path


def verify(final_plugin_dir: Path) -> None:
    run(
        [
            sys.executable,
            str(REPO_ROOT / "packaging" / "post_install.py"),
            "--plugin-root",
            str(final_plugin_dir),
        ]
    )


def rewrite_distribution_build_info(final_plugin_dir: Path, mode: str) -> None:
    build_info = final_plugin_dir / "BUILD_INFO.txt"
    lines = build_info.read_text(encoding="utf-8").splitlines() if build_info.exists() else []
    updated = []
    saw_mode = False
    for line in lines:
        if line.startswith("package_mode="):
            updated.append("package_mode={}".format(mode))
            saw_mode = True
        else:
            updated.append(line)
    if not saw_mode:
        updated.append("package_mode={}".format(mode))
    build_info.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue-root", default=str(DEFAULT_UE_ROOT), type=Path, help="Unreal Engine root")
    parser.add_argument("--python", default=None, type=Path, help="Python executable for vendoring dependencies")
    parser.add_argument(
        "--core-wheel", default=DEFAULT_CORE_WHEEL, type=Path, help="Local dcc-mcp-core wheel to vendor"
    )
    parser.add_argument("--core-wheel-url", default=DEFAULT_CORE_WHEEL_URL, help="URL to a dcc-mcp-core wheel artifact")
    parser.add_argument("--core-spec", default=DEFAULT_CORE_SPEC, help="dcc-mcp-core spec when no wheel is provided")
    parser.add_argument("--core-root", default=str(REPO_ROOT.parent / "dcc-mcp-core"), type=Path)
    parser.add_argument(
        "--use-local-core", action="store_true", help="Install dcc-mcp-core from source instead of a wheel"
    )
    parser.add_argument("--skip-core", action="store_true", help="Do not vendor dcc-mcp-core")
    parser.add_argument(
        "--vctoolchain-version",
        default=os.environ.get("VCTOOLCHAIN_VERSION", ""),
        help="MSVC toolchain version passed to UBT via -VCToolchainVersion=",
    )
    parser.add_argument(
        "--max-parallel-actions",
        type=positive_integer,
        default=None,
        help="Optional UBT action concurrency limit; defaults to engine behavior",
    )
    parser.add_argument(
        "--patched-headers-dir",
        default=os.environ.get("PATCHED_HEADERS_DIR", ""),
        help="Directory where a force-include header is written; path is passed to UBT via -AdditionalCompilerArguments /FI",
    )
    parser.add_argument(
        "--mode",
        choices=("native", "source", "python-only"),
        default=os.environ.get("DCC_MCP_UNREAL_PACKAGE_MODE", "native"),
        help="native: UAT precompiled package; source: source plugin with vendored Python; python-only: no C++ module",
    )
    parser.add_argument(
        "--python-plugin-name",
        default=os.environ.get("DCC_MCP_UNREAL_PYTHON_PLUGIN", "PythonScriptPlugin"),
        help="Unreal Python plugin dependency name; pass an empty string to omit the dependency",
    )
    parser.add_argument("--work-dir", default=str(REPO_ROOT / "dist" / "_uplugin_work"), type=Path)
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "dist" / "package"), type=Path)
    args = parser.parse_args()

    args.ue_root = args.ue_root.resolve()
    args.core_root = args.core_root.resolve()
    args.work_dir = args.work_dir.resolve()
    args.out_dir = args.out_dir.resolve()
    if args.core_wheel:
        args.core_wheel = args.core_wheel.resolve()
    else:
        args.core_wheel = None
    if not args.core_wheel_url:
        args.core_wheel_url = None
    if args.python:
        args.python = args.python.resolve()

    if not PLUGIN_SOURCE.exists():
        raise FileNotFoundError("Plugin descriptor not found: {}".format(PLUGIN_SOURCE))

    payload_dir = args.work_dir / "payload" / "DccMcpUnreal"
    uat_dir = args.work_dir / "uat" / "DccMcpUnreal"
    final_plugin_dir = args.out_dir / "DccMcpUnreal"

    remove_tree(args.work_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "native":
        source_lock = native_source_lock()
        build_precompiled_plugin(args, uat_dir)
        native_info = validate_native_output(args, uat_dir, source_lock)
        # A finite bootstrap payload makes the native wheel independently
        # installable: its _plugin already includes the host's Python runtime.
        build_python_payload(args, payload_dir)
        wheel_plugin_dir = args.work_dir / "wheel-payload" / "DccMcpUnreal"
        merge_payload(payload_dir, uat_dir, wheel_plugin_dir)
        rewrite_distribution_build_info(wheel_plugin_dir, args.mode)
        native_wheel = build_native_wheel(args, wheel_plugin_dir, source_lock)
        build_python_payload(args, payload_dir, native_wheel)
        merge_payload(payload_dir, uat_dir, final_plugin_dir)
        vendored_plugin = final_plugin_dir / "python" / "dcc_mcp_unreal" / "_plugin"
        if not read_engine_tag(args.ue_root).startswith("ue4.") and tree_hashes(vendored_plugin) != tree_hashes(
            wheel_plugin_dir
        ):
            raise RuntimeError("Vendored adapter did not consume the new native wheel")
        if not read_engine_tag(args.ue_root).startswith("ue4.") and not args.skip_core:
            bootstrap_core = tree_hashes(wheel_plugin_dir / "python" / "dcc_mcp_core")
            if not bootstrap_core or tree_hashes(final_plugin_dir / "python" / "dcc_mcp_core") != bootstrap_core:
                raise RuntimeError("Final vendoring changed the bootstrap Core package")
    else:
        build_python_payload(args, payload_dir)
        remove_tree(final_plugin_dir)
        final_plugin_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            str(payload_dir), str(final_plugin_dir), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        )
    rewrite_distribution_build_info(final_plugin_dir, args.mode)
    verify(final_plugin_dir)
    archive = zip_final(final_plugin_dir, args.ue_root, args.mode)

    if args.mode == "native":
        if validate_native_output(args, uat_dir, source_lock) != native_info:
            raise RuntimeError("UAT payload changed during native wheel packaging")
        final_files = tree_hashes(final_plugin_dir)
        if any(final_files.get(path) != digest for path, digest in native_info["payload"].items()):
            raise RuntimeError("Final plugin does not preserve the complete UAT payload")
        (args.out_dir / "native-wheel-build.json").write_text(
            json.dumps(
                {
                    "source_lock": source_lock,
                    "native": native_info,
                    "wheel": str(native_wheel),
                    "wheel_sha256": hashlib.sha256(native_wheel.read_bytes()).hexdigest(),
                    "core_wheel": str(args.core_wheel) if args.core_wheel else None,
                    "core_wheel_sha256": hashlib.sha256(args.core_wheel.read_bytes()).hexdigest()
                    if args.core_wheel
                    else None,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print("[build-uplugin] package: {}".format(final_plugin_dir))
    print("[build-uplugin] zip: {}".format(archive))
    if args.mode == "native":
        print("[build-uplugin] installer wheel: {}".format(native_wheel))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a distributable Unreal plugin zip.

This script creates a package suitable for users to drop into a project's
``Plugins/`` directory. It supports three modes:

* ``native``: vendors Python for UE5, runs Unreal AutomationTool
  ``BuildPlugin``, and writes
  ``dist/DccMcpUnreal-<version>-<ue-version>-win64.zip``. UE4 native packages
  use the standalone sidecar and omit the incompatible embedded dependencies.
* ``source``: vendors Python and keeps the C++ source module for engines that
  should compile the plugin locally.
* ``python-only``: vendors Python and strips the C++ module for legacy/internal
  engines that provide their own Python bridge.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
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


def run(cmd: List[str], *, cwd: Optional[Path] = None, log_path: Optional[Path] = None) -> None:
    print("[build-uplugin] " + " ".join(_quote(part) for part in cmd))
    if log_path is None:
        subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            cmd,
            cwd=str(cwd or REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            result = process.wait()
        if result:
            raise subprocess.CalledProcessError(result, cmd)


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
def ubt_user_config_lock(timeout: float = 120):
    """Serialize this repository's UAT jobs sharing one user configuration."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        yield
        return
    directory = Path(appdata) / "Unreal Engine" / "UnrealBuildTool"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "dcc-mcp-build.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another UAT job owns {}".format(directory)) from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


EMPTY_UBT_CONFIG = (
    '<?xml version="1.0" encoding="utf-8" ?>\n'
    '<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">\n'
    "</Configuration>\n"
).encode("utf-8")


def recover_legacy_ubt_user_config(config_path: Path) -> None:
    backup_path = config_path.with_name("BuildConfiguration.xml.dcc-mcp-backup")
    active_path = config_path.with_name("BuildConfiguration.xml.dcc-mcp-active")
    created_path = config_path.with_name("BuildConfiguration.xml.dcc-mcp-created")
    if not backup_path.exists():
        # A restore can complete before journal cleanup. Never use an orphaned
        # absence marker to decide ownership of a later user configuration.
        created_path.unlink(missing_ok=True)
        active_path.unlink(missing_ok=True)
        config_path.with_name("BuildConfiguration.xml.dcc-mcp-new").unlink(missing_ok=True)
        return
    # Do not overwrite a change from a user or an unrelated build during our job.
    expected = active_path.read_bytes() if active_path.exists() else EMPTY_UBT_CONFIG
    if config_path.exists() and config_path.read_bytes() not in (expected, backup_path.read_bytes()):
        raise RuntimeError("UBT configuration changed while guarded; original preserved at {}".format(backup_path))
    if created_path.exists():
        # Delete our new config before the backup: every crash boundary keeps
        # either a recoverable absence transaction or no owned configuration.
        config_path.unlink(missing_ok=True)
        backup_path.unlink()
        created_path.unlink()
    else:
        os.replace(str(backup_path), str(config_path))
    active_path.unlink(missing_ok=True)
    config_path.with_name("BuildConfiguration.xml.dcc-mcp-new").unlink(missing_ok=True)
    print("[build-uplugin] Restored UBT config: {}".format(config_path))


@contextlib.contextmanager
def temporarily_clear_legacy_ubt_user_config(work_dir: Path, compiler: str = "", sdk: str = ""):
    """Hide cross-version UBT settings, with a durable crash-recovery backup."""
    with ubt_user_config_lock():
        appdata = os.environ.get("APPDATA")
        if not appdata:
            yield
            return
        config_path = Path(appdata) / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
        recover_legacy_ubt_user_config(config_path)
        if not config_path.is_file() and not compiler and not sdk:
            yield
            return
        backup_path = config_path.with_name("BuildConfiguration.xml.dcc-mcp-backup")
        active_path = config_path.with_name("BuildConfiguration.xml.dcc-mcp-active")
        original_exists = config_path.is_file()
        if original_exists:
            config_path.with_name("BuildConfiguration.xml.dcc-mcp-created").unlink(missing_ok=True)
            shutil.copy2(str(config_path), str(backup_path))
        else:
            backup_path.write_bytes(b"")
            config_path.with_name("BuildConfiguration.xml.dcc-mcp-created").touch()
        # The backup lives beside the configuration, outside the disposable build directory.
        with backup_path.open("r+b") as backup:
            os.fsync(backup.fileno())
        try:
            content = EMPTY_UBT_CONFIG
            if compiler or sdk:
                configuration = ET.Element("Configuration", xmlns="https://www.unrealengine.com/BuildConfiguration")
                platform = ET.SubElement(configuration, "WindowsPlatform")
                for name, value in (("CompilerVersion", compiler), ("WindowsSdkVersion", sdk)):
                    if value:
                        ET.SubElement(platform, name).text = value
                content = ET.tostring(configuration, encoding="utf-8", xml_declaration=True)
            active_path.write_bytes(content)
            with active_path.open("r+b") as active:
                os.fsync(active.fileno())
            temporary_path = config_path.with_name("BuildConfiguration.xml.dcc-mcp-new")
            temporary_path.write_bytes(content)
            with temporary_path.open("r+b") as temporary:
                os.fsync(temporary.fileno())
            os.replace(str(temporary_path), str(config_path))
            print("[build-uplugin] Temporarily cleared cross-version UBT config: {}".format(config_path))
            yield
        finally:
            recover_legacy_ubt_user_config(config_path)
            if not original_exists:
                config_path.unlink(missing_ok=True)


def build_python_payload(args: argparse.Namespace, payload_dir: Path) -> None:
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
    """Discover all editions and custom locations through Microsoft's Setup API."""
    vswhere = shutil.which("vswhere")
    if not vswhere:
        vswhere = str(
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Microsoft Visual Studio"
            / "Installer"
            / "vswhere.exe"
        )
    if not Path(vswhere).is_file():
        raise FileNotFoundError(
            "vswhere is required to verify an explicit compiler; install Visual Studio Build Tools."
        )
    output = subprocess.check_output(
        [vswhere, "-all", "-products", "*", "-format", "json", "-utf8"], text=True, encoding="utf-8-sig"
    )
    candidates = [Path(instance["installationPath"]) / "VC" / "Tools" / "MSVC" for instance in json.loads(output)]
    roots = []
    for p in candidates:
        if p.is_dir():
            roots.extend(sorted(p.iterdir()))
    return roots


def _check_msvc_toolchain(version: str) -> None:
    """Fail before UAT when an explicitly requested compiler is not registered."""
    if not version:
        return
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
        raise ValueError("Compiler selection must be a numeric version, not Latest or Preview")
    roots = _msvc_toolchain_roots()
    installed = [d.name for d in roots if (d / "bin" / "Hostx64" / "x64" / "cl.exe").is_file()]
    if not any(v == version or v.startswith(version + ".") for v in installed):
        raise RuntimeError(
            "Requested MSVC {} is not registered with a usable x64 compiler. Available: {}. "
            "Provision the compatible VS C++ toolset or explicitly register msvc-kit before building.".format(
                version, ", ".join(sorted(installed)) or "none"
            )
        )


def verify_ubt_toolchain(log_path: Path, compiler: str = "", sdk: str = "") -> None:
    """Require evidence of UBT's actual selection for explicitly pinned builds."""
    if not compiler and not sdk:
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    selections = re.findall(r"Using .*? (14\.\d+\.\d+) toolchain \((.+?)\) and Windows (\d+(?:\.\d+){1,3}) SDK", text)
    if not selections:
        raise RuntimeError("UBT did not report its compiler/SDK selection; see {}".format(log_path))
    for actual_compiler, toolset_path, actual_sdk in selections:
        family = re.split(r"[/\\]", toolset_path.rstrip("/\\"))[-1]
        actual_family = family if re.fullmatch(r"14\.\d+\.\d+", family) else actual_compiler
        for label, expected, actual in (("compiler", compiler, actual_family), ("SDK", sdk, actual_sdk)):
            if expected and not (actual == expected or actual.startswith(expected + ".")):
                raise RuntimeError("UBT selected {} {}, expected {}; see {}".format(label, actual, expected, log_path))
        print(
            "[build-uplugin] Verified toolset family {}, compiler {}, SDK {}".format(
                actual_family, actual_compiler, actual_sdk
            )
        )


def build_precompiled_plugin(args: argparse.Namespace, uat_dir: Path) -> None:
    _check_msvc_toolchain(args.vctoolchain_version)
    sdk_version = getattr(args, "sdk_version", "")
    msvc_kit = getattr(args, "msvc_kit", "")
    if msvc_kit:
        diagnostics = [msvc_kit, "doctor", "--format", "json", "--compile", "--arch", "x64", "--host-arch", "x64"]
        for flag, value in (
            ("--msvc-version", args.vctoolchain_version),
            ("--sdk-version", sdk_version),
            ("--dir", getattr(args, "msvc_kit_dir", "")),
        ):
            if value:
                diagnostics += [flag, value]
        report = json.loads(subprocess.check_output(diagnostics, text=True, encoding="utf-8"))
        if report.get("schema") != "msvc-kit.doctor.v1" or report.get("status") != "passed":
            raise RuntimeError("Requested msvc-kit doctor did not report a supported, passing toolchain")
        uat_dir.parent.mkdir(parents=True, exist_ok=True)
        (uat_dir.parent / "toolchain-diagnostics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
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
    if args.vctoolchain_version:
        ubtargs.append("-CompilerVersion={}".format(args.vctoolchain_version))
    if sdk_version:
        if not re.fullmatch(r"\d+(?:\.\d+){3}", sdk_version):
            raise ValueError("SDK selection must be a complete numeric version")
        ubtargs.append("-WindowsSdkVersion={}".format(sdk_version))
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
    # BuildPlugin does not forward -ubtargs. Use the installed UBT entrypoint's
    # native argument environment contract, or the guarded legacy XML fallback.
    entrypoint = args.ue_root / "Engine" / "Source" / "Programs" / "UnrealBuildTool" / "UnrealBuildTool.cs"
    supports_extra_args = entrypoint.is_file() and "UBT_EXTRA_ARGS" in entrypoint.read_text(encoding="utf-8-sig")
    previous_extra_args = os.environ.get("UBT_EXTRA_ARGS")
    if supports_extra_args and ubtargs:
        os.environ["UBT_EXTRA_ARGS"] = " ".join(filter(None, [previous_extra_args, " ".join(ubtargs)]))
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
    try:
        log_path = uat_dir.parent / "uat-toolchain.log"

        def run_uat():
            if args.vctoolchain_version or sdk_version:
                run(cmd, log_path=log_path)
                verify_ubt_toolchain(log_path, args.vctoolchain_version, sdk_version)
            else:
                run(cmd)

        if uses_legacy_ubt_config or (ubtargs and not supports_extra_args):
            legacy_compiler = "" if supports_extra_args else args.vctoolchain_version
            legacy_sdk = "" if supports_extra_args else sdk_version
            with temporarily_clear_legacy_ubt_user_config(uat_dir.parent, legacy_compiler, legacy_sdk):
                run_uat()
        else:
            with ubt_user_config_lock():
                appdata = os.environ.get("APPDATA")
                if appdata:
                    recover_legacy_ubt_user_config(
                        Path(appdata) / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
                    )
                run_uat()
    finally:
        if previous_extra_args is None:
            os.environ.pop("UBT_EXTRA_ARGS", None)
        else:
            os.environ["UBT_EXTRA_ARGS"] = previous_extra_args
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
        help="Required MSVC compiler version passed to UBT via -CompilerVersion= and verified in its log",
    )
    parser.add_argument(
        "--sdk-version",
        default=os.environ.get("DCC_MCP_UNREAL_SDK_VERSION", ""),
        help="Required Windows SDK version passed to UBT and verified in its log",
    )
    parser.add_argument(
        "--msvc-kit",
        default=os.environ.get("DCC_MCP_UNREAL_MSVC_KIT", ""),
        help="Optional explicit msvc-kit executable for a JSON doctor/compile preflight",
    )
    parser.add_argument(
        "--msvc-kit-dir",
        default=os.environ.get("DCC_MCP_UNREAL_MSVC_KIT_DIR", ""),
        help="Optional toolchain directory for the requested msvc-kit preflight",
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

    build_python_payload(args, payload_dir)
    if args.mode == "native":
        build_precompiled_plugin(args, uat_dir)
        merge_payload(payload_dir, uat_dir, final_plugin_dir)
    else:
        remove_tree(final_plugin_dir)
        final_plugin_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            str(payload_dir), str(final_plugin_dir), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        )
    rewrite_distribution_build_info(final_plugin_dir, args.mode)
    verify(final_plugin_dir)
    archive = zip_final(final_plugin_dir, args.ue_root, args.mode)

    print("[build-uplugin] package: {}".format(final_plugin_dir))
    print("[build-uplugin] zip: {}".format(archive))


if __name__ == "__main__":
    main()

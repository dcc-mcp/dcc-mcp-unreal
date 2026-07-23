#!/usr/bin/env python3
"""Build a distributable Unreal plugin zip.

This script creates a package suitable for users to drop into a project's
``Plugins/`` directory. It supports three modes:

* ``native``: vendors Python, runs Unreal AutomationTool ``BuildPlugin``, and
  writes ``dist/DccMcpUnreal-<version>-<ue-version>-win64.zip``.
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
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = REPO_ROOT / "unreal" / "plugin" / "DccMcpUnreal.uplugin"
DEFAULT_UE_ROOT = Path(os.environ.get("UE_ROOT", r"C:\Program Files\Epic Games\UE_5.7"))
DEFAULT_CORE_WHEEL = os.environ.get("DCC_MCP_CORE_WHEEL")
DEFAULT_CORE_WHEEL_URL = os.environ.get("DCC_MCP_CORE_WHEEL_URL")
DEFAULT_CORE_SPEC = os.environ.get("DCC_MCP_CORE_SPEC", "dcc-mcp-core>=0.18.7,<1.0.0")


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
def temporarily_clear_ue4_user_config(work_dir: Path):
    """Hide cross-version UBT settings while an old engine is running."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        yield
        return

    config_path = Path(appdata) / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    if not config_path.is_file():
        yield
        return

    backup_path = work_dir / "ue4-user-BuildConfiguration.xml.backup"
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
    if is_ue4:
        with temporarily_clear_ue4_user_config(uat_dir.parent):
            run(cmd)
    else:
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
    is_ue4 = read_engine_tag(args.ue_root).startswith("ue4.")
    if is_ue4:
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
    run(cmd)


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
        help="MSVC toolchain version passed to UBT via -VCToolchainVersion=",
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

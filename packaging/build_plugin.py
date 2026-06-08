#!/usr/bin/env python3
"""Build a deployable Unreal Engine plugin package for dcc-mcp-unreal."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = REPO_ROOT / "unreal" / "plugin"
DEFAULT_OUT_DIR = REPO_ROOT / "dist" / "DccMcpUnreal"
DEFAULT_UE_ROOT = Path(os.environ.get("UE_ROOT", r"C:\Program Files\Epic Games\UE_5.2"))
DEFAULT_CORE_ROOT = Path(os.environ.get("DCC_MCP_CORE_ROOT", str(REPO_ROOT.parent / "dcc-mcp-core")))
DEFAULT_CORE_SPEC = os.environ.get("DCC_MCP_CORE_SPEC", "dcc-mcp-core>=0.18.7,<1.0.0")
DEFAULT_CORE_WHEEL = os.environ.get("DCC_MCP_CORE_WHEEL")


def run(cmd: List[str], *, cwd: Optional[Path] = None) -> None:
    print("[build-plugin] " + " ".join(_quote(part) for part in cmd))
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)


def _quote(value: str) -> str:
    return '"{}"'.format(value) if " " in value else value


def copytree_clean(src: Path, dst: Path) -> None:
    def ignore(_dir: str, names: Iterable[str]) -> set:
        return {name for name in names if name in {"__pycache__", ".pytest_cache"} or name.endswith((".pyc", ".pyo"))}

    shutil.copytree(str(src), str(dst), ignore=ignore)


def rewrite_plugin_descriptor(
    plugin_dir: Path,
    *,
    no_native: bool,
    python_plugin_name: str,
) -> None:
    descriptor = find_uplugin(plugin_dir)
    data = json.loads(descriptor.read_text(encoding="utf-8"))

    if no_native:
        data["Modules"] = []
        for rel in ("Source", "Binaries", "Intermediate"):
            path = plugin_dir / rel
            if path.exists():
                shutil.rmtree(str(path))

    if python_plugin_name:
        plugins = data.get("Plugins")
        if not isinstance(plugins, list):
            plugins = []
        plugins = [entry for entry in plugins if not (isinstance(entry, dict) and entry.get("Name") == "PythonScriptPlugin")]
        plugins.append({"Name": python_plugin_name, "Enabled": True})
        data["Plugins"] = plugins
    else:
        data.pop("Plugins", None)

    descriptor.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")


def remove_existing(path: Path) -> None:
    if not path.exists():
        return
    if path.name != "DccMcpUnreal":
        raise ValueError("Refusing to remove unexpected path: {}".format(path))
    shutil.rmtree(str(path))


def resolve_python(ue_root: Path, explicit_python: Optional[str]) -> Path:
    if explicit_python:
        return Path(explicit_python)
    ue_python = ue_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Win64" / "python.exe"
    if ue_python.exists():
        return ue_python
    return Path(sys.executable)


def install_python_payload(
    python_exe: Path,
    target_dir: Path,
    *,
    core_spec: str,
    core_wheel: Optional[Path],
    core_root: Path,
    use_local_core: bool,
    skip_core: bool,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    pip_base = [
        str(python_exe),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--ignore-installed",
        "--no-warn-script-location",
        "--target",
        str(target_dir),
    ]

    if not skip_core:
        if core_wheel is not None:
            if not core_wheel.exists():
                raise FileNotFoundError("dcc-mcp-core wheel not found: {}".format(core_wheel))
            run(pip_base + ["--no-deps", str(core_wheel)])
        elif use_local_core:
            if not core_root.exists():
                raise FileNotFoundError("Local dcc-mcp-core checkout not found: {}".format(core_root))
            run(pip_base + ["--no-deps", str(core_root)])
        else:
            run(
                pip_base
                + [
                    "--no-deps",
                    "--prefer-binary",
                    "--only-binary",
                    "dcc-mcp-core",
                    core_spec,
                ]
            )

    run(pip_base + ["--no-deps", str(REPO_ROOT)])


def read_plugin_version(plugin_dir: Path) -> str:
    descriptor = find_uplugin(plugin_dir)
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    return str(data.get("VersionName") or "0.0.0")


def find_uplugin(plugin_dir: Path) -> Path:
    preferred = plugin_dir / "DccMcpUnreal.uplugin"
    if preferred.exists():
        return preferred
    matches = sorted(plugin_dir.glob("*.uplugin"))
    if not matches:
        raise FileNotFoundError("No .uplugin descriptor found in {}".format(plugin_dir))
    return matches[0]


def write_build_info(
    out_dir: Path,
    *,
    python_exe: Path,
    core_spec: str,
    core_wheel: Optional[Path],
    core_root: Path,
    use_local_core: bool,
    skip_python_deps: bool,
    ue_root: Path,
    package_mode: str,
    python_plugin_name: str,
) -> None:
    version = read_plugin_version(out_dir)
    lines = [
        "dcc-mcp-unreal {}".format(version),
        "ue_root={}".format(ue_root),
        "python={}".format(python_exe),
        "core_spec={}".format(core_spec),
        "core_wheel={}".format(core_wheel or ""),
        "core_root={}".format(core_root),
        "use_local_core={}".format(use_local_core),
        "skip_python_deps={}".format(skip_python_deps),
        "package_mode={}".format(package_mode),
        "python_plugin_name={}".format(python_plugin_name),
    ]
    (out_dir / "BUILD_INFO.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_engine_tag(ue_root: Path) -> str:
    build_version = ue_root / "Engine" / "Build" / "Build.version"
    if build_version.exists():
        data = json.loads(build_version.read_text(encoding="utf-8"))
        major = data.get("MajorVersion")
        minor = data.get("MinorVersion")
        if major is not None and minor is not None:
            return "ue{}.{}".format(major, minor)
    return "ue"


def zip_plugin(out_dir: Path, ue_root: Path) -> Path:
    version = read_plugin_version(out_dir)
    zip_base = out_dir.parent / "DccMcpUnreal-{}-{}".format(version, read_engine_tag(ue_root))
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=str(out_dir.parent), base_dir=out_dir.name)
    return Path(archive)


def install_to_project(out_dir: Path, project_root: Path) -> Path:
    if project_root.suffix.lower() == ".uproject":
        project_root = project_root.parent
    if not project_root.exists():
        raise FileNotFoundError("Project root does not exist: {}".format(project_root))
    dest = project_root / "Plugins" / "DccMcpUnreal"
    remove_existing(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    copytree_clean(out_dir, dest)
    return dest


def install_to_engine(out_dir: Path, ue_root: Path) -> Path:
    dest = ue_root / "Engine" / "Plugins" / "DccMcpUnreal"
    remove_existing(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    copytree_clean(out_dir, dest)
    return dest


def build(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir).resolve()
    ue_root = Path(args.ue_root).resolve()
    core_root = Path(args.core_root).resolve()
    core_spec = str(args.core_spec)
    core_wheel = Path(args.core_wheel).resolve() if args.core_wheel else None
    python_exe = resolve_python(ue_root, args.python)

    if not PLUGIN_SOURCE.is_dir():
        raise FileNotFoundError("Plugin source directory not found: {}".format(PLUGIN_SOURCE))
    if not python_exe.exists():
        raise FileNotFoundError("Python executable not found: {}".format(python_exe))

    if args.clean:
        remove_existing(out_dir)
    elif out_dir.exists():
        raise FileExistsError("{} already exists; pass --clean to replace it".format(out_dir))

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    copytree_clean(PLUGIN_SOURCE, out_dir)
    rewrite_plugin_descriptor(
        out_dir,
        no_native=args.no_native,
        python_plugin_name=str(args.python_plugin_name),
    )

    if not args.skip_python_deps:
        install_python_payload(
            python_exe,
            out_dir / "python",
            core_spec=core_spec,
            core_wheel=core_wheel,
            core_root=core_root,
            use_local_core=args.use_local_core,
            skip_core=args.skip_core,
        )

    write_build_info(
        out_dir,
        python_exe=python_exe,
        core_spec=core_spec,
        core_wheel=core_wheel,
        core_root=core_root,
        use_local_core=args.use_local_core,
        skip_python_deps=args.skip_python_deps,
        ue_root=ue_root,
        package_mode="python-only" if args.no_native else "source",
        python_plugin_name=str(args.python_plugin_name),
    )

    print("[build-plugin] package: {}".format(out_dir))

    if args.zip:
        archive = zip_plugin(out_dir, ue_root)
        print("[build-plugin] zip: {}".format(archive))

    if args.install_project:
        dest = install_to_project(out_dir, Path(args.install_project).resolve())
        print("[build-plugin] installed project plugin: {}".format(dest))

    if args.install_engine:
        dest = install_to_engine(out_dir, ue_root)
        print("[build-plugin] installed engine plugin: {}".format(dest))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue-root", default=str(DEFAULT_UE_ROOT), help="Unreal Engine root; defaults to UE_5.2")
    parser.add_argument("--python", default=None, help="Python executable used for pip --target")
    parser.add_argument("--core-spec", default=DEFAULT_CORE_SPEC, help="dcc-mcp-core package spec for wheel installs")
    parser.add_argument("--core-wheel", default=DEFAULT_CORE_WHEEL, help="Local dcc-mcp-core wheel to vendor")
    parser.add_argument("--core-root", default=str(DEFAULT_CORE_ROOT), help="Local dcc-mcp-core checkout for --use-local-core")
    parser.add_argument("--use-local-core", action="store_true", help="Install dcc-mcp-core from --core-root instead of PyPI wheels")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output plugin directory")
    parser.add_argument("--clean", action="store_true", help="Remove an existing output plugin directory first")
    parser.add_argument("--zip", action="store_true", help="Also create a zip archive under dist/")
    parser.add_argument("--skip-python-deps", action="store_true", help="Only copy the uplugin files; do not pip install")
    parser.add_argument("--skip-core", action="store_true", help="Do not install dcc-mcp-core into python/")
    parser.add_argument("--no-native", action="store_true", help="Remove C++ module metadata and Source/ before packaging")
    parser.add_argument(
        "--python-plugin-name",
        default=os.environ.get("DCC_MCP_UNREAL_PYTHON_PLUGIN", "PythonScriptPlugin"),
        help="Unreal Python plugin dependency name; pass an empty string to omit the dependency",
    )
    parser.add_argument("--install-project", default=None, help="Copy package to <project>/Plugins/DccMcpUnreal")
    parser.add_argument("--install-engine", action="store_true", help="Copy package to <UE_ROOT>/Engine/Plugins/DccMcpUnreal")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()

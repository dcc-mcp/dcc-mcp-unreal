#!/usr/bin/env python3
"""Post-install verification for dcc-mcp-unreal plugin.

Checks that:
1. The plugin directory structure is correct
2. The .uplugin descriptor is valid JSON
3. The dcc_mcp_unreal Python package is importable from the plugin's python/ dir
4. The dcc_mcp_core dependency is present
5. The Content/Python/init_unreal.py entry point exists

Usage:
    python post_install.py --plugin-root /path/to/DccMcpUnreal
    python post_install.py  # auto-detect from script location
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check(condition: bool, msg_ok: str, msg_fail: str) -> bool:
    if condition:
        print(f"  [OK]   {msg_ok}")
    else:
        print(f"  [FAIL] {msg_fail}")
    return condition


def verify(plugin_root: Path) -> bool:
    print(f"\n[dcc-mcp-unreal] Post-install verification: {plugin_root}\n")
    passed = True

    # 1. Plugin root exists
    passed &= check(plugin_root.is_dir(), f"Plugin root exists: {plugin_root}", f"Plugin root not found: {plugin_root}")
    if not plugin_root.is_dir():
        return False

    # 2. .uplugin descriptor
    uplugin = plugin_root / "dcc_mcp_unreal.uplugin"
    passed &= check(uplugin.exists(), ".uplugin descriptor found", f".uplugin not found at {uplugin}")
    if uplugin.exists():
        try:
            data = json.loads(uplugin.read_text(encoding="utf-8"))
            passed &= check(
                "VersionName" in data,
                f".uplugin is valid JSON (VersionName={data.get('VersionName')})",
                ".uplugin JSON missing 'VersionName'",
            )
        except json.JSONDecodeError as exc:
            print(f"  [FAIL] .uplugin JSON parse error: {exc}")
            passed = False

    # 3. Content/Python/init_unreal.py
    init_py = plugin_root / "Content" / "Python" / "init_unreal.py"
    passed &= check(init_py.exists(), "Content/Python/init_unreal.py exists", f"init_unreal.py not found at {init_py}")

    # 4. python/ package directory (only present after `pip install --target`)
    python_dir = plugin_root / "python"
    if python_dir.is_dir():
        check(True, f"python/ package directory exists: {python_dir}", "")
        python_str = str(python_dir)
        if python_str not in sys.path:
            sys.path.insert(0, python_str)
    else:
        print(f"  [INFO] python/ not found at {python_dir} (expected after install, OK in dev mode)")

    # 5. dcc_mcp_unreal importable (from python/ or regular sys.path in dev mode)
    try:
        import dcc_mcp_unreal  # noqa: F401, PLC0415
        from dcc_mcp_unreal.__version__ import __version__  # noqa: PLC0415
        passed &= check(True, f"dcc_mcp_unreal importable (version={__version__})", "")
    except ImportError as exc:
        passed &= check(False, "", f"dcc_mcp_unreal import failed: {exc}")

    # 6. dcc_mcp_core importable
    try:
        import dcc_mcp_core  # noqa: F401, PLC0415
        passed &= check(True, "dcc_mcp_core importable", "")
    except ImportError as exc:
        passed &= check(False, "", f"dcc_mcp_core import failed: {exc}")

    print()
    if passed:
        print("[dcc-mcp-unreal] All checks passed. OK")
    else:
        print("[dcc-mcp-unreal] Some checks FAILED. See above for details.")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-install verification for dcc-mcp-unreal")
    parser.add_argument(
        "--plugin-root",
        default=None,
        help="Path to the installed plugin root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    if args.plugin_root:
        plugin_root = Path(args.plugin_root)
    else:
        # Auto-detect: this script lives in packaging/, plugin is in unreal/plugin/
        script_dir = Path(__file__).resolve().parent
        plugin_root = script_dir.parent / "unreal" / "plugin"

    ok = verify(plugin_root)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

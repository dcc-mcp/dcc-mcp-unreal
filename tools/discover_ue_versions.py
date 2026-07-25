"""Discover all Unreal Engine installations on the local machine.

Outputs JSON with each installation's engine version, path, and Python executable.
Used by CI to build the UE test matrix.
"""
from __future__ import annotations

import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

# Standard UE install locations on Windows
_UE_SEARCH_ROOTS: list[str] = []

if platform.system() == "Windows":
    _UE_SEARCH_ROOTS = [
        "C:/Program Files/Epic Games",
        "D:/Program Files/Epic Games",
        "E:/UNREAL",
        "F:/UE",
        "G:/UE",
        # Also check common non-standard locations
    ]
    for drive_letter in "CDEFGH":
        p = f"{drive_letter}:/UE"
        if p not in _UE_SEARCH_ROOTS:
            _UE_SEARCH_ROOTS.append(p)
        p = f"{drive_letter}:/UNREAL"
        if p not in _UE_SEARCH_ROOTS:
            _UE_SEARCH_ROOTS.append(p)


def _parse_ue_version(version_str: str) -> tuple[int, int] | None:
    """Parse 'UE_5.3' → (5, 3)."""
    m = re.match(r"UE[ _-]?(\d+)\.(\d+)", version_str, re.IGNORECASE)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def _find_ue_python(engine_root: Path) -> Path | None:
    """Find the UE-bundled Python interpreter under an engine root."""
    candidates = [
        engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Win64" / "python.exe",
        engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Linux" / "bin" / "python3",
        engine_root / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Mac" / "bin" / "python3",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _find_ue_cmd_exe(engine_root: Path) -> Path | None:
    """Find the command-line Unreal Editor executable."""
    candidates = [
        engine_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe",
        engine_root / "Engine" / "Binaries" / "Linux" / "UnrealEditor-Cmd",
        engine_root / "Engine" / "Binaries" / "Mac" / "UnrealEditor-Cmd",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _get_ue_version_from_build(engine_root: Path) -> str | None:
    """Try to read engine version from Build.version file."""
    build_ver = engine_root / "Engine" / "Build" / "Build.version"
    if not build_ver.is_file():
        return None
    try:
        data = json.loads(build_ver.read_text(encoding="utf-8"))
        major = data.get("MajorVersion", 0)
        minor = data.get("MinorVersion", 0)
        patch = data.get("PatchVersion", 0)
        changelist = data.get("Changelist", "")
        return f"{major}.{minor}.{patch}"
    except (json.JSONDecodeError, KeyError):
        return None


def discover() -> list[dict[str, Any]]:
    """Discover all UE installations and return structured data."""
    found: list[dict[str, Any]] = []

    for search_root_str in _UE_SEARCH_ROOTS:
        search_root = Path(search_root_str)
        if not search_root.is_dir():
            continue

        for entry in sorted(search_root.iterdir()):
            if not entry.is_dir():
                continue

            version_tuple = _parse_ue_version(entry.name)
            if version_tuple is None:
                continue

            # Verify this is actually a UE installation (has Engine dir)
            engine_dir = entry / "Engine"
            if not engine_dir.is_dir():
                continue

            python_exe = _find_ue_python(entry)
            cmd_exe = _find_ue_cmd_exe(entry)

            # Try to get precise version
            precise_version = _get_ue_version_from_build(entry) or f"{version_tuple[0]}.{version_tuple[1]}"

            found.append({
                "name": entry.name,
                "path": str(entry),
                "version": f"{version_tuple[0]}.{version_tuple[1]}",
                "version_tuple": list(version_tuple),
                "precise_version": precise_version,
                "python_exe": str(python_exe) if python_exe else None,
                "cmd_exe": str(cmd_exe) if cmd_exe else None,
                "has_python": python_exe is not None,
                "has_cmd": cmd_exe is not None,
                "testable": python_exe is not None and cmd_exe is not None,
            })

    # Sort by version descending
    found.sort(key=lambda x: x["version_tuple"], reverse=True)
    return found


def main() -> None:
    results = discover()
    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(f"Found {len(results)} UE installation(s):")
        for r in results:
            status = "✅ testable" if r["testable"] else "⚠️  no python/cmd"
            print(f"  {r['name']:12s} v{r['precise_version']:10s} {status}")
            print(f"    path:   {r['path']}")
            print(f"    python: {r['python_exe']}")
            print(f"    cmd:    {r['cmd_exe']}")
            print()


if __name__ == "__main__":
    main()

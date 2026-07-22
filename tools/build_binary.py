"""Build the PyOxidizer standalone Unreal sidecar launcher."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
OUTPUT = ROOT / "dist" / "standalone"
NAME = "dcc-mcp-unreal" + (".exe" if sys.platform == "win32" else "")


def _find_binary() -> Path:
    matches = sorted(path for path in BUILD.rglob(NAME) if "pyoxidizer" not in path.parts) if BUILD.exists() else []
    if not matches:
        raise FileNotFoundError("PyOxidizer did not produce {} under {}".format(NAME, BUILD))
    return matches[-1]


def _write_manifest(directory: Path) -> None:
    lines = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        lines.append("{}  {}".format(hashlib.sha256(path.read_bytes()).hexdigest(), path.relative_to(directory).as_posix()))
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, type=Path, help="dcc-mcp-server binary to bundle")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not args.server.is_file():
        parser.error("server binary does not exist: {}".format(args.server))

    subprocess.run(["pyoxidizer", "build", "--path", str(ROOT), *(["--verbose"] if args.verbose else [])], cwd=ROOT, check=True)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    binary = _find_binary()
    shutil.copy2(binary, OUTPUT / binary.name)
    shutil.copy2(args.server, OUTPUT / args.server.name)
    runtime = binary.parent / "lib"
    if runtime.is_dir():
        shutil.copytree(runtime, OUTPUT / "lib", dirs_exist_ok=True)
    if sys.platform == "win32":
        for dll in binary.parent.glob("*.dll"):
            shutil.copy2(dll, OUTPUT / dll.name)
    _write_manifest(OUTPUT)


if __name__ == "__main__":
    main()

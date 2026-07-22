"""Launch the native Unreal sidecar without requiring a system Python."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from .__version__ import __version__


def _server_binary(executable: Path) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    server = executable.resolve().parent / ("dcc-mcp-server" + suffix)
    if not server.is_file():
        raise FileNotFoundError("Bundled dcc-mcp-server was not found: {}".format(server))
    return server


def main(argv: Optional[Sequence[str]] = None) -> int:
    resolved = list(sys.argv if argv is None else argv)
    if resolved[1:] == ["--version"]:
        print(__version__)
        return 0
    return subprocess.call([str(_server_binary(Path(resolved[0]))), *resolved[1:]])


if __name__ == "__main__":
    raise SystemExit(main())

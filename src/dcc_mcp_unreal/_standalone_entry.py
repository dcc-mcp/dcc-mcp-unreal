"""Launch the native Unreal sidecar without requiring a system Python."""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Sequence

from .__version__ import __version__


def _server_binary(*executables: Path) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    candidates = [executable.resolve().parent / ("dcc-mcp-server" + suffix) for executable in executables]
    for server in candidates:
        if server.is_file():
            return server
    raise FileNotFoundError(
        "Bundled dcc-mcp-server was not found next to: {}".format(", ".join(str(path) for path in executables))
    )


def _is_unreal_sidecar(arguments: Sequence[str]) -> bool:
    try:
        sidecar_index = arguments.index("sidecar")
    except ValueError:
        return False
    trailing = list(arguments[sidecar_index + 1 :])
    for index, argument in enumerate(trailing):
        if argument == "--dcc" and index + 1 < len(trailing):
            return trailing[index + 1].lower() == "unreal"
        if argument.lower().startswith("--dcc="):
            return argument.split("=", 1)[1].lower() == "unreal"
    return False


@contextmanager
def _native_discovery() -> Iterator[str]:
    from .native_discovery import native_discovery_server  # noqa: PLC0415

    with native_discovery_server() as url:
        yield url


def main(argv: Optional[Sequence[str]] = None) -> int:
    resolved = list(sys.argv if argv is None else argv)
    if resolved[1:] == ["--version"]:
        print(__version__)
        return 0
    server = str(_server_binary(Path(resolved[0]), Path(sys.executable)))
    arguments = resolved[1:]
    if not _is_unreal_sidecar(arguments) or "--discovery-mcp-url" in arguments:
        return subprocess.call([server, *arguments])

    try:
        with _native_discovery() as discovery_url:
            return subprocess.call([server, *arguments, "--discovery-mcp-url", discovery_url])
    except Exception as exc:
        print("Native tool discovery failed; starting dispatch-only sidecar: {}".format(exc), file=sys.stderr)
        return subprocess.call([server, *arguments])


if __name__ == "__main__":
    raise SystemExit(main())

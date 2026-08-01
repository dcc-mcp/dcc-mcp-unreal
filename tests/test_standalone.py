from contextlib import contextmanager
from pathlib import Path

import pytest

from dcc_mcp_unreal import _standalone_entry


@pytest.fixture(autouse=True)
def stub_native_discovery(monkeypatch: pytest.MonkeyPatch):
    @contextmanager
    def discovery():
        yield "http://127.0.0.1:3987/mcp"

    monkeypatch.setattr(_standalone_entry, "_native_discovery", discovery)


def test_standalone_forwards_arguments_to_bundled_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launcher = tmp_path / ("dcc-mcp-unreal.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-unreal")
    server = tmp_path / ("dcc-mcp-server.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-server")
    server.touch()
    called = []
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command: called.append(command) or 7)

    assert _standalone_entry.main([str(launcher), "sidecar", "--dcc", "unreal"]) == 7
    assert called == [
        [
            str(server),
            "sidecar",
            "--dcc",
            "unreal",
            "--discovery-mcp-url",
            "http://127.0.0.1:3987/mcp",
        ]
    ]


def test_frozen_standalone_resolves_server_next_to_sys_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launcher = tmp_path / ("dcc-mcp-unreal.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-unreal")
    server = tmp_path / ("dcc-mcp-server.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-server")
    module_argv = tmp_path / "lib" / "dcc_mcp_unreal" / "_standalone_entry.py"
    server.touch()
    called = []
    monkeypatch.setattr(_standalone_entry.sys, "executable", str(launcher))
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command: called.append(command) or 0)

    assert _standalone_entry.main([str(module_argv), "sidecar", "--dcc", "unreal"]) == 0
    assert called == [
        [
            str(server),
            "sidecar",
            "--dcc",
            "unreal",
            "--discovery-mcp-url",
            "http://127.0.0.1:3987/mcp",
        ]
    ]


def test_standalone_requires_bundled_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_standalone_entry.sys, "executable", str(tmp_path / "missing-python"))

    with pytest.raises(FileNotFoundError, match="Bundled dcc-mcp-server"):
        _standalone_entry.main([str(tmp_path / "dcc-mcp-unreal"), "sidecar"])


def test_non_unreal_command_does_not_start_native_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launcher = tmp_path / ("dcc-mcp-unreal.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-unreal")
    server = tmp_path / ("dcc-mcp-server.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-server")
    server.touch()
    called = []
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command: called.append(command) or 0)

    assert _standalone_entry.main([str(launcher), "gateway"]) == 0
    assert called == [[str(server), "gateway"]]


def test_explicit_discovery_url_is_preserved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launcher = tmp_path / ("dcc-mcp-unreal.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-unreal")
    server = tmp_path / ("dcc-mcp-server.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-server")
    server.touch()
    called = []
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command: called.append(command) or 0)

    assert (
        _standalone_entry.main(
            [
                str(launcher),
                "sidecar",
                "--dcc",
                "unreal",
                "--discovery-mcp-url",
                "http://127.0.0.1:4100/mcp",
            ]
        )
        == 0
    )
    assert called == [
        [
            str(server),
            "sidecar",
            "--dcc",
            "unreal",
            "--discovery-mcp-url",
            "http://127.0.0.1:4100/mcp",
        ]
    ]

from pathlib import Path

import pytest

from dcc_mcp_unreal import _standalone_entry


def test_standalone_forwards_arguments_to_bundled_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launcher = tmp_path / ("dcc-mcp-unreal.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-unreal")
    server = tmp_path / ("dcc-mcp-server.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-server")
    server.touch()
    called = []
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command: called.append(command) or 7)

    assert _standalone_entry.main([str(launcher), "sidecar", "--dcc", "unreal"]) == 7
    assert called == [[str(server), "sidecar", "--dcc", "unreal"]]


def test_standalone_requires_bundled_server(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Bundled dcc-mcp-server"):
        _standalone_entry.main([str(tmp_path / "dcc-mcp-unreal"), "sidecar"])

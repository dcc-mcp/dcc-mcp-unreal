import json
import os
import subprocess
import sys
import textwrap
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
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command, **_kwargs: called.append(command) or 7)

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
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command, **_kwargs: called.append(command) or 0)

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
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command, **_kwargs: called.append(command) or 0)

    assert _standalone_entry.main([str(launcher), "gateway"]) == 0
    assert called == [[str(server), "gateway"]]


def test_explicit_discovery_url_is_preserved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launcher = tmp_path / ("dcc-mcp-unreal.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-unreal")
    server = tmp_path / ("dcc-mcp-server.exe" if _standalone_entry.sys.platform == "win32" else "dcc-mcp-server")
    server.touch()
    called = []
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command, **_kwargs: called.append(command) or 0)

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


@pytest.mark.parametrize("discovery_fails", [False, True])
def test_sidecar_is_hidden_even_when_discovery_fails(monkeypatch, tmp_path, discovery_fails):
    observed = []
    monkeypatch.setattr(_standalone_entry, "_server_binary", lambda *_args: tmp_path / "server")
    monkeypatch.setattr(_standalone_entry.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command, **kwargs: observed.append(kwargs) or 0)
    if discovery_fails:

        @contextmanager
        def discovery():
            raise RuntimeError("discovery unavailable")
            yield  # pragma: no cover

        monkeypatch.setattr(_standalone_entry, "_native_discovery", discovery)
    assert _standalone_entry.main(["launcher", "sidecar", "--dcc", "unreal"]) == 0
    assert observed == [{"creationflags": 0x08000000}]


def test_foreground_command_preserves_console_semantics(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(_standalone_entry, "_server_binary", lambda *_args: tmp_path / "server")
    monkeypatch.setattr(_standalone_entry.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(_standalone_entry.subprocess, "call", lambda command, **kwargs: observed.append(kwargs) or 0)
    assert _standalone_entry.main(["launcher", "gateway"]) == 0
    assert observed == [{"creationflags": 0}]


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows pythonw and console process APIs")
def test_real_sidecar_child_from_pythonw_has_no_console_and_preserves_streams(tmp_path):
    pythonw = Path(sys._base_executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip("pythonw.exe is unavailable")
    stdout_path, stderr_path = tmp_path / "stdout.txt", tmp_path / "stderr.txt"
    # A console Python process stands in for the Rust executable. The actual
    # wrapper and subprocess.call run unchanged under a GUI-subsystem parent.
    (tmp_path / "sidecar").write_text(
        "import ctypes,json,os,sys\n"
        "print(json.dumps({'pid':os.getpid(),'console':bool(ctypes.windll.kernel32.GetConsoleWindow())}))\n"
        "print('sidecar diagnostic',file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    parent = textwrap.dedent(f"""
        from pathlib import Path
        from dcc_mcp_unreal import _standalone_entry as entry
        entry._server_binary = lambda *_args: Path({str(sys.executable)!r})
        original_call = entry.subprocess.call
        output = open({str(stdout_path)!r}, 'w')
        errors = open({str(stderr_path)!r}, 'w')
        entry.subprocess.call = lambda argv,**kwargs: original_call(argv,stdout=output,stderr=errors,**kwargs)
        raise SystemExit(entry.main(['launcher','sidecar','--dcc','unreal','--discovery-mcp-url','probe']))
    """)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(p) for p in sys.path if p)
    result = subprocess.run(
        [str(pythonw), "-c", parent],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 7, result.stderr
    receipt = json.loads(stdout_path.read_text(encoding="utf-8"))
    assert receipt["console"] is False
    assert "sidecar diagnostic" in stderr_path.read_text(encoding="utf-8")

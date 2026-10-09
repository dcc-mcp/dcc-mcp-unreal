"""Owner configuration reaches Core without changing an active UI session."""

from __future__ import annotations

import importlib
import sys
import types

import pytest


@pytest.fixture
def runtime(tmp_path):
    module = importlib.import_module("dcc_mcp_core.server")
    options_type = getattr(module, "UiControlRuntimeOptions", None)
    if options_type is None:
        pytest.skip("Published Core does not yet expose owned UI Control")
    return options_type(
        binary=str(tmp_path / "dcc-cua-background.exe"),
        sha256="a" * 64,
        runtime_version="test-runtime",
        window_operations=("activate", "restore_activate"),
    )


def test_unsupported_core_refuses_explicit_runtime(monkeypatch):
    import dcc_mcp_core

    import dcc_mcp_unreal.server as server

    # Resolve the normal constructor before replacing only the optional API.
    assert dcc_mcp_core.DccServerOptions is not None
    monkeypatch.setitem(sys.modules, "dcc_mcp_core.server", types.ModuleType("dcc_mcp_core.server"))
    with pytest.raises(ImportError, match="UiControlRuntimeOptions support"):
        server.UnrealMcpServer(ui_control=object())


def test_default_bootstrap_preserves_published_core_support():
    from dcc_mcp_unreal.server import UnrealMcpServer

    server = UnrealMcpServer(port=0, enable_file_logging=False, enable_telemetry=False)
    assert server._ui_control_runtime is None


def test_runtime_reaches_core_unchanged(runtime):
    from dcc_mcp_unreal.server import UnrealMcpServer

    server = UnrealMcpServer(port=0, ui_control=runtime, enable_file_logging=False, enable_telemetry=False)
    assert server._options.ui_control is runtime
    assert server._options.ui_control.allowed_actions == ()
    assert server._options.ui_control.window_operations == ("activate", "restore_activate")


def test_untyped_runtime_is_rejected(runtime):
    from dcc_mcp_unreal.server import UnrealMcpServer

    with pytest.raises(TypeError, match="UiControlRuntimeOptions or None"):
        UnrealMcpServer(ui_control={"binary": runtime.binary})


def test_start_helper_forwards_runtime_without_starting_ui(monkeypatch, runtime):
    import dcc_mcp_unreal.server as server

    captured = {}

    def capture_start(self):
        captured["runtime"] = self._options.ui_control
        return "started"

    monkeypatch.setattr(server, "_server_instance", None)
    monkeypatch.setattr(server.UnrealMcpServer, "start", capture_start)
    assert server.start_server(port=0, register_builtins=False, ui_control=runtime) == "started"
    assert captured["runtime"] is runtime


@pytest.mark.parametrize("reuse", ["omitted", "same", "different"])
def test_active_server_cannot_silently_change_runtime(monkeypatch, runtime, reuse):
    from dataclasses import replace

    import dcc_mcp_unreal.server as server

    calls = []
    active = types.SimpleNamespace(
        is_running=True, _ui_control_runtime=runtime, start=lambda: calls.append(True) or "existing"
    )
    monkeypatch.setattr(server, "_server_instance", active)
    requested = {"omitted": None, "same": runtime, "different": replace(runtime, sha256="b" * 64)}[reuse]
    if reuse == "different":
        with pytest.raises(ValueError, match="Stop the running Unreal server"):
            server.start_server(ui_control=requested)
        assert calls == []
    else:
        assert server.start_server(ui_control=requested) == "existing"
        assert calls == [True]

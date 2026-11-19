"""Offline composition contracts: actual installed Core types, mocked host/OS.

The server/bootstrap are explicitly loaded as source under test;
their dependencies come from normally installed packages. No native
runtime, HTTP server, Editor, window API, observation or input is started.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import dcc_mcp_core
import dcc_mcp_core.server as core_server
import pytest

import dcc_mcp_unreal

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ENV = "DCC_MCP_UNREAL_UI_CONTROL_PROFILE"
SHA_ENV = "DCC_MCP_UNREAL_UI_CONTROL_PROFILE_SHA256"


@pytest.fixture
def owned_runtime_api():
    if not hasattr(core_server, "UiControlRuntimeOptions"):
        pytest.skip("Installed Core does not expose the optional owned UI Control API")


def _load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(monkeypatch):
    module = _load_source("dcc_mcp_unreal.composition_test_server", ROOT / "src/dcc_mcp_unreal/server.py")
    monkeypatch.setattr(module, "_make_execution_bridge", lambda _timeout: (SimpleNamespace(), object()))
    monkeypatch.setattr(
        module.DccServerBase, "__init__", lambda self, *, options: setattr(self, "test_options", options)
    )
    return module


@pytest.fixture
def bootstrap(monkeypatch, tmp_path):
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    monkeypatch.delenv(SHA_ENV, raising=False)
    monkeypatch.setenv("DCC_MCP_UNREAL_RUNTIME", "python")
    project = tmp_path / "Test.uproject"
    project.write_text("{}")
    binary = tmp_path / "dcc-cua-test.exe"
    binary.write_bytes(b"offline placeholder: never executed")
    identity = {
        "schema": "dcc-unreal-editor-main-frame/v1",
        "success": True,
        "reason": "ok",
        "host_pid": os.getpid(),
        "window_pid": os.getpid(),
        "window_handle": "4242",
    }
    calls = []
    fake_unreal = SimpleNamespace(
        Paths=SimpleNamespace(project_file_path=lambda: str(project), project_dir=lambda: str(tmp_path)),
        DccMcpEditorWindowLibrary=SimpleNamespace(get_main_frame_identity_json=lambda: json.dumps(identity)),
        is_editor=lambda: True,
        register_slate_post_tick_callback=lambda _callback: "mock-tick",
        log=lambda _message: None,
        log_warning=lambda _message: None,
    )
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(
        dcc_mcp_unreal,
        "start_server",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(mcp_url=lambda: "mock://not-started"),
    )
    module = _load_source("composition_test_bootstrap", ROOT / "unreal/plugin/Content/Python/init_unreal.py")
    profile = {
        "schema": "dcc-unreal-ui-control-owner/v1",
        "project_file": str(project),
        "binary": str(binary),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "runtime_version": "offline-test-version",
        "allowed_actions": ["keypress"],
    }

    context = SimpleNamespace(module=module, profile=profile, identity=identity, unreal=fake_unreal, calls=calls)

    def pin(data=None, *, raw=None, missing=None, digest=None):
        content = raw if raw is not None else json.dumps(data if data is not None else profile).encode()
        path = tmp_path / "owner.json"
        path.write_bytes(content)
        monkeypatch.setenv(PROFILE_ENV, str(path))
        monkeypatch.setenv(SHA_ENV, digest if digest is not None else hashlib.sha256(content).hexdigest())
        if missing is not None:
            monkeypatch.delenv(missing)
        context.module = _load_source(
            "composition_test_bootstrap", ROOT / "unreal/plugin/Content/Python/init_unreal.py"
        )
        return path

    context.pin = pin
    return context


def test_default_server_preserves_legacy_core_keyword_contract(server, monkeypatch):
    monkeypatch.delattr(core_server, "UiControlRuntimeOptions", raising=False)
    captured = {}

    def legacy_from_env(_name, _skills, **kwargs):
        assert not {"ui_control", "dcc_pid", "dcc_window_handle"} & kwargs.keys()
        captured.update(kwargs)
        return "legacy-options"

    monkeypatch.setattr(dcc_mcp_core.DccServerOptions, "from_env", legacy_from_env)
    instance = server.UnrealMcpServer(port=0)
    assert instance.test_options == "legacy-options"
    assert captured["port"] == 0


def test_default_server_accepts_actual_installed_core_options(server):
    instance = server.UnrealMcpServer(port=0)
    assert isinstance(instance.test_options, dcc_mcp_core.DccServerOptions)
    assert instance.test_options.port == 0
    assert getattr(instance.test_options, "ui_control", None) is None


def test_default_bootstrap_uses_no_new_core_type_or_native_getter(bootstrap, monkeypatch):
    monkeypatch.delattr(core_server, "UiControlRuntimeOptions", raising=False)
    del bootstrap.unreal.DccMcpEditorWindowLibrary
    del bootstrap.unreal.Paths
    bootstrap.module._start()
    assert bootstrap.calls == [{"server_name": "unreal-mcp", "extra_skill_paths": []}]


def test_typed_forwarding_uses_current_pid_and_exact_hwnd(server, monkeypatch, tmp_path, owned_runtime_api):
    from dcc_mcp_core.server import UiControlRuntimeOptions

    options = UiControlRuntimeOptions(binary=str(tmp_path / "candidate.exe"), sha256="a" * 64, runtime_version="test")
    captured = {}
    validated = []
    monkeypatch.setattr(server, "_assert_current_process_window", validated.append)
    monkeypatch.setattr(
        dcc_mcp_core.DccServerOptions, "from_env", lambda *_args, **kwargs: captured.update(kwargs) or "typed-options"
    )
    instance = server.UnrealMcpServer(ui_control=options, dcc_window_handle=4242)
    assert instance.test_options == "typed-options"
    assert captured["ui_control"] is options
    assert captured["dcc_pid"] == os.getpid()
    assert captured["dcc_window_handle"] == 4242
    assert validated == [4242]


def test_public_skill_bridge_reaches_owned_factory_and_strips_tool_forgery(
    server, monkeypatch, tmp_path, owned_runtime_api
):
    """Real installed binder/entrypoint/factory; abort at mocked client constructor.

    This does not exercise HTTP, gateway, CLI, Native protocol or any UI.
    """
    import dcc_mcp_core.host.cua_mcp_client as owned_client
    from dcc_mcp_core import HostExecutionBridge
    from dcc_mcp_core.server import UiControlRuntimeOptions

    options = UiControlRuntimeOptions(binary=str(tmp_path / "owner.exe"), sha256="a" * 64, runtime_version="owner")
    forged = replace(options, allowed_actions=("click",), runtime_version="attacker")
    bridge = HostExecutionBridge()
    registered = []
    reached = []

    def init_without_http(self, *, options):
        self._options = options
        self._dcc_name = options.dcc_name
        self._dcc_pid = options.diagnostics.dcc_pid
        self._dcc_window_handle = options.diagnostics.window_handle
        self._dcc_window_title = options.diagnostics.window_title
        self._config = SimpleNamespace(sandbox_policy=None)
        self._server = SimpleNamespace(set_in_process_executor=registered.append)
        self._quit_hooks = []

    def factory_boundary(**kwargs):
        reached.append(kwargs)
        raise ValueError("offline factory boundary: no client, session, process or observation")

    monkeypatch.setattr(server.DccServerBase, "__init__", init_without_http)
    monkeypatch.setattr(server.DccServerBase, "register_quit_hook", lambda self, hook: self._quit_hooks.append(hook))
    monkeypatch.setattr(server, "_make_execution_bridge", lambda _timeout: (SimpleNamespace(), bridge))
    monkeypatch.setattr(server, "_assert_current_process_window", lambda _handle: None)
    monkeypatch.setattr(owned_client, "PixelsMcpHostClient", factory_boundary)
    monkeypatch.setenv("DCC_MCP_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DCC_MCP_ARTEFACT_DIR", str(tmp_path / "artifacts"))
    instance = server.UnrealMcpServer(ui_control=options, dcc_window_handle=4242)
    instance.register_host_execution_bridge(bridge)
    assert len(registered) == 1
    script = Path(dcc_mcp_core.__file__).parent / "skills/ui-control/scripts/snapshot.py"
    try:
        result = registered[0](
            str(script),
            {
                "session_id": "adapter-offline-composition",
                "trusted_adapter_scope": {"process_id": 1, "window_handle": 2},
                "trusted_ui_control_runtime": forged,
            },
            skill_name="ui-control",
            action_name="ui_control__snapshot",
            trusted_adapter_scope={"process_id": 3, "window_handle": 4},
            trusted_ui_control_runtime=forged,
        )
    finally:
        bridge.shutdown_script_execution()
    assert result["success"] is False
    assert len(reached) == 1
    assert reached[0]["options"] is options
    assert reached[0]["options"].allowed_actions == ()
    assert reached[0]["process_id"] == os.getpid()
    assert reached[0]["window_handle"] == 4242


def test_running_server_refuses_changed_owner_configuration(server, monkeypatch, tmp_path, owned_runtime_api):
    from dcc_mcp_core.server import UiControlRuntimeOptions

    options = UiControlRuntimeOptions(binary=str(tmp_path / "candidate.exe"), sha256="a" * 64, runtime_version="test")
    monkeypatch.setattr(server, "_assert_current_process_window", lambda _handle: None)
    calls = []
    current = SimpleNamespace(
        is_running=True, _ui_control_binding=(options, 4242), start=lambda: calls.append(1) or "handle"
    )
    monkeypatch.setattr(server, "_server_instance", current)
    assert server.start_server(ui_control=options, dcc_window_handle=4242) == "handle"
    for kwargs in (
        {},
        {"ui_control": options, "dcc_window_handle": 4243},
        {"ui_control": replace(options, allowed_actions=("keypress",)), "dcc_window_handle": 4242},
    ):
        with pytest.raises(ValueError, match="configuration changed"):
            server.start_server(**kwargs)
    assert calls == [1]


def test_typed_binding_rejects_missing_hwnd_wrong_type_and_unowned_handle(server, tmp_path, owned_runtime_api):
    from dcc_mcp_core.server import UiControlRuntimeOptions

    options = UiControlRuntimeOptions(binary=str(tmp_path / "candidate.exe"), sha256="a" * 64, runtime_version="test")
    with pytest.raises(ValueError, match="exact current Editor HWND"):
        server._validate_ui_control_binding(options, None)
    with pytest.raises(TypeError, match="UiControlRuntimeOptions"):
        server._validate_ui_control_binding({"allowed_actions": ["keypress"]}, 4242)
    with pytest.raises(ValueError, match="typed owner"):
        server._validate_ui_control_binding(None, 4242)


@pytest.mark.parametrize("handle", [None, True, 0, -1, "4242", 1 << 64])
def test_exact_window_binding_rejects_invalid_hwnd_without_os_call(server, monkeypatch, handle):
    monkeypatch.setattr(server, "_IS_WINDOWS", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: pytest.fail("OS call must not run"), raising=False)
    with pytest.raises(ValueError):
        server._assert_current_process_window(handle)


def test_exact_window_binding_checks_actual_process_without_enumeration(server, monkeypatch):
    monkeypatch.setattr(server, "_IS_WINDOWS", True)
    owner = [os.getpid()]
    seen = []

    def get_pid(hwnd, output):
        seen.append(hwnd)
        output._obj.value = owner[0]
        return 1

    monkeypatch.setattr(
        ctypes, "WinDLL", lambda *_args, **_kwargs: SimpleNamespace(GetWindowThreadProcessId=get_pid), raising=False
    )
    server._assert_current_process_window(4242)
    owner[0] += 1
    with pytest.raises(ValueError, match="current Unreal process"):
        server._assert_current_process_window(4242)
    assert seen == [4242, 4242]


def test_profile_composes_actual_core_type_and_explicit_window_ceiling(bootstrap, owned_runtime_api):
    from dcc_mcp_core.server import UiControlRuntimeOptions

    bootstrap.profile["window_operations"] = ["activate", "restore_activate"]
    bootstrap.pin()
    bootstrap.module._start()
    kwargs = bootstrap.calls[0]
    assert type(kwargs["ui_control"]) is UiControlRuntimeOptions
    assert kwargs["ui_control"].allowed_actions == ("keypress",)
    assert kwargs["ui_control"].window_operations == ("activate", "restore_activate")
    assert kwargs["ui_control"].recording is None
    assert kwargs["dcc_window_handle"] == 4242


def test_launch_profile_pair_cannot_be_enabled_by_later_environment_changes(bootstrap):
    original_module = bootstrap.module
    bootstrap.pin()
    original_module._start()
    assert bootstrap.calls == [{"server_name": "unreal-mcp", "extra_skill_paths": []}]


def test_launch_pinned_profile_rejects_content_change_despite_new_environment_digest(bootstrap, monkeypatch):
    path = bootstrap.pin()
    bootstrap.profile["allowed_actions"] = []
    content = json.dumps(bootstrap.profile).encode()
    path.write_bytes(content)
    monkeypatch.setenv(SHA_ENV, hashlib.sha256(content).hexdigest())
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        bootstrap.module._start()
    assert bootstrap.calls == []


def test_profile_hardlink_is_rejected(bootstrap, tmp_path):
    path = bootstrap.pin()
    os.link(path, tmp_path / "second-profile.json")
    with pytest.raises(ValueError, match="ordinary file"):
        bootstrap.module._start()
    assert bootstrap.calls == []


@pytest.mark.parametrize(
    "change", ["unknown", "duplicate", "malformed", "oversized", "wrong_project", "bad_actions", "bad_window"]
)
def test_invalid_profile_never_calls_start_server(bootstrap, change, tmp_path):
    if change == "unknown":
        bootstrap.profile["dcc_window_handle"] = 9999
    elif change == "duplicate":
        content = json.dumps(bootstrap.profile).encode()
        bootstrap.pin(raw=content[:-1] + b', "allowed_actions": []}')
    elif change == "malformed":
        bootstrap.pin(raw=b"{")
    elif change == "oversized":
        bootstrap.pin(raw=b" " * 16385)
    elif change == "wrong_project":
        other = tmp_path / "Other.uproject"
        other.write_text("{}")
        bootstrap.profile["project_file"] = str(other)
    elif change == "bad_actions":
        bootstrap.profile["allowed_actions"] = ["keypress", "keypress"]
    elif change == "bad_window":
        bootstrap.profile["window_operations"] = ["minimize"]
    if change not in {"duplicate", "malformed", "oversized"}:
        bootstrap.pin()
    with pytest.raises(ValueError):
        bootstrap.module._start()
    assert bootstrap.calls == []


def test_sha_is_verified_before_any_json_parse(bootstrap, monkeypatch):
    bootstrap.pin(raw=b"not json", digest="0" * 64)
    monkeypatch.setattr(bootstrap.module.json, "loads", lambda *_a, **_kw: pytest.fail("must verify SHA first"))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        bootstrap.module._start()
    assert bootstrap.calls == []


@pytest.mark.parametrize("missing", [PROFILE_ENV, SHA_ENV])
def test_incomplete_profile_optin_fails_closed(bootstrap, monkeypatch, missing):
    bootstrap.pin(missing=missing)
    with pytest.raises(ValueError, match="both"):
        bootstrap.module._start()
    assert bootstrap.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("window_handle", "04242"),
        ("window_handle", 4242),
        ("window_pid", 1),
        ("host_pid", True),
        ("success", False),
        ("reason", "not_ready"),
    ],
)
def test_native_identity_must_match_exact_current_editor(bootstrap, field, value, owned_runtime_api):
    bootstrap.pin()
    bootstrap.identity[field] = value
    with pytest.raises(ValueError, match="MainFrame identity"):
        bootstrap.module._start()
    assert bootstrap.calls == []


def test_missing_native_getter_and_old_core_have_no_fallback(bootstrap, monkeypatch, owned_runtime_api):
    bootstrap.pin()
    del bootstrap.unreal.DccMcpEditorWindowLibrary
    with pytest.raises(RuntimeError, match="getter is required"):
        bootstrap.module._start()
    monkeypatch.delattr(core_server, "UiControlRuntimeOptions", raising=False)
    with pytest.raises(RuntimeError, match="Core does not support"):
        bootstrap.module._start()
    assert bootstrap.calls == []


def test_recording_requires_progress_capability_in_older_core(bootstrap, monkeypatch, tmp_path, owned_runtime_api):
    class OlderRecordingOptions:
        def __init__(self, *, output_root):
            self.output_root = output_root

    monkeypatch.setattr(core_server, "UiControlRecordingOptions", OlderRecordingOptions, raising=False)
    bootstrap.profile["recording_output_root"] = str(tmp_path)
    bootstrap.pin()
    with pytest.raises(RuntimeError, match="progress-required"):
        bootstrap.module._start()
    assert bootstrap.calls == []


def test_actual_recording_capability_receives_progress_required_owner_root(bootstrap, tmp_path, owned_runtime_api):
    import inspect

    recording_type = getattr(core_server, "UiControlRecordingOptions", None)
    if recording_type is None or "require_progress" not in inspect.signature(recording_type).parameters:
        pytest.skip("Installed Core does not support progress-required recording")
    bootstrap.profile["recording_output_root"] = str(tmp_path)
    bootstrap.pin()
    bootstrap.module._start()
    recording = bootstrap.calls[0]["ui_control"].recording
    assert recording.output_root == str(tmp_path)
    assert recording.require_progress is True


def test_profile_optin_cannot_silently_select_sidecar(bootstrap, monkeypatch):
    bootstrap.pin()
    monkeypatch.setenv("DCC_MCP_UNREAL_RUNTIME", "sidecar")
    with pytest.raises(RuntimeError, match="embedded Editor Python"):
        _load_source("composition_test_sidecar", ROOT / "unreal/plugin/Content/Python/init_unreal.py")
    assert bootstrap.calls == []

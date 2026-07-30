"""Tests for dcc-mcp-unreal (without a real Unreal Engine instance).

All tests run in a plain Python environment — no ``unreal`` module is available.
This covers the public API surface, helpers, and the server instantiation path.
"""

from __future__ import annotations

import importlib.util
import os
import runpy
import sys
import threading
import time
import types
from pathlib import Path

import pytest

if sys.version_info >= (3, 8):
    from importlib.metadata import version
else:
    from importlib_metadata import version

# ---------------------------------------------------------------------------
# Package-level imports
# ---------------------------------------------------------------------------


def test_import():
    """Package imports without errors."""
    import dcc_mcp_unreal

    assert dcc_mcp_unreal.__version__ == version("dcc-mcp-unreal")


def test_api_imports():
    """All public API symbols are importable from the top-level package."""
    from dcc_mcp_unreal import (
        UNREAL_CAPABILITIES_DICT,
        MissingParamError,
        UnrealMcpServer,
        UnrealNotAvailableError,
        actor_to_dict,
        build_context_dict,
        ensure_valid_name,
        get_param_list,
        get_unreal,
        is_unreal_available,
        missing_param_error,
        require_any_param,
        require_param,
        require_unreal,
        rotator_to_list,
        start_server,
        stop_server,
        unreal_capabilities,
        unreal_error,
        unreal_from_exception,
        unreal_success,
        unreal_warning,
        vector_to_list,
        with_unreal,
    )

    for sym in (
        UnrealMcpServer,
        start_server,
        stop_server,
        unreal_success,
        unreal_error,
        unreal_warning,
        unreal_from_exception,
        with_unreal,
        require_unreal,
        get_unreal,
        is_unreal_available,
        require_param,
        require_any_param,
        get_param_list,
        missing_param_error,
        ensure_valid_name,
        build_context_dict,
        vector_to_list,
        rotator_to_list,
        actor_to_dict,
        unreal_capabilities,
    ):
        assert callable(sym), f"{sym} should be callable"

    assert isinstance(UNREAL_CAPABILITIES_DICT, dict)
    assert issubclass(MissingParamError, ValueError)
    assert issubclass(UnrealNotAvailableError, ImportError)


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------


def test_is_unreal_available_false_outside_unreal():
    """is_unreal_available() returns False outside Unreal Engine."""
    from dcc_mcp_unreal import is_unreal_available

    assert is_unreal_available() is False


def test_get_unreal_returns_none_outside_unreal():
    """get_unreal() returns None when unreal module is absent."""
    from dcc_mcp_unreal import get_unreal

    assert get_unreal() is None


def test_require_unreal_raises_outside_unreal():
    """require_unreal() raises UnrealNotAvailableError when not in UE."""
    from dcc_mcp_unreal import UnrealNotAvailableError, require_unreal

    with pytest.raises(UnrealNotAvailableError):
        require_unreal()


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def test_unreal_success_returns_dict():
    """unreal_success() returns a success dict with expected keys."""
    from dcc_mcp_unreal import unreal_success

    result = unreal_success("test done", count=3)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert result.get("message") == "test done"


def test_unreal_success_with_prompt():
    """unreal_success() preserves the prompt field."""
    from dcc_mcp_unreal import unreal_success

    result = unreal_success("done", prompt="Check the viewport")
    assert result.get("prompt") == "Check the viewport"


def test_unreal_success_with_context():
    """unreal_success() stores extra kwargs in context."""
    from dcc_mcp_unreal import unreal_success

    result = unreal_success("ok", actor_name="SM_Cube", count=5)
    ctx = result.get("context", {})
    assert ctx.get("actor_name") == "SM_Cube"
    assert ctx.get("count") == 5


def test_unreal_error_returns_dict():
    """unreal_error() returns a failure dict."""
    from dcc_mcp_unreal import unreal_error

    result = unreal_error("failed", error="ImportError: unreal")
    assert isinstance(result, dict)
    assert result.get("success") is False
    assert result.get("error") == "ImportError: unreal"


def test_unreal_error_with_possible_solutions():
    """unreal_error() stores possible_solutions in context."""
    from dcc_mcp_unreal import unreal_error

    result = unreal_error(
        "Plugin not found",
        error="PluginError: Python plugin disabled",
        possible_solutions=["Enable Python Editor Script Plugin"],
    )
    assert result.get("success") is False
    ctx = result.get("context", {})
    assert "possible_solutions" in ctx
    assert "Enable Python Editor Script Plugin" in ctx["possible_solutions"]


def test_unreal_warning_returns_success_dict():
    """unreal_warning() returns success=True with a warning in context."""
    from dcc_mcp_unreal import unreal_warning

    result = unreal_warning("Done with issues", warning="Asset not found, used default")
    assert isinstance(result, dict)
    assert result.get("success") is True
    ctx = result.get("context", {})
    assert "warning" in ctx
    assert "Asset not found" in ctx["warning"]


def test_unreal_from_exception():
    """unreal_from_exception() builds error dict from an exception."""
    from dcc_mcp_unreal import unreal_from_exception

    try:
        raise RuntimeError("test error")
    except RuntimeError as exc:
        result = unreal_from_exception(exc, message="Skill failed")

    assert result.get("success") is False
    assert result.get("message") == "Skill failed"


def test_unreal_from_exception_default_message():
    """unreal_from_exception() uses default message when none given."""
    from dcc_mcp_unreal import unreal_from_exception

    try:
        raise ValueError("oops")
    except ValueError as exc:
        result = unreal_from_exception(exc)

    assert result.get("success") is False
    assert result.get("message") == "Unreal operation failed"


# ---------------------------------------------------------------------------
# with_unreal decorator
# ---------------------------------------------------------------------------


def test_with_unreal_catches_import_error():
    """@with_unreal catches ImportError and returns error dict."""
    from dcc_mcp_unreal import unreal_success, with_unreal

    @with_unreal
    def needs_unreal(**kwargs):
        import no_such_module_unreal  # noqa: F401

        return unreal_success("never")

    result = needs_unreal()
    assert result.get("success") is False
    assert "not available" in result.get("message", "").lower()


def test_with_unreal_catches_generic_exception():
    """@with_unreal catches general exceptions and returns error dict."""
    from dcc_mcp_unreal import with_unreal

    @with_unreal
    def broken(**kwargs):
        raise RuntimeError("something went wrong")

    result = broken()
    assert result.get("success") is False


def test_with_unreal_passes_through_success():
    """@with_unreal passes through a successful return value unchanged."""
    from dcc_mcp_unreal import unreal_success, with_unreal

    @with_unreal
    def good_func(x: int = 1, **kwargs):
        return unreal_success("good", value=x)

    result = good_func(x=42)
    assert result.get("success") is True
    assert result.get("context", {}).get("value") == 42


def test_with_unreal_accepts_positional_args():
    """@with_unreal accepts both *args and **kwargs."""
    from dcc_mcp_unreal import unreal_success, with_unreal

    @with_unreal
    def func_with_args(a, b, **kwargs):
        return unreal_success("ok", a=a, b=b)

    result = func_with_args(1, 2)
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# Parameter helpers
# ---------------------------------------------------------------------------


def test_require_param_returns_value():
    """require_param() returns the value when key exists."""
    from dcc_mcp_unreal import require_param

    params = {"actor_name": "SM_Cube", "radius": 100.0}
    assert require_param(params, "actor_name") == "SM_Cube"
    assert require_param(params, "radius") == 100.0


def test_require_param_returns_default():
    """require_param() returns default when key is absent."""
    from dcc_mcp_unreal import require_param

    params = {}
    assert require_param(params, "radius", 50.0) == 50.0


def test_require_param_raises_when_missing():
    """require_param() raises MissingParamError when key is absent and no default."""
    from dcc_mcp_unreal import MissingParamError, require_param

    with pytest.raises(MissingParamError, match="actor_name"):
        require_param({}, "actor_name")


def test_require_any_param_first_match():
    """require_any_param() returns first matching key."""
    from dcc_mcp_unreal import require_any_param

    params = {"node_name": "cube"}
    assert require_any_param(params, "actor_name", "node_name", "name") == "cube"


def test_require_any_param_raises_when_all_missing():
    """require_any_param() raises MissingParamError when none of the keys exist."""
    from dcc_mcp_unreal import MissingParamError, require_any_param

    with pytest.raises(MissingParamError):
        require_any_param({}, "actor_name", "name")


def test_missing_param_error_returns_dict():
    """missing_param_error() returns a failure dict."""
    from dcc_mcp_unreal import missing_param_error

    result = missing_param_error("actor_name")
    assert result.get("success") is False
    assert "actor_name" in result.get("message", "")


def test_get_param_list_bare_string():
    """get_param_list() coerces a bare string to a single-element list."""
    from dcc_mcp_unreal import get_param_list

    params = {"actors": "SM_Cube"}
    assert get_param_list(params, "actors") == ["SM_Cube"]


def test_get_param_list_already_list():
    """get_param_list() returns a list as-is."""
    from dcc_mcp_unreal import get_param_list

    params = {"actors": ["SM_Cube", "BP_Player"]}
    assert get_param_list(params, "actors") == ["SM_Cube", "BP_Player"]


def test_get_param_list_default():
    """get_param_list() returns [] when key is absent."""
    from dcc_mcp_unreal import get_param_list

    assert get_param_list({}, "actors") == []


# ---------------------------------------------------------------------------
# Name and context helpers
# ---------------------------------------------------------------------------


def test_ensure_valid_name_passes():
    """ensure_valid_name() returns None for a valid name."""
    from dcc_mcp_unreal import ensure_valid_name

    assert ensure_valid_name("SM_Cube") is None


def test_ensure_valid_name_empty():
    """ensure_valid_name() returns error dict for empty name."""
    from dcc_mcp_unreal import ensure_valid_name

    result = ensure_valid_name("", param="actor_name")
    assert isinstance(result, dict)
    assert result.get("success") is False
    assert "actor_name" in result.get("message", "")


def test_ensure_valid_name_whitespace():
    """ensure_valid_name() returns error dict for whitespace-only name."""
    from dcc_mcp_unreal import ensure_valid_name

    result = ensure_valid_name("   ")
    assert result.get("success") is False


def test_build_context_dict_filters_none():
    """build_context_dict() excludes None-valued keys."""
    from dcc_mcp_unreal import build_context_dict

    result = build_context_dict(a=1, b=None, c="hello")
    assert result == {"a": 1, "c": "hello"}


# ---------------------------------------------------------------------------
# Unreal data model helpers (no real unreal module)
# ---------------------------------------------------------------------------


class _FakeVector:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class _FakeRotator:
    def __init__(self, pitch, yaw, roll):
        self.pitch = pitch
        self.yaw = yaw
        self.roll = roll


def test_vector_to_list():
    """vector_to_list() converts a Vector-like object to [x, y, z]."""
    from dcc_mcp_unreal import vector_to_list

    v = _FakeVector(100.0, 200.0, 300.0)
    assert vector_to_list(v) == [100.0, 200.0, 300.0]


def test_rotator_to_list():
    """rotator_to_list() converts a Rotator-like object to [pitch, yaw, roll]."""
    from dcc_mcp_unreal import rotator_to_list

    r = _FakeRotator(10.0, 20.0, 30.0)
    assert rotator_to_list(r) == [10.0, 20.0, 30.0]


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def test_unreal_capabilities_dict():
    """UNREAL_CAPABILITIES_DICT has expected keys and Unreal-specific values."""
    from dcc_mcp_unreal import UNREAL_CAPABILITIES_DICT

    assert UNREAL_CAPABILITIES_DICT["transform"] is True
    assert UNREAL_CAPABILITIES_DICT["scene_manager"] is True
    assert UNREAL_CAPABILITIES_DICT["has_embedded_python"] is True
    # Unreal-specific: no DAG hierarchy, no progress window
    assert UNREAL_CAPABILITIES_DICT["hierarchy"] is False
    assert UNREAL_CAPABILITIES_DICT["progress_reporting"] is False


# ---------------------------------------------------------------------------
# Server instantiation (no real dcc-mcp-core required for these tests)
# ---------------------------------------------------------------------------


def test_server_instantiation():
    """UnrealMcpServer can be instantiated (requires dcc-mcp-core)."""
    from dcc_mcp_unreal import UnrealMcpServer

    server = UnrealMcpServer(port=9999)
    assert server._config is not None
    assert server._server is not None
    assert server._main_thread_dispatcher._http_dispatcher is not None
    assert server.is_running is False
    assert server.mcp_url is None


def test_server_forces_current_windows_ui_control_scope(monkeypatch):
    import dcc_mcp_unreal.server as server_module

    monkeypatch.setattr(server_module, "_IS_WINDOWS", True, raising=False)
    monkeypatch.setenv("DCC_MCP_UI_CONTROL_BACKEND", "mock")
    monkeypatch.setenv("DCC_MCP_UI_CONTROL_UIA_PROCESS_ID", "123")
    monkeypatch.setenv("DCC_MCP_UI_CONTROL_UIA_WINDOW_HANDLE", "456")

    server_module.UnrealMcpServer(port=0)

    assert os.environ["DCC_MCP_UI_CONTROL_BACKEND"] == "windows-uia"
    assert os.environ["DCC_MCP_UI_CONTROL_UIA_PROCESS_ID"] == str(os.getpid())
    assert "DCC_MCP_UI_CONTROL_UIA_WINDOW_HANDLE" not in os.environ


def test_server_start_repairs_ui_control_scope_drift(monkeypatch):
    import dcc_mcp_unreal.server as server_module

    monkeypatch.setattr(server_module, "_IS_WINDOWS", True, raising=False)
    server = server_module.UnrealMcpServer(port=0)
    monkeypatch.setenv("DCC_MCP_UI_CONTROL_BACKEND", "mock")
    monkeypatch.setenv("DCC_MCP_UI_CONTROL_UIA_PROCESS_ID", "123")
    monkeypatch.setenv("DCC_MCP_UI_CONTROL_UIA_WINDOW_HANDLE", "456")
    captured = {}

    def capture_start(_self, *, install_atexit_hook=True):
        captured.update(os.environ)
        return install_atexit_hook

    monkeypatch.setattr(server_module.DccServerBase, "start", capture_start)

    assert server.start(install_atexit_hook=False) is False
    assert captured["DCC_MCP_UI_CONTROL_BACKEND"] == "windows-uia"
    assert captured["DCC_MCP_UI_CONTROL_UIA_PROCESS_ID"] == str(os.getpid())
    assert "DCC_MCP_UI_CONTROL_UIA_WINDOW_HANDLE" not in captured


def test_server_custom_name():
    """UnrealMcpServer accepts custom server_name and server_version."""
    from dcc_mcp_unreal import UnrealMcpServer

    server = UnrealMcpServer(port=8765, server_name="my-unreal-mcp", server_version="1.2.3")
    assert server._config.server_name == "my-unreal-mcp"
    assert server._config.server_version == "1.2.3"


@pytest.mark.parametrize(("port", "expected"), [(None, 18765), (0, 0)])
def test_server_dynamic_port_and_explicit_zero_override_env(monkeypatch, port, expected):
    """Core owns env resolution while an explicit zero remains meaningful."""
    from dcc_mcp_unreal import UnrealMcpServer

    monkeypatch.setenv("DCC_MCP_UNREAL_PORT", "18765")
    server = UnrealMcpServer(port=port)
    assert server._config.port == expected


@pytest.mark.parametrize(
    "script_name",
    ["init_unreal.py", "dcc_mcp_unreal_startup.py"],
)
def test_unreal_bootstrap_delegates_instance_port_resolution_to_core(script_name):
    script = Path(__file__).parents[1] / "unreal" / "plugin" / "Content" / "Python" / script_name
    source = script.read_text(encoding="utf-8")
    assert 'os.environ.get("DCC_MCP_UNREAL_PORT"' not in source
    assert "start_server(port=" not in source


def test_unreal_bootstrap_skips_embedded_server_when_sidecar_is_selected():
    script = Path(__file__).parents[1] / "unreal" / "plugin" / "Content" / "Python" / "init_unreal.py"
    source = script.read_text(encoding="utf-8")

    assert 'runtime_mode = os.environ.get("DCC_MCP_UNREAL_RUNTIME", "auto").lower()' in source
    assert 'if runtime_mode == "sidecar":' in source


def test_main_thread_dispatcher_registers_one_tick_callback_on_the_game_thread(monkeypatch):
    """Worker dispatch must queue work without touching Slate from that worker."""
    from dcc_mcp_unreal.server import UnrealMainThreadDispatcher

    main_thread_id = threading.get_ident()
    callbacks = []
    unregistered = []

    def register_tick(callback):
        assert threading.get_ident() == main_thread_id
        callbacks.append(callback)
        return "tick-handle"

    def unregister_tick(handle):
        assert threading.get_ident() == main_thread_id
        unregistered.append(handle)

    fake_unreal = types.SimpleNamespace(
        register_slate_post_tick_callback=register_tick,
        unregister_slate_post_tick_callback=unregister_tick,
    )
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)

    dispatcher = UnrealMainThreadDispatcher(timeout_secs=1.0)
    assert len(callbacks) == 1

    native_ticks = []
    native_shutdown = []
    native_dispatcher = types.SimpleNamespace(
        pending=lambda: 1 if not native_ticks else 0,
        tick=lambda max_jobs: (
            native_ticks.append((threading.get_ident(), max_jobs)) or types.SimpleNamespace(jobs_executed=1)
        ),
        shutdown=lambda: native_shutdown.append(True),
    )
    dispatcher.attach_http_dispatcher(native_dispatcher)

    result = {}

    def run_worker():
        result["thread_id"] = dispatcher.dispatch_callable(threading.get_ident)

    worker = threading.Thread(target=run_worker)
    worker.start()
    for _ in range(100):
        if dispatcher._pending.qsize() == 1:
            break
        time.sleep(0.001)
    assert dispatcher._pending.qsize() == 1
    callbacks[0](0.0)
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert result["thread_id"] == main_thread_id
    assert len(callbacks) == 1
    assert native_ticks == [(main_thread_id, 16)]

    dispatcher.close()
    assert unregistered == ["tick-handle"]
    assert native_shutdown == [True]


def test_scene_publisher_runs_immediately_then_once_per_second(monkeypatch):
    from dcc_mcp_unreal.server import UnrealMainThreadDispatcher

    callbacks = []
    fake_unreal = types.SimpleNamespace(
        register_slate_post_tick_callback=lambda callback: callbacks.append(callback) or "tick-handle",
        unregister_slate_post_tick_callback=lambda _handle: None,
    )
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)
    dispatcher = UnrealMainThreadDispatcher()
    published = []
    dispatcher.attach_scene_publisher(lambda: published.append(True))

    callbacks[0](0.0)
    callbacks[0](0.5)
    callbacks[0](0.5)

    assert published == [True, True]


def test_server_publishes_changed_scene_to_gateway_and_resource(monkeypatch):
    import dcc_mcp_unreal.server as server_module

    server = server_module.UnrealMcpServer(port=0)
    snapshot = {"scene": "/Game/Maps/LiveMap", "world_type": "Editor"}
    monkeypatch.setattr(server_module, "_current_scene_snapshot", lambda: snapshot)
    resources = []
    gateway_scenes = []
    monkeypatch.setattr(server, "set_scene_resource", resources.append)
    monkeypatch.setattr(
        server,
        "update_gateway_metadata",
        lambda **kwargs: gateway_scenes.append(kwargs["scene"]),
    )

    server._publish_scene_context()
    server._publish_scene_context()

    assert resources == [snapshot]
    assert gateway_scenes == ["/Game/Maps/LiveMap"]


def test_init_unreal_registers_submenu_entries_and_releases_one_shot_tick(monkeypatch):
    """UE should expose one DCC MCP top-level menu, matching the other DCC hosts."""
    callbacks = []
    unregistered = []
    entries = []
    submenus = []

    class FakeHandle:
        @staticmethod
        def mcp_url():
            return "http://127.0.0.1:12345/mcp"

    fake_package = types.ModuleType("dcc_mcp_unreal")
    fake_package.__path__ = []
    fake_package.start_server = lambda **_kwargs: FakeHandle()
    fake_package.stop_server = lambda: None
    fake_version = types.ModuleType("dcc_mcp_unreal.__version__")
    fake_version.__version__ = "0.2.0"
    monkeypatch.setitem(sys.modules, "dcc_mcp_unreal", fake_package)
    monkeypatch.setitem(sys.modules, "dcc_mcp_unreal.__version__", fake_version)

    class FakeEntry:
        def __init__(self, name, type):
            self.name = name
            self.type = type

        def set_label(self, _label):
            pass

        def set_tool_tip(self, _tooltip):
            pass

        def set_string_command(self, **_kwargs):
            pass

    class FakeSubMenu:
        def __init__(self, name):
            self.name = name

        @staticmethod
        def add_section(_name, _label):
            pass

        def add_menu_entry(self, section, entry):
            entries.append((section, entry.name))

    class FakeMenu:
        @staticmethod
        def add_sub_menu(**kwargs):
            submenus.append(kwargs)
            return FakeSubMenu(kwargs["name"])

    class FakeToolMenusInstance:
        @staticmethod
        def extend_menu(_name):
            return FakeMenu()

        @staticmethod
        def refresh_all_widgets():
            pass

    fake_unreal = types.SimpleNamespace(
        AppMsgType=types.SimpleNamespace(OK="ok"),
        EditorDialog=types.SimpleNamespace(show_message=lambda **_kwargs: None),
        MultiBlockType=types.SimpleNamespace(MENU_ENTRY="menu-entry"),
        Name=lambda value: value,
        Text=lambda value: value,
        ToolMenuEntry=FakeEntry,
        ToolMenuStringCommandType=types.SimpleNamespace(PYTHON="python"),
        ToolMenus=types.SimpleNamespace(get=lambda: FakeToolMenusInstance()),
        is_editor=lambda: True,
        log=lambda _message: None,
        log_warning=lambda _message: None,
        register_slate_post_tick_callback=lambda callback: callbacks.append(callback) or "tick-handle",
        unregister_slate_post_tick_callback=lambda handle: unregistered.append(handle),
    )
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)
    monkeypatch.delenv("DCC_MCP_UI_CONTROL_BACKEND", raising=False)
    monkeypatch.delenv("DCC_MCP_UI_CONTROL_UIA_PROCESS_ID", raising=False)

    script = Path(__file__).parents[1] / "unreal" / "plugin" / "Content" / "Python" / "init_unreal.py"
    runpy.run_path(str(script), run_name="dcc_mcp_unreal_test_init")
    assert len(callbacks) == 1
    if sys.platform == "win32":
        assert os.environ["DCC_MCP_UI_CONTROL_BACKEND"] == "windows-uia"
        assert os.environ["DCC_MCP_UI_CONTROL_UIA_PROCESS_ID"] == str(os.getpid())
    else:
        assert "DCC_MCP_UI_CONTROL_BACKEND" not in os.environ
        assert "DCC_MCP_UI_CONTROL_UIA_PROCESS_ID" not in os.environ

    callbacks[0](0.0)

    assert submenus == [
        {
            "owner": "DccMcp",
            "section_name": "",
            "name": "DccMcp",
            "label": "DCC MCP",
            "tool_tip": "DCC MCP server controls",
        }
    ]
    assert entries == [
        ("DccMcpInstance", "DccMcp.CopyInstanceId"),
        ("DccMcpInstance", "DccMcp.ServerInfo"),
        ("DccMcpServer", "DccMcp.ShowUrl"),
        ("DccMcpControl", "DccMcp.Restart"),
        ("DccMcpControl", "DccMcp.Stop"),
        ("DccMcpAbout", "DccMcp.About"),
    ]
    assert unregistered == ["tick-handle"]


def test_asset_data_object_path_supports_ue58_and_legacy_api():
    helper_path = (
        Path(__file__).parents[1] / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts" / "_asset_data.py"
    )
    spec = importlib.util.spec_from_file_location("_test_unreal_asset_data", helper_path)
    assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    ue58 = types.SimpleNamespace(get_soft_object_path=lambda: "/Game/New.New")
    legacy = types.SimpleNamespace(object_path="/Game/Old.Old")
    fallback = types.SimpleNamespace(package_name="/Game/Fallback", asset_name="Fallback")

    assert helper.object_path(ue58) == "/Game/New.New"
    assert helper.object_path(legacy) == "/Game/Old.Old"
    assert helper.object_path(fallback) == "/Game/Fallback.Fallback"

    legacy_options = types.SimpleNamespace(
        include_packages=False,
        include_soft_package_references=True,
        include_hard_package_references=False,
        include_searchable_names=True,
        include_soft_management_references=True,
        include_hard_management_references=True,
    )
    assert helper.configure_dependency_options(legacy_options) is legacy_options
    assert legacy_options.include_packages is True
    assert legacy_options.include_hard_package_references is True
    assert legacy_options.include_soft_package_references is False
    modern_options = object()
    assert helper.configure_dependency_options(modern_options) is modern_options


def test_fbx_import_options_combine_meshes_and_select_named_asset():
    helper_path = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_unreal"
        / "skills"
        / "unreal-assets"
        / "scripts"
        / "_asset_import.py"
    )
    spec = importlib.util.spec_from_file_location("_test_unreal_asset_import", helper_path)
    assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    class FakeProperties:
        def __init__(self):
            self.values = {}

        def set_editor_property(self, name, value):
            self.values[name] = value

    class FakeOptions(FakeProperties):
        def __init__(self):
            super().__init__()
            self.static_mesh_data = FakeProperties()

        def get_editor_property(self, name):
            assert name == "static_mesh_import_data"
            return self.static_mesh_data

    unreal = types.SimpleNamespace(
        FbxImportUI=FakeOptions,
        FBXImportType=types.SimpleNamespace(
            FBXIT_STATIC_MESH="static",
            FBXIT_SKELETAL_MESH="skeletal",
        ),
    )

    options = helper.configure_fbx_options(
        unreal,
        combine_meshes=True,
        import_materials=True,
        import_textures=False,
    )

    assert options.values == {
        "import_mesh": True,
        "import_as_skeletal": False,
        "mesh_type_to_import": "static",
        "import_materials": True,
        "import_textures": False,
        "import_animations": False,
    }
    assert options.static_mesh_data.values == {"combine_meshes": True}
    assert (
        helper.primary_object_path(
            ["/Game/Import/colormap.colormap", "/Game/Import/SM_Creature.SM_Creature"],
            "SM_Creature",
        )
        == "/Game/Import/SM_Creature.SM_Creature"
    )
    assert (
        helper.primary_object_path(
            [
                "/Game/Import/SK_Creature_Skeleton.SK_Creature_Skeleton",
                "/Game/Import/SK_Creature1.SK_Creature1",
                "/Game/Import/SK_Creature_Anim.SK_Creature_Anim",
            ],
            "SK_Creature",
            import_as_skeletal=True,
        )
        == "/Game/Import/SK_Creature1.SK_Creature1"
    )

    skeletal_options = helper.configure_fbx_options(
        unreal,
        combine_meshes=True,
        import_materials=False,
        import_textures=True,
        import_as_skeletal=True,
        import_animations=True,
    )
    assert skeletal_options.values == {
        "import_mesh": True,
        "import_as_skeletal": True,
        "mesh_type_to_import": "skeletal",
        "import_materials": False,
        "import_textures": True,
        "import_animations": True,
    }
    assert skeletal_options.static_mesh_data.values == {}


def test_texture_material_skill_is_registered_and_builds_complete_graph():
    skill_root = Path(__file__).parents[1] / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets"
    tools = (skill_root / "tools.yaml").read_text(encoding="utf-8")
    script = (skill_root / "scripts" / "create_texture_material.py").read_text(encoding="utf-8")

    assert "name: create_texture_material" in tools
    assert "affinity: main" in tools
    assert "MaterialExpressionTextureCoordinate" in script
    assert "MaterialExpressionMultiply" in script
    assert "MP_BASE_COLOR" in script
    assert "MP_EMISSIVE_COLOR" in script
    assert "MSM_UNLIT" in script
    assert "SAMPLERTYPE_LINEAR_COLOR" in script
    assert "SAMPLERTYPE_NORMAL" in script
    assert "MP_NORMAL" in script
    assert "MP_ROUGHNESS" in script
    assert "MP_AMBIENT_OCCLUSION" in script
    assert "MP_METALLIC" in script
    assert "MP_SPECULAR" in script
    assert "normal_texture_path:" in tools
    assert "roughness_texture_path:" in tools
    assert "ambient_occlusion_texture_path:" in tools
    assert "metallic_texture_path:" in tools
    assert "base_color_scale:" in tools
    assert "unlit:" in tools


def test_blueprint_creation_skill_is_registered():
    skill_root = Path(__file__).parents[1] / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets"
    tools = (skill_root / "tools.yaml").read_text(encoding="utf-8")
    script = (skill_root / "scripts" / "create_blueprint.py").read_text(encoding="utf-8")

    assert "name: create_blueprint" in tools
    assert "parent_class_path:" in tools
    assert "unreal.BlueprintFactory()" in script
    assert 'factory.set_editor_property("parent_class", parent_class)' in script
    assert "save_loaded_asset" in script

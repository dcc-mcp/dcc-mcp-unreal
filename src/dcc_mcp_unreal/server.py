"""Embedded DCC-MCP server for Unreal Engine.

The adapter is intentionally thin: dcc-mcp-core owns MCP protocol handling,
skill discovery, diagnostic tools, gateway metadata, hot reload, and
in-process skill execution.  This module supplies Unreal-specific defaults:
the bundled skill directory, a UE main-thread dispatcher, version probing, and
small module-level start/stop helpers for ``init_unreal.py``.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from dcc_mcp_core.server import UiControlRuntimeOptions

from dcc_mcp_core import ChunkedRunner, HostUiDispatcherBase

try:
    from dcc_mcp_core import DccServerBase
except ImportError:  # pragma: no cover - only useful for partial installs
    DccServerBase = object  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

_BUILTIN_SKILLS_DIR = Path(__file__).parent / "skills"
_DEFAULT_DCC_NAME = "unreal"
_DEFAULT_SERVER_NAME = "unreal-mcp"
_DEFAULT_SERVER_VERSION = "0.1.0"
_IS_WINDOWS = os.name == "nt"
_SCENE_REFRESH_SECS = 1.0
_DISPATCH_BUDGET_MS = 4.0
# Own this identity in the package, shared by embedded startup paths and server
# restarts. Unreal executes multiple unrelated scripts named init_unreal.py.
_PROCESS_START_TOKEN = globals().get("_PROCESS_START_TOKEN") or uuid.uuid4().hex


def _configure_ui_control_for_process() -> None:
    """Bind Windows UI Control to this Unreal Editor process."""
    if not _IS_WINDOWS:
        return
    # Core 0.20 delegates native UI Control to standalone dcc-cua. The
    # adapter grants only its own process; requests may narrow but not widen it.
    os.environ["DCC_MCP_UI_CONTROL_BACKEND"] = "cua"
    os.environ["DCC_MCP_UI_CONTROL_PROCESS_ID"] = str(os.getpid())
    os.environ.pop("DCC_MCP_UI_CONTROL_WINDOW_HANDLE", None)
    for legacy_name in (
        "DCC_MCP_UI_CONTROL_UIA_PROCESS_ID",
        "DCC_MCP_UI_CONTROL_UIA_WINDOW_HANDLE",
        "DCC_MCP_APP_UI_BACKEND",
        "DCC_MCP_APP_UI_UIA_PROCESS_ID",
        "DCC_MCP_APP_UI_UIA_WINDOW_HANDLE",
    ):
        os.environ.pop(legacy_name, None)


def _assert_current_process_window(window_handle: int) -> None:
    """Validate an owner-supplied exact HWND without enumeration or activation."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    if not _IS_WINDOWS:
        raise ValueError("An exact Unreal HWND requires Windows")
    if type(window_handle) is not int or not 0 < window_handle < 1 << (8 * ctypes.sizeof(ctypes.c_void_p)):
        raise ValueError("dcc_window_handle must be an exact positive HWND integer")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_pid = user32.GetWindowThreadProcessId
    get_pid.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    get_pid.restype = wintypes.DWORD
    owner_pid = wintypes.DWORD()
    if not get_pid(window_handle, ctypes.byref(owner_pid)) or owner_pid.value != os.getpid():
        raise ValueError("dcc_window_handle must belong to the current Unreal process")


def _validate_ui_control_binding(ui_control: Any, dcc_window_handle: Optional[int]) -> None:
    if ui_control is not None:
        try:
            from dcc_mcp_core.server import UiControlRuntimeOptions  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("This Core does not support typed owned UI Control") from exc

        if not isinstance(ui_control, UiControlRuntimeOptions):
            raise TypeError("ui_control must be UiControlRuntimeOptions or None")
        if dcc_window_handle is None:
            raise ValueError("Owned UI Control requires an exact current Editor HWND")
    elif dcc_window_handle is not None:
        raise ValueError("An exact HWND requires typed owner UI Control configuration")
    if dcc_window_handle is not None:
        _assert_current_process_window(dcc_window_handle)


class UnrealMainThreadDispatcher(HostUiDispatcherBase):
    """Dispatch in-process skill calls onto Unreal's editor tick when needed.

    The MCP HTTP server handles requests off the editor thread.  Unreal's
    Python editor APIs are safest on the main/UI thread, so scene-touching
    tools declare ``affinity: main`` in ``tools.yaml`` and flow through this
    dispatcher via ``HostExecutionBridge``.
    """

    def __init__(self, timeout_secs: float = 60.0, main_thread_id: Optional[int] = None) -> None:
        super().__init__(label="Unreal Slate")
        self.timeout_secs = timeout_secs
        self.main_thread_id = main_thread_id if main_thread_id is not None else threading.get_ident()
        self._tick_handle: Any = None
        self._unregister_tick: Optional[Callable[[Any], Any]] = None
        self._scene_publisher: Optional[Callable[[], Any]] = None
        self._scene_elapsed = 0.0
        self._inside_unreal = False
        self._close_lock = threading.RLock()
        self._closed = threading.Event()
        self._draining = False

        try:
            import unreal  # noqa: PLC0415
        except ImportError:
            return

        self._inside_unreal = True
        register_tick = getattr(unreal, "register_slate_post_tick_callback", None)
        unregister_tick = getattr(unreal, "unregister_slate_post_tick_callback", None)
        if callable(register_tick) and callable(unregister_tick):
            if not self.is_host_thread():
                raise RuntimeError("Unreal dispatcher must be created on the host thread")
            self._unregister_tick = unregister_tick
            self._tick_handle = register_tick(self._on_tick)

    def poke_host_pump(self) -> None:
        """The existing recurring Slate callback already services this queue.

        Submissions never register another callback or run a recursive pump.
        """

    def is_host_thread(self) -> bool:
        return threading.get_ident() == self.main_thread_id

    def _require_host_pump(self) -> None:
        if self._tick_handle is None:
            raise RuntimeError("Unreal main-thread dispatch is unavailable")

    def submit_callable(
        self, request_id: str, task: Callable[[], Any], affinity: str = "main", timeout_ms: Optional[int] = None
    ) -> Dict[str, Any]:
        # Core's any-affinity fast path does not check shutdown.
        if self.is_shutdown:
            return {
                "request_id": request_id,
                "affinity": affinity,
                "success": False,
                "output": None,
                "error": "Interrupted",
            }
        if (affinity or "main").lower() == "main":
            self._require_host_pump()
            if self.is_host_thread():
                return self.run_on_any_thread(request_id, task, affinity)
        return super().submit_callable(request_id, task, affinity, timeout_ms)

    def format_timeout_error(self, request_id: str, affinity: str, timeout_sec: float) -> str:
        self.cancel(request_id)
        return super().format_timeout_error(request_id, affinity, timeout_sec)

    def submit_async_callable(self, request_id: str, task: Callable[[], Any], **kwargs: Any) -> Dict[str, Any]:
        if not self.is_shutdown and (kwargs.get("affinity") or "main").lower() == "main":
            self._require_host_pump()
        return super().submit_async_callable(request_id, task, **kwargs)

    def submit_chunked_runner(self, request_id: str, runner: ChunkedRunner, **kwargs: Any) -> Dict[str, Any]:
        if not self.is_shutdown:
            self._require_host_pump()
        return super().submit_chunked_runner(request_id, runner, **kwargs)

    def drain_queue(self, budget_ms: float) -> Tuple[int, int]:
        if not self.is_host_thread():
            raise RuntimeError("Unreal queue must be drained on the host thread")
        if self._draining:
            raise RuntimeError("Recursive Unreal queue draining is not supported")
        self._draining = True
        try:
            return super().drain_queue(budget_ms)
        finally:
            self._draining = False

    def attach_scene_publisher(self, publisher: Callable[[], Any]) -> None:
        """Run a lightweight scene publisher on the Unreal main thread."""
        self._scene_publisher = publisher
        self._scene_elapsed = _SCENE_REFRESH_SECS

    def dispatch_callable(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run ``func`` inline or on the next Unreal Slate tick."""
        affinity = str(kwargs.pop("affinity", "main") or "main").lower()
        timeout_hint_secs = kwargs.pop("timeout_hint_secs", None)

        # Metadata supplied by HostExecutionBridge; not arguments for func.
        kwargs.pop("context", None)
        kwargs.pop("action_name", None)
        kwargs.pop("skill_name", None)
        kwargs.pop("execution", None)

        if self.is_shutdown:
            raise RuntimeError("Unreal main-thread dispatcher is closed")
        if affinity not in ("main", "any"):
            raise ValueError("Unsupported Unreal thread affinity: {}".format(affinity))
        if affinity == "any" or self.is_host_thread():
            return func(*args, **kwargs)

        if not self._inside_unreal:
            # Standalone tests and non-UE interpreters intentionally run inline.
            return func(*args, **kwargs)

        errors: List[Exception] = []

        def invoke() -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                errors.append(exc)
                raise

        timeout = float(timeout_hint_secs or self.timeout_secs)
        result = self.submit_callable(uuid.uuid4().hex, invoke, timeout_ms=max(1, int(timeout * 1000)))
        if errors:
            raise errors[0]
        if not result["success"] and str(result["error"]).startswith("Timeout"):
            raise TimeoutError("Unreal main-thread dispatch timed out after {:.1f}s".format(timeout))
        if not result["success"]:
            raise RuntimeError(str(result["error"]))
        return result["output"]

    def _on_tick(self, _delta: float) -> None:
        if not self.is_host_thread():
            raise RuntimeError("Unreal Slate callback must run on the host thread")
        if self._draining:
            # Engine operations may pump Slate recursively. The outer drain
            # owns queue advancement, scene publication and deferred cleanup.
            return
        if self.is_shutdown:
            self._unregister_tick_callback()
            return
        # Cooperative budget: a running function cannot be pre-empted. Skills
        # must yield bounded steps; Core advances at most one chunk per drain.
        self.drain_queue(budget_ms=_DISPATCH_BUDGET_MS)
        if self.is_shutdown:
            self._unregister_tick_callback()
            return

        self._scene_elapsed += max(float(_delta), 0.0)
        if self._scene_publisher is not None and self._scene_elapsed >= _SCENE_REFRESH_SECS:
            self._scene_elapsed = 0.0
            try:
                self._scene_publisher()
            except Exception:
                logger.debug("Unable to publish Unreal scene context", exc_info=True)

    def close(self) -> None:
        # Wake pending workers before waiting for the host to detach Slate.
        with self._close_lock:
            if not self.is_shutdown:
                self.shutdown()
        if self.is_host_thread() and self._draining:
            # An active step may request close. Let it return to Core before
            # cancelling any continuation it requeues and removing Slate.
            return
        if self._tick_handle is None or self.is_host_thread():
            self._unregister_tick_callback()
            return
        if not self._closed.wait(self.timeout_secs):
            logger.warning("Unreal dispatcher is shut down; Slate callback removal awaits the host tick")

    def _unregister_tick_callback(self) -> None:
        if self.queue_size():
            self.shutdown()
        handle = self._tick_handle
        if handle is not None and self._unregister_tick is not None:
            if not self.is_host_thread():
                raise RuntimeError("Unreal Slate callback must be removed on the host thread")
            self._unregister_tick(handle)
        self._tick_handle = None
        self._scene_publisher = None
        self._http_dispatcher = None
        self._closed.set()


def _make_execution_bridge(timeout_secs: float) -> Any:
    from dcc_mcp_core import HostExecutionBridge  # noqa: PLC0415

    from dcc_mcp_unreal.skill_runner import run_skill_script as _unreal_run_skill_script

    dispatcher = UnrealMainThreadDispatcher(timeout_secs=timeout_secs)
    bridge = HostExecutionBridge(
        dispatcher=dispatcher,
        runner=_unreal_run_skill_script,
        default_thread_affinity="main",
        default_execution="sync",
        default_timeout_hint_secs=int(timeout_secs),
    )
    return dispatcher, bridge


class UnrealMcpServer(DccServerBase):  # type: ignore[misc]
    """DCC-MCP server composition root for Unreal Engine."""

    def __init__(
        self,
        port: Optional[int] = None,
        server_name: str = _DEFAULT_SERVER_NAME,
        server_version: str = _DEFAULT_SERVER_VERSION,
        *,
        gateway_port: Optional[int] = None,
        registry_dir: Optional[str] = None,
        enable_gateway_failover: bool = True,
        execution_timeout_secs: float = 60.0,
        enable_file_logging: bool = True,
        enable_job_persistence: bool = True,
        enable_telemetry: bool = True,
        ui_control: Optional["UiControlRuntimeOptions"] = None,
        dcc_window_handle: Optional[int] = None,
    ) -> None:
        if DccServerBase is object:  # pragma: no cover - defensive install error
            raise ImportError("dcc-mcp-core is required to create UnrealMcpServer")

        from dcc_mcp_core import DccServerOptions  # noqa: PLC0415

        _validate_ui_control_binding(ui_control, dcc_window_handle)
        self._ui_control_binding = (ui_control, dcc_window_handle)
        self._ui_control_runtime = ui_control
        _configure_ui_control_for_process()
        self._main_thread_dispatcher, bridge = _make_execution_bridge(execution_timeout_secs)
        options = DccServerOptions.from_env(
            _DEFAULT_DCC_NAME,
            _BUILTIN_SKILLS_DIR,
            port=port,
            server_name=server_name,
            server_version=server_version,
            gateway_port=gateway_port,
            registry_dir=registry_dir,
            enable_gateway_failover=enable_gateway_failover,
            enable_file_logging=enable_file_logging,
            enable_job_persistence=enable_job_persistence,
            enable_telemetry=enable_telemetry,
            execution_bridge=bridge,
            **(
                {"ui_control": ui_control, "dcc_pid": os.getpid(), "dcc_window_handle": dcc_window_handle}
                if ui_control is not None
                else {}
            ),
        )
        super().__init__(options=options)
        self._last_scene_snapshot: Optional[Dict[str, Any]] = None

    @property
    def process_start_token(self) -> str:
        """Opaque process-scoped identity, independent of Engine startup modules."""
        return _PROCESS_START_TOKEN

    def start(self, *, install_atexit_hook: bool = True) -> Any:
        """Start with UI Control scoped to the current Unreal process."""
        _validate_ui_control_binding(*self._ui_control_binding)
        _configure_ui_control_for_process()
        handle = super().start(install_atexit_hook=install_atexit_hook)
        self._main_thread_dispatcher.attach_scene_publisher(self._publish_scene_context)
        return handle

    def _publish_scene_context(self) -> None:
        snapshot = _current_scene_snapshot()
        if snapshot is None or snapshot == self._last_scene_snapshot:
            return
        previous_scene = (self._last_scene_snapshot or {}).get("scene")
        self._last_scene_snapshot = snapshot
        self.set_scene_resource(snapshot)
        if snapshot.get("scene") != previous_scene:
            self.update_gateway_metadata(scene=str(snapshot.get("scene") or ""))

    def stop(self) -> None:
        try:
            super().stop()
        finally:
            self._main_thread_dispatcher.close()

    def _version_string(self) -> str:
        try:
            from dcc_mcp_unreal.api import get_unreal  # noqa: PLC0415

            unreal = get_unreal()
            if unreal is None:
                return "unknown"
            system_library = getattr(unreal, "SystemLibrary", None)
            if system_library is not None and hasattr(system_library, "get_engine_version"):
                return str(system_library.get_engine_version())
        except Exception:
            logger.debug("Unable to query Unreal Engine version", exc_info=True)
        return "unknown"

    def register_builtin_actions(
        self,
        extra_skill_paths: Optional[List[str]] = None,
        *,
        include_bundled: bool = True,
        eager_load: bool = True,
    ) -> "UnrealMcpServer":
        """Discover Unreal skills and optionally load Unreal tools eagerly."""
        super().register_builtin_actions(
            extra_skill_paths=extra_skill_paths,
            include_bundled=include_bundled,
        )

        if eager_load:
            self._load_discovered_unreal_skills()
        return self

    def _load_discovered_unreal_skills(self) -> None:
        loaded = 0
        failed = 0
        for summary in self.list_skills():
            skill_name = _summary_value(summary, "name")
            if not skill_name or not _is_unreal_skill(self, summary, skill_name):
                continue
            if self.is_skill_loaded(skill_name):
                continue
            try:
                self.load_skill(skill_name)
                loaded += 1
            except Exception as exc:
                logger.warning("Failed to load Unreal skill %r: %s", skill_name, exc)
                failed += 1

        logger.info("Unreal skills loaded: %d loaded, %d failed", loaded, failed)

    def find_skills(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        dcc: Optional[str] = None,
    ) -> List[Any]:
        """Backward-compatible alias for catalog skill search."""
        return list(self.search_skills(query=query, tags=tags, dcc=dcc))

    def get_capabilities(self) -> Any:
        from dcc_mcp_unreal.capabilities import unreal_capabilities  # noqa: PLC0415

        return unreal_capabilities()


def _summary_value(summary: Any, key: str) -> Any:
    if hasattr(summary, key):
        return getattr(summary, key)
    if isinstance(summary, dict):
        return summary.get(key)
    return None


def _current_scene_snapshot() -> Optional[Dict[str, Any]]:
    from dcc_mcp_unreal.api import get_unreal  # noqa: PLC0415

    unreal = get_unreal()
    editor_level_library = getattr(unreal, "EditorLevelLibrary", None) if unreal is not None else None
    if editor_level_library is None:
        return None
    world = editor_level_library.get_editor_world()
    if world is None:
        return {"scene": None, "world_type": None}
    package = world.get_outer()
    scene = package.get_name() if package is not None else world.get_name()
    world_type = str(world.world_type) if hasattr(world, "world_type") else None
    return {"scene": str(scene), "world_type": world_type}


def _is_unreal_skill(server: UnrealMcpServer, summary: Any, skill_name: str) -> bool:
    dcc = _summary_value(summary, "dcc")
    if dcc == _DEFAULT_DCC_NAME:
        return True
    if skill_name.startswith("unreal-"):
        return True

    try:
        info = server.get_skill_info(skill_name)
    except Exception:
        return False

    info_dcc = _summary_value(info, "dcc")
    if info_dcc == _DEFAULT_DCC_NAME:
        return True
    metadata = _summary_value(info, "metadata")
    if isinstance(metadata, dict):
        dcc_mcp = metadata.get("dcc-mcp") or metadata.get("dcc_mcp") or {}
        if isinstance(dcc_mcp, dict) and dcc_mcp.get("dcc") == _DEFAULT_DCC_NAME:
            return True
    return False


_server_instance: Optional[UnrealMcpServer] = None
_lock = threading.Lock()


def start_server(
    port: Optional[int] = None,
    server_name: str = _DEFAULT_SERVER_NAME,
    server_version: str = _DEFAULT_SERVER_VERSION,
    register_builtins: bool = True,
    extra_skill_paths: Optional[List[str]] = None,
    *,
    include_bundled: bool = True,
    eager_load: bool = True,
    gateway_port: Optional[int] = None,
    registry_dir: Optional[str] = None,
    enable_gateway_failover: bool = True,
    ui_control: Optional["UiControlRuntimeOptions"] = None,
    dcc_window_handle: Optional[int] = None,
) -> Any:
    """Start, or return, the module-level Unreal MCP server handle."""
    global _server_instance
    with _lock:
        _validate_ui_control_binding(ui_control, dcc_window_handle)
        if _server_instance is not None and _server_instance.is_running:
            if _server_instance._ui_control_binding != (ui_control, dcc_window_handle):
                raise ValueError("UI Control configuration changed; stop the server before rebinding")
        if _server_instance is None or not _server_instance.is_running:
            _server_instance = UnrealMcpServer(
                port=port,
                server_name=server_name,
                server_version=server_version,
                gateway_port=gateway_port,
                registry_dir=registry_dir,
                enable_gateway_failover=enable_gateway_failover,
                ui_control=ui_control,
                dcc_window_handle=dcc_window_handle,
            )
            if register_builtins:
                _server_instance.register_builtin_actions(
                    extra_skill_paths=extra_skill_paths,
                    include_bundled=include_bundled,
                    eager_load=eager_load,
                )
        return _server_instance.start()


def stop_server() -> None:
    """Stop the module-level Unreal MCP server."""
    global _server_instance
    with _lock:
        if _server_instance is not None:
            _server_instance.stop()
            _server_instance = None

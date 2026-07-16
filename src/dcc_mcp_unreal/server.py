"""Embedded DCC-MCP server for Unreal Engine.

The adapter is intentionally thin: dcc-mcp-core owns MCP protocol handling,
skill discovery, diagnostic tools, gateway metadata, hot reload, and
in-process skill execution.  This module supplies Unreal-specific defaults:
the bundled skill directory, a UE main-thread dispatcher, version probing, and
small module-level start/stop helpers for ``init_unreal.py``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from dcc_mcp_core import DccServerBase
except ImportError:  # pragma: no cover - only useful for partial installs
    DccServerBase = object  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

_BUILTIN_SKILLS_DIR = Path(__file__).parent / "skills"
_DEFAULT_DCC_NAME = "unreal"
_DEFAULT_SERVER_NAME = "unreal-mcp"
_DEFAULT_SERVER_VERSION = "0.1.0"


class UnrealMainThreadDispatcher:
    """Dispatch in-process skill calls onto Unreal's editor tick when needed.

    The MCP HTTP server handles requests off the editor thread.  Unreal's
    Python editor APIs are safest on the main/UI thread, so scene-touching
    tools declare ``affinity: main`` in ``tools.yaml`` and flow through this
    dispatcher via ``HostExecutionBridge``.
    """

    def __init__(self, timeout_secs: float = 60.0, main_thread_id: Optional[int] = None) -> None:
        self.timeout_secs = timeout_secs
        self.main_thread_id = main_thread_id if main_thread_id is not None else threading.get_ident()

    def dispatch_callable(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run ``func`` inline or on the next Unreal Slate tick."""
        affinity = str(kwargs.pop("affinity", "main") or "main").lower()
        timeout_hint_secs = kwargs.pop("timeout_hint_secs", None)

        # Metadata supplied by HostExecutionBridge; not arguments for func.
        kwargs.pop("context", None)
        kwargs.pop("action_name", None)
        kwargs.pop("skill_name", None)
        kwargs.pop("execution", None)

        if affinity != "main" or threading.get_ident() == self.main_thread_id:
            return func(*args, **kwargs)

        try:
            import unreal  # noqa: PLC0415
        except ImportError:
            # Standalone tests and non-UE interpreters intentionally fall back
            # to inline execution; the script itself will return the UE import
            # error in the normal skill result envelope.
            return func(*args, **kwargs)

        register_tick = getattr(unreal, "register_slate_post_tick_callback", None)
        unregister_tick = getattr(unreal, "unregister_slate_post_tick_callback", None)
        if not callable(register_tick) or not callable(unregister_tick):
            return func(*args, **kwargs)

        event = threading.Event()
        result_box: Dict[str, Any] = {}
        handle_box: Dict[str, Any] = {}

        def _on_tick(_delta: float) -> None:
            handle = handle_box.get("handle")
            if handle is not None:
                try:
                    unregister_tick(handle)
                except Exception:
                    logger.debug("Failed to unregister Unreal tick callback", exc_info=True)
            try:
                result_box["value"] = func(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised on caller thread
                result_box["error"] = exc
            finally:
                event.set()

        handle_box["handle"] = register_tick(_on_tick)

        timeout = float(timeout_hint_secs or self.timeout_secs)
        if not event.wait(timeout):
            handle = handle_box.get("handle")
            if handle is not None:
                try:
                    unregister_tick(handle)
                except Exception:
                    logger.debug("Failed to unregister timed-out Unreal tick callback", exc_info=True)
            raise TimeoutError("Unreal main-thread dispatch timed out after {:.1f}s".format(timeout))

        if "error" in result_box:
            raise result_box["error"]
        return result_box.get("value")


def _make_execution_bridge(timeout_secs: float) -> Any:
    from dcc_mcp_core import HostExecutionBridge  # noqa: PLC0415

    dispatcher = UnrealMainThreadDispatcher(timeout_secs=timeout_secs)
    return HostExecutionBridge(
        dispatcher=dispatcher,
        default_thread_affinity="main",
        default_execution="sync",
        default_timeout_hint_secs=int(timeout_secs),
    )


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
    ) -> None:
        if DccServerBase is object:  # pragma: no cover - defensive install error
            raise ImportError("dcc-mcp-core is required to create UnrealMcpServer")

        from dcc_mcp_core import DccServerOptions  # noqa: PLC0415

        bridge = _make_execution_bridge(execution_timeout_secs)
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
        )
        super().__init__(options=options)

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
) -> Any:
    """Start, or return, the module-level Unreal MCP server handle."""
    global _server_instance
    with _lock:
        if _server_instance is None or not _server_instance.is_running:
            _server_instance = UnrealMcpServer(
                port=port,
                server_name=server_name,
                server_version=server_version,
                gateway_port=gateway_port,
                registry_dir=registry_dir,
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

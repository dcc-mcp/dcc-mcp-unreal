"""Unreal Editor host adapter for dcc-mcp-core main-thread dispatch.

Wires the dcc-mcp-core dispatcher to Unreal Editor's idle/tick system.
Unreal Editor provides several idle hook points:
- ``unreal.register_slate_pre_tick_callback`` — fires before Slate ticks
- ``unreal.register_slate_post_tick_callback`` — fires after Slate ticks
- ``FTicker`` — delegate-based tick system (C++ side)

This adapter uses Slate tick callbacks when available (UE5), falling back to
the base ``HostAdapter`` headless loop for UE 4.18 compatibility.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from dcc_mcp_core.host import HostAdapter, QueueDispatcher

TickFn = Callable[[], Optional[float]]


class UnrealHost(HostAdapter):
    """Drive a dcc-mcp-core dispatcher from Unreal Editor's main thread.

    In interactive mode (editor GUI), this adapter registers a tick callback
    with Unreal's Slate tick system. In background/headless mode
    (``-unattended``, commandlet), it uses the base class blocking loop.

    Usage (inside Unreal Editor Python console or startup script)::

        from dcc_mcp_core.host import QueueDispatcher
        from dcc_mcp_unreal.host import UnrealHost

        dispatcher = QueueDispatcher()
        host = UnrealHost(dispatcher)
        host.start()
    """

    def __init__(self, dispatcher: QueueDispatcher, **kwargs) -> None:
        super().__init__(dispatcher, name=kwargs.pop("name", "unreal-host"), **kwargs)
        self._tick_handle: Any = None
        self._owner_thread_ident = threading.get_ident()

    # ── Hook 1: tell the base class whether we have a UI loop ─────────────

    def is_background(self) -> bool:
        """Return ``True`` when Unreal Editor is running headless (unattended).

        Detection strategy:
        1. Check ``unreal.SlateApplication.is_initialized()`` — if Slate is not
           running, we are in headless mode.
        2. Check for command-line flags: ``-unattended``, ``-nullrhi``,
           ``-noslate``.
        3. If ``unreal`` module is not importable, assume background.
        """
        try:
            import unreal  # noqa: PLC0415

            if not unreal.SlateApplication.is_initialized():
                return True
            # Check command-line for headless flags
            try:
                cmd_line = unreal.SystemLibrary.get_command_line()
                headless_flags = ("-unattended", "-nullrhi", "-noslate", "-server")
                if any(flag in cmd_line for flag in headless_flags):
                    return True
            except Exception:
                pass
            return False
        except ImportError:
            return True

    # ── Hook 2: wire the DCC's idle primitive ────────────────────────────

    def attach_tick(self, tick_fn: TickFn) -> None:
        """Register ``tick_fn`` with Unreal's Slate tick system.

        Uses ``unreal.register_slate_pre_tick_callback`` which fires on every
        frame before Slate processes input. The callback must return ``None``
        to keep registered.

        Fallback for UE 4.18: uses ``unreal.register_python_tick_callback`` if
        Slate callbacks are unavailable.
        """
        try:
            import unreal  # noqa: PLC0415

            # Prefer Slate pre-tick (available in UE 4.26+, robust in UE5)
            if hasattr(unreal, "register_slate_pre_tick_callback"):
                self._tick_handle = unreal.register_slate_pre_tick_callback(lambda delta_time: tick_fn())
                return

            # Fallback: Python tick callback (available since UE 4.20 Python Plugin)
            if hasattr(unreal, "register_python_tick_callback"):
                self._tick_handle = unreal.register_python_tick_callback(tick_fn)
                return

            # Last resort: base class headless thread
            raise NotImplementedError("No Slate tick callback available; use run_headless() instead.")
        except ImportError:
            raise NotImplementedError("Unreal module not available; use run_headless() instead.")

    # ── Hook 3: undo attach_tick (must be idempotent) ───────────────────

    def detach_tick(self) -> None:
        """Unregister the Unreal Slate tick callback."""
        handle = self._tick_handle
        if handle is None:
            return

        try:
            import unreal  # noqa: PLC0415

            if hasattr(unreal, "unregister_slate_pre_tick_callback"):
                unreal.unregister_slate_pre_tick_callback(handle)
        except Exception:
            pass
        finally:
            self._tick_handle = None

    @property
    def tick_thread_ident(self) -> Optional[int]:
        """Thread id of the Unreal Editor main thread (set at construction)."""
        return self._owner_thread_ident


__all__ = ["UnrealHost"]

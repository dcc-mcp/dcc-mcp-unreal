"""Bridge client for dcc-mcp-unreal C++ plugin communication.

When the C++ plugin is loaded inside Unreal Editor, this client communicates
with it via the dcc-mcp-core bridge protocol (WebSocket or HTTP).

When ``unreal`` module is importable directly, the bridge uses UE Python API
as the primary transport and the C++ bridge as fallback for operations the
Python API cannot express (e.g. bulk class scanning).
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class DccMcpBridge:
    """Client for communicating with the dcc-mcp-unreal C++ bridge.

    The bridge supports two modes:
    1. **Direct mode** — ``unreal`` Python module is available; calls use
       UE Python API directly for most operations.
    2. **Bridge mode** — ``unreal`` module is not available; calls are routed
       through the C++ plugin's HTTP/WS endpoint.

    Parameters:
        bridge_url: URL of the C++ plugin's bridge endpoint (e.g. ``"http://127.0.0.1:19876"``).
        timeout: Request timeout in seconds.
    """

    def __init__(self, bridge_url: Optional[str] = None, timeout: float = 30.0) -> None:
        self._bridge_url = self._normalize_bridge_url(bridge_url or "http://127.0.0.1:19876")
        self._timeout = timeout
        self._session: Any = None
        self._lock = threading.Lock()
        self._use_direct: Optional[bool] = None  # Lazily determined

    @property
    def use_direct(self) -> bool:
        """Return ``True`` if ``unreal`` module is available for direct calls."""
        if self._use_direct is None:
            try:
                import unreal  # noqa: F401, PLC0415

                self._use_direct = hasattr(unreal, "load_object") and hasattr(unreal, "log")
            except ImportError:
                self._use_direct = False
        return self._use_direct

    def call(self, method: str, **params: Any) -> Any:
        """Call a bridge method with JSON-serializable parameters.

        Args:
            method: Bridge method name (e.g. ``"discover_objects"``).
            **params: Keyword arguments for the method.

        Returns:
            The deserialized response from the bridge.

        Raises:
            RuntimeError: If the bridge call fails.
        """
        payload = {"method": method, "params": params}
        if self.use_direct:
            return self._call_direct(method, params)
        return self._call_http(payload)

    # ── Private ────────────────────────────────────────────────────────────

    def _call_direct(self, method: str, params: Dict[str, Any]) -> Any:
        """Route through the `unreal` module directly."""
        import unreal  # noqa: PLC0415
        from dcc_mcp_unreal.reflection import _call_unreal_direct  # noqa: PLC0415

        return _call_unreal_direct(unreal, method, params)

    def _call_http(self, payload: Dict[str, Any]) -> Any:
        """Send an HTTP POST to the C++ bridge endpoint."""
        import urllib.request  # noqa: PLC0415

        method = str(payload.get("method", "<unknown>"))
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._bridge_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                collection_fields = {
                    "discover_objects": "objects",
                    "get_properties": "properties",
                    "set_properties": "properties",
                }
                collection_field = collection_fields.get(method)
                if collection_field and isinstance(result, dict):
                    if collection_field in result:
                        return result[collection_field]
                    error = result.get("error", "missing collection field")
                    raise RuntimeError(f"Bridge call failed: {method} — {error}")
                return result
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Bridge call failed: {method} — {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Bridge response parse error: {exc}") from exc

    @staticmethod
    def _normalize_bridge_url(bridge_url: str) -> str:
        """Add the native plugin endpoint when only an origin is provided."""
        parsed = urllib.parse.urlsplit(bridge_url)
        if parsed.path in ("", "/"):
            return urllib.parse.urlunsplit(parsed._replace(path="/bridge"))
        return bridge_url


# ── Module-level singleton ───────────────────────────────────────────────────

_bridge_instance: Optional[DccMcpBridge] = None


def get_bridge(url: Optional[str] = None) -> DccMcpBridge:
    """Get or create the singleton bridge client."""
    global _bridge_instance  # noqa: PLW0603
    if _bridge_instance is None:
        _bridge_instance = DccMcpBridge(bridge_url=url)
    return _bridge_instance


__all__ = ["DccMcpBridge", "get_bridge"]

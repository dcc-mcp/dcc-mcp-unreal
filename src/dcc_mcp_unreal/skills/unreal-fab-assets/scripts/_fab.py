"""Small, token-safe bridge to Unreal's official Fab plugin."""

from __future__ import annotations

import json
import uuid

FAB_BASE_URL = "https://fab.com/plugins/ue5"


def fab_library():
    import unreal

    library = getattr(unreal, "DccMcpAutomationLibrary", None)
    required = ("get_fab_session_status_json", "request_fab_login", "open_fab_listing")
    if library is None or any(not hasattr(library, name) for name in required):
        raise RuntimeError("The DCC MCP native Fab bridge is not available in this Unreal Editor")
    return library


def inspect_session(library) -> dict:
    """Return Fab state without exposing access or refresh tokens."""
    status = json.loads(library.get_fab_session_status_json())
    return {
        "plugin_available": bool(status.get("plugin_available")),
        "authenticated": bool(status.get("authenticated")),
        "engine_version": str(status.get("engine_version", "")),
        "plugin_version": str(status.get("plugin_version", "")),
    }


def listing_url(listing_id: str) -> str:
    normalized = str(uuid.UUID(str(listing_id).strip()))
    return f"{FAB_BASE_URL}/listings/{normalized}"


def open_listing(library, listing_id: str) -> str:
    url = listing_url(listing_id)
    if not library.open_fab_listing(url):
        raise RuntimeError("The native Fab bridge could not open the approved listing")
    return url


def request_login(library) -> None:
    if not library.request_fab_login():
        raise RuntimeError("The native Fab bridge could not open Epic's login flow")

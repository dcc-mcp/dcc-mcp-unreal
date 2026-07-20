"""Open one Fab listing in Unreal's official authenticated browser."""

from __future__ import annotations

from _fab import fab_library, inspect_session, open_listing
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def open_fab_listing(listing_id: str = "", **kwargs) -> dict:
    try:
        library = fab_library()
        status = inspect_session(library)
        if not status["plugin_available"]:
            return skill_error("Fab is unavailable", "Enable Epic's official Fab plugin and restart Unreal Editor")
        if not listing_id.strip():
            return skill_error("Missing required parameter: 'listing_id'", "listing_id must be a Fab listing UUID")
        url = open_listing(library, listing_id)
        return skill_success(
            "Opened the Fab listing in Unreal Editor.",
            prompt=(
                "Acquire or add the listing to the project. Fab will reuse persistent Epic auth when available; "
                "otherwise complete the official login prompt yourself."
            ),
            listing_id=listing_id,
            listing_url=url,
            authenticated=status["authenticated"],
            next_tool="app_ui__snapshot",
            required_ui_action="Acquire the free listing or add the owned listing to this project.",
        )
    except ValueError as exc:
        return skill_error("Invalid Fab listing id", str(exc), listing_id=listing_id)
    except Exception as exc:
        return skill_exception(exc, message="Failed to open the Fab listing")

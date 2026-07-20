"""Open Fab's official interactive Epic account portal."""

from __future__ import annotations

from _fab import fab_library, request_login
from dcc_mcp_core.skill import skill_entry, skill_exception, skill_success


@skill_entry
def request_fab_login(**kwargs) -> dict:
    try:
        request_login(fab_library())
        return skill_success(
            "Opened the official Fab login flow.",
            prompt="Complete Epic sign-in in the account portal; never send credentials to the agent.",
            requires_user_action=True,
            next_tool="unreal_fab_assets__inspect_fab_session",
        )
    except Exception as exc:
        return skill_exception(exc, message="Failed to open the official Fab login flow")

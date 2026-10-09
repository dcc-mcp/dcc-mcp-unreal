"""Read the last native Editor close state without inferring process exit."""

from _editor_close import _native
from dcc_mcp_core.skill import skill_entry


@skill_entry
def get_editor_close_status(**kwargs) -> dict:
    return _native("get_editor_close_status_json")

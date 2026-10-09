"""Inspect the native owned-test Editor close policy."""

from _editor_close import _native
from dcc_mcp_core.skill import skill_entry


@skill_entry
def inspect_editor_close(**kwargs) -> dict:
    return _native("inspect_editor_close_json")

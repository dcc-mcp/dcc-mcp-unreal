"""Request bounded normal Editor close using a launch-owned expiring proof."""

from _editor_close import request_editor_close as _request
from dcc_mcp_core.skill import skill_entry


@skill_entry
def request_editor_close(**kwargs) -> dict:
    return _request(**kwargs)

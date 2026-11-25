"""Read the status of a Hyper3D Rodin generation task."""

from __future__ import annotations

from _hyper3d_client import Hyper3DClientError, generation_status
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def get_hyper3d_generation_status(subscription_key: str = "", **kwargs) -> dict:
    try:
        result = generation_status(subscription_key)
    except Hyper3DClientError as exc:
        return skill_error("Hyper3D status check failed", exc.code)
    except Exception as exc:
        return skill_error("Hyper3D status check failed", type(exc).__name__)
    return skill_success(
        "Hyper3D generation status retrieved.",
        prompt="Run download_hyper3d_result after all_done becomes true.",
        **result,
    )

"""Download a completed Hyper3D result without exposing signed URLs."""

from __future__ import annotations

from _hyper3d_client import Hyper3DClientError, download_result
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def download_hyper3d_result(task_uuid: str = "", result_path: str = "", file_name: str = "", **kwargs) -> dict:
    try:
        result = download_result(task_uuid, result_path, file_name)
    except Hyper3DClientError as exc:
        return skill_error("Hyper3D result download failed", exc.code)
    except Exception as exc:
        return skill_error("Hyper3D result download failed", type(exc).__name__)
    return skill_success(
        "Hyper3D result downloaded.",
        prompt="Import the downloaded model with import_hyper3d_asset inside Unreal.",
        **result,
    )

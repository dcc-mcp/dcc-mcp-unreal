"""Submit a Hyper3D Rodin generation task."""

from __future__ import annotations

from typing import Iterable, Optional

from _hyper3d_client import Hyper3DClientError, submit_generation
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def submit_hyper3d_generation(
    image_paths: Optional[Iterable[str]] = None,
    prompt: str = "",
    tier: str = "Gen-2.5-Medium",
    mesh_mode: str = "Raw",
    quality: str = "medium",
    texture_mode: str = "",
    geometry_file_format: str = "glb",
    material: str = "PBR",
    **kwargs,
) -> dict:
    try:
        result = submit_generation(
            image_paths=image_paths or (),
            prompt=prompt,
            tier=tier,
            mesh_mode=mesh_mode,
            quality=quality,
            texture_mode=texture_mode,
            geometry_file_format=geometry_file_format,
            material=material,
        )
    except Hyper3DClientError as exc:
        return skill_error(
            "Hyper3D generation submission failed",
            exc.code,
            possible_solutions=[
                "Set HYPER3D_API_KEY or RODIN_API_KEY in the Unreal process environment.",
                "Provide one to five existing absolute image paths or a non-empty prompt.",
                "Use a tier and output option supported by the Rodin API.",
            ],
        )
    except Exception as exc:
        return skill_error("Hyper3D generation submission failed", type(exc).__name__)
    return skill_success(
        "Hyper3D generation task submitted.",
        prompt="Poll get_hyper3d_generation_status with the returned subscription_key.",
        **result,
    )

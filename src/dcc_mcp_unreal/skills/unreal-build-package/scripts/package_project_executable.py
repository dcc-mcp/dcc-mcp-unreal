"""Compile, cook, stage, and archive an Unreal project for Windows."""

from __future__ import annotations

from _build_package import package_project_executable_impl
from dcc_mcp_core.skill import skill_entry


@skill_entry
def package_project_executable(
    project_path: str,
    output_directory: str,
    ue_root: str = "",
    configuration: str = "Shipping",
    target_platform: str = "Win64",
    **kwargs,
) -> dict:
    return package_project_executable_impl(
        project_path=project_path,
        output_directory=output_directory,
        ue_root=ue_root,
        configuration=configuration,
        target_platform=target_platform,
    )

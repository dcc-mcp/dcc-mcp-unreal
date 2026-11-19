"""Validate native PCG Pathfinding configuration without editing project assets."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def preflight_pcg_pathfinding(point_cloud: list, start: dict, goal: dict, settings: dict, **kwargs) -> dict:
    """Check descriptors and transient settings; do not execute a path search."""
    from dcc_mcp_unreal.pcg_pathfinding import (  # noqa: PLC0415
        PathfindingHostError,
        PathfindingValidationError,
        preflight_pathfinding,
        validate_pathfinding_request,
    )

    try:
        if kwargs:
            raise PathfindingValidationError("Unknown top-level arguments")
        validate_pathfinding_request(point_cloud, start, goal, settings)
    except PathfindingValidationError as exc:
        return skill_error(
            "Invalid PCG Pathfinding input", str(exc), error_kind="invalid_input", execution_verified=False
        )
    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return skill_error(
            "Unreal Python API is unavailable; no native preflight was performed",
            "A running Unreal Python host is required",
            error_kind="host_unavailable",
            execution_verified=False,
        )
    try:
        result = preflight_pathfinding(unreal, point_cloud, start, goal, settings)
    except PathfindingHostError as exc:
        return skill_error(
            "Native PCG Pathfinding preflight failed",
            str(exc),
            error_kind="native_preflight_failed",
            execution_verified=False,
            persistent_assets_modified=False,
            generation_started=False,
        )
    return skill_success(
        "Transient PCG Pathfinding configuration verified; no path search was executed.",
        **result,
    )

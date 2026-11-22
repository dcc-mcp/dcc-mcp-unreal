"""Validate a procedural workflow request without touching Unreal objects."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def validate_procedural_workflow(feature: str, operation: str, request: dict, **kwargs) -> dict:
    from dcc_mcp_unreal.procedural_workflows import ProceduralWorkflowError, validate_request  # noqa: PLC0415

    if kwargs:
        return skill_error("Invalid procedural workflow request", "Unknown arguments", error_kind="invalid_input")
    try:
        result = validate_request(feature, operation, request)
    except ProceduralWorkflowError as exc:
        return skill_error("Invalid procedural workflow request", str(exc), error_kind="invalid_input")
    return skill_success("Validated a procedural workflow plan without mutation.", **result)


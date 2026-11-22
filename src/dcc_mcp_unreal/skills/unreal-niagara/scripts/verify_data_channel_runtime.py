"""Validate native runtime observations for a Niagara Data Channel."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def verify_niagara_data_channel_runtime(
    channel_path: str, routing: str, visibility: list[str], evidence: dict, **kwargs
) -> dict:
    from dcc_mcp_unreal.niagara_runtime import NiagaraRuntimeEvidenceError, validate_runtime_evidence  # noqa: PLC0415

    if kwargs:
        return skill_error("Invalid Niagara runtime evidence", "Unknown arguments", error_kind="invalid_input")
    try:
        result = validate_runtime_evidence(channel_path, routing, visibility, evidence)
    except NiagaraRuntimeEvidenceError as exc:
        return skill_error("Invalid Niagara runtime evidence", str(exc), error_kind="invalid_input")
    if result["status"] != "qualified":
        return skill_error(
            "Niagara Data Channel runtime remains unqualified",
            "The supplied observations do not prove all requested runtime paths and teardown behavior.",
            error_kind="runtime_unverified",
            **result,
        )
    return skill_success("Verified Niagara Data Channel runtime evidence.", **result)


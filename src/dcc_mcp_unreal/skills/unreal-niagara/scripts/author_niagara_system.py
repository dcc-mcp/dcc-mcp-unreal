"""Author a Niagara system through the UE 5.8 external editor API bridge."""

from __future__ import annotations

import json

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


@skill_entry
def author_niagara_system(
    system_name: str,
    emitters: list[dict],
    package_path: str = "/Game/VFX",
    **kwargs,
) -> dict:
    """Create and finalize a semantically-authored Niagara system.

    The native bridge uses UE 5.8's public ``UNiagaraExternalEditUtilities``
    surface. It deliberately refuses commandlets and other hosts without a
    fully initialized Slate editor before creating an asset.
    """
    package_path = package_path.rstrip("/")
    if not system_name or not (package_path == "/Game" or package_path.startswith("/Game/")):
        return unreal_error(
            "Invalid Niagara authoring parameters",
            "system_name must be non-empty and package_path must be /Game or start with /Game/",
        )
    if not isinstance(emitters, list) or not emitters:
        return unreal_error(
            "Invalid Niagara emitter specification",
            "emitters must be a non-empty array",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    author = getattr(bridge, "author_niagara_system_json", None)
    if not callable(author):
        return unreal_error(
            "Niagara semantic authoring is unavailable",
            "The installed DccMcpUnreal native plugin does not expose author_niagara_system_json.",
            error_code="niagara_bridge_unavailable",
            possible_solutions=["Install a DccMcpUnreal build with UE 5.8 Niagara authoring support."],
        )

    specification = {
        "asset_name": system_name,
        "asset_path": package_path,
        "emitters": emitters,
    }
    try:
        native_result = json.loads(author(json.dumps(specification, separators=(",", ":"))))
    except Exception as exc:
        return unreal_from_exception(
            exc,
            "Failed to invoke Niagara semantic authoring",
            system_name=system_name,
            package_path=package_path,
        )

    if not isinstance(native_result, dict):
        return unreal_error(
            "Invalid Niagara authoring response",
            "The native bridge returned a non-object JSON value.",
            error_code="invalid_native_response",
        )

    context = {key: value for key, value in native_result.items() if key not in {"success", "message"}}
    if not native_result.get("success"):
        return unreal_error(
            "Niagara semantic authoring failed",
            str(native_result.get("message") or "The native bridge rejected the request."),
            **context,
        )

    return unreal_success(
        str(native_result.get("message") or f"Authored Niagara system '{package_path}/{system_name}'"),
        prompt="Inspect or spawn the finalized system with the other unreal-niagara tools.",
        **context,
    )

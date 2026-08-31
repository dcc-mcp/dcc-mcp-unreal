"""Apply typed Material Instance parameter values."""

from __future__ import annotations

import json
from typing import Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def set_material_instance_parameters(
    instance_path: str = "",
    scalar_parameters: Optional[dict] = None,
    vector_parameters: Optional[dict] = None,
    texture_parameters: Optional[dict] = None,
    **kwargs,
) -> dict:
    """Set scalar, vector, and texture parameters without raw editor scripting."""
    import unreal  # noqa: PLC0415

    instance = unreal.EditorAssetLibrary.load_asset(instance_path)
    if instance is None or not isinstance(instance, unreal.MaterialInstanceConstant):
        return skill_error("Material Instance not found", f"'{instance_path}' is not a MaterialInstanceConstant")
    scalar_parameters = scalar_parameters or {}
    vector_parameters = vector_parameters or {}
    texture_parameters = texture_parameters or {}

    normalized_scalars = {}
    for name, value in scalar_parameters.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return skill_error("Invalid scalar parameter", f"'{name}' must be a number")
        normalized_scalars[name] = float(value)
    normalized_vectors = {}
    for name, value in vector_parameters.items():
        if (
            not isinstance(value, (list, tuple))
            or len(value) not in (3, 4)
            or any(not isinstance(component, (int, float)) or isinstance(component, bool) for component in value)
        ):
            return skill_error("Invalid vector parameter", f"'{name}' must contain three or four numbers")
        rgba = [float(component) for component in value]
        if len(rgba) == 3:
            rgba.append(1.0)
        normalized_vectors[name] = unreal.LinearColor(*rgba)
    texture_assets = {}
    for name, texture_path in texture_parameters.items():
        texture = unreal.EditorAssetLibrary.load_asset(texture_path)
        if texture is None or not isinstance(texture, unreal.Texture):
            return skill_error("Texture parameter asset not found", f"'{texture_path}' is not a Texture")
        texture_assets[name] = texture

    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    configure = getattr(bridge, "configure_material_instance_parameters", None)
    if not callable(configure):
        return skill_error(
            "Native Material Instance bridge unavailable",
            "Install a DCC-MCP Unreal plugin that exposes configure_material_instance_parameters",
        )
    try:
        native_result = json.loads(configure(instance, normalized_scalars, normalized_vectors, texture_assets))
    except (TypeError, ValueError) as exc:
        return skill_error("Native Material Instance bridge failed", f"invalid result: {exc}")
    if not isinstance(native_result, dict) or not native_result.get("success"):
        return skill_error(
            "Native Material Instance bridge failed",
            str((native_result or {}).get("message") or "native operation failed"),
            native_result=native_result,
        )
    if not native_result.get("saved") or not native_result.get("verified") or native_result.get("package_dirty"):
        return skill_error(
            "Native Material Instance verification failed",
            "The native bridge did not verify a clean saved package",
            native_result=native_result,
        )
    return skill_success(
        f"Updated Material Instance '{instance_path}'",
        instance_path=instance_path,
        scalar_parameters=scalar_parameters,
        vector_parameters=vector_parameters,
        texture_parameters=texture_parameters,
        changed=bool(native_result.get("changed")),
        native_verified=True,
        native_result=native_result,
    )

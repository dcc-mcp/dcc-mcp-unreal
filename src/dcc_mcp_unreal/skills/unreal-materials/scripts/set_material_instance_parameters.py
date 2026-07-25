"""Apply typed Material Instance parameter values."""

from __future__ import annotations

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

    for name, value in scalar_parameters.items():
        if not isinstance(value, (int, float)):
            return skill_error("Invalid scalar parameter", f"'{name}' must be a number")
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(instance, name, float(value))
    for name, value in vector_parameters.items():
        if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
            return skill_error("Invalid vector parameter", f"'{name}' must contain three or four numbers")
        rgba = [float(component) for component in value]
        if len(rgba) == 3:
            rgba.append(1.0)
        unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(
            instance, name, unreal.LinearColor(*rgba)
        )
    for name, texture_path in texture_parameters.items():
        texture = unreal.EditorAssetLibrary.load_asset(texture_path)
        if texture is None or not isinstance(texture, unreal.Texture):
            return skill_error("Texture parameter asset not found", f"'{texture_path}' is not a Texture")
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(instance, name, texture)

    if not unreal.EditorAssetLibrary.save_loaded_asset(instance, only_if_is_dirty=False):
        return skill_error("Failed to save Material Instance", instance_path)
    return skill_success(
        f"Updated Material Instance '{instance_path}'",
        instance_path=instance_path,
        scalar_parameters=scalar_parameters,
        vector_parameters=vector_parameters,
        texture_parameters=texture_parameters,
    )

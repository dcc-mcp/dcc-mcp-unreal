"""Create a new Material asset in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_VALID_BLEND_MODES = frozenset({"Opaque", "Masked", "Translucent", "Additive", "Modulate"})
_VALID_SHADING_MODELS = frozenset({
    "DefaultLit", "Unlit", "Subsurface", "PreintegratedSkin",
    "ClearCoat", "SubsurfaceProfile", "TwoSidedFoliage", "Hair", "Cloth", "Eye",
})


def _resolve_blend_mode(unreal, mode: str):
    """Map a string blend mode to its unreal.BlendMode enum value."""
    mapping = {
        "Opaque": unreal.BlendMode.BLEND_OPAQUE if hasattr(unreal.BlendMode, "BLEND_OPAQUE") else 0,
        "Masked": unreal.BlendMode.BLEND_MASKED if hasattr(unreal.BlendMode, "BLEND_MASKED") else 1,
        "Translucent": unreal.BlendMode.BLEND_TRANSLUCENT if hasattr(unreal.BlendMode, "BLEND_TRANSLUCENT") else 2,
        "Additive": unreal.BlendMode.BLEND_ADDITIVE if hasattr(unreal.BlendMode, "BLEND_ADDITIVE") else 3,
        "Modulate": unreal.BlendMode.BLEND_MODULATE if hasattr(unreal.BlendMode, "BLEND_MODULATE") else 4,
    }
    return mapping.get(mode, 0)


def _resolve_shading_model(unreal, model_name: str):
    """Map a string shading model to its unreal.EMaterialShadingModel enum value."""
    mapping = {
        "DefaultLit": 0,
        "Unlit": 1,
        "Subsurface": 2,
        "PreintegratedSkin": 3,
        "ClearCoat": 4,
        "SubsurfaceProfile": 5,
        "TwoSidedFoliage": 6,
        "Hair": 7,
        "Cloth": 8,
        "Eye": 9,
    }
    return mapping.get(model_name, 0)


@skill_entry
def create_material_graph(
    material_name: str,
    package_path: str = "/Game/Materials",
    blend_mode: str = "Opaque",
    shading_model: str = "DefaultLit",
    two_sided: bool = False,
    **kwargs,
) -> dict:
    """Create a new Material asset with the specified properties.

    Args:
        material_name: Name for the new Material (e.g. "M_MyMaterial").
        package_path: Content Browser path for the asset (must start with /Game).
        blend_mode: One of Opaque, Masked, Translucent, Additive, Modulate.
        shading_model: One of DefaultLit, Unlit, Subsurface, etc.
        two_sided: Whether the material renders both sides.

    Returns:
        ActionResultModel with created Material info.
    """
    import unreal  # noqa: PLC0415

    if not material_name or not package_path.startswith("/Game"):
        return skill_error(
            "Invalid Material settings",
            "material_name is required; package_path must start with /Game",
        )

    blend_mode = blend_mode or "Opaque"
    shading_model = shading_model or "DefaultLit"

    if blend_mode not in _VALID_BLEND_MODES:
        return skill_error(
            f"Invalid blend mode: {blend_mode}",
            f"Must be one of: {', '.join(sorted(_VALID_BLEND_MODES))}",
        )
    if shading_model not in _VALID_SHADING_MODELS:
        return skill_error(
            f"Invalid shading model: {shading_model}",
            f"Must be one of: {', '.join(sorted(_VALID_SHADING_MODELS))}",
        )

    package_path = package_path.rstrip("/")
    full_path = f"{package_path}/{material_name}"

    # Check for existing asset
    existing = unreal.EditorAssetLibrary.does_asset_exist(full_path)
    if existing:
        return skill_error(
            f"Material already exists: {full_path}",
            "Delete the existing asset or choose a different name.",
        )

    # Ensure package directory
    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)

    # Create the Material
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew()
    material = asset_tools.create_asset(
        asset_name=material_name,
        package_path=package_path,
        asset_class=unreal.Material,
        factory=factory,
    )

    if material is None:
        return skill_error(
            f"Failed to create Material '{material_name}'",
            "Asset creation returned None",
            prompt="Check that the name is unique and the path is writable.",
        )

    # Configure material properties
    material.set_editor_property("blend_mode", _resolve_blend_mode(unreal, blend_mode))
    material.set_editor_property("shading_model", _resolve_shading_model(unreal, shading_model))
    if two_sided:
        material.set_editor_property("two_sided", True)

    # Save
    unreal.EditorAssetLibrary.save_asset(full_path)

    return skill_success(
        f"Created Material '{material_name}' at {full_path}",
        prompt="Add expressions with unreal_material_shaders__add_material_expression, then compile.",
        material_name=material_name,
        material_path=full_path,
        blend_mode=blend_mode,
        shading_model=shading_model,
        two_sided=two_sided,
    )

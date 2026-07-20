"""Create a tiled Unreal PBR material from Content Browser textures."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _material_object_path(destination_path: str, material_name: str) -> str:
    folder = destination_path.rstrip("/") or "/Game/GeneratedMaterials"
    return f"{folder}/{material_name}.{material_name}"


def _constant_expression(unreal, material, value: float, x: int, y: int):
    expression = unreal.MaterialEditingLibrary.create_material_expression(
        material,
        unreal.MaterialExpressionConstant,
        x,
        y,
    )
    expression.set_editor_property("r", value)
    return expression


def _build_material_graph(
    unreal,
    material,
    texture,
    *,
    normal_texture=None,
    roughness_texture=None,
    ambient_occlusion_texture=None,
    metallic_texture=None,
    uv_scale: float,
    base_color_scale: float,
    roughness: float,
    specular: float,
) -> None:
    unreal.MaterialEditingLibrary.delete_all_material_expressions(material)

    coordinates = unreal.MaterialEditingLibrary.create_material_expression(
        material,
        unreal.MaterialExpressionTextureCoordinate,
        -700,
        0,
    )
    coordinates.set_editor_property("u_tiling", uv_scale)
    coordinates.set_editor_property("v_tiling", uv_scale)

    sample = unreal.MaterialEditingLibrary.create_material_expression(
        material,
        unreal.MaterialExpressionTextureSample,
        -430,
        0,
    )
    sample.set_editor_property("texture", texture)
    unreal.MaterialEditingLibrary.connect_material_expressions(
        coordinates,
        "",
        sample,
        "UVs",
    )
    base_color_expression = sample
    base_color_output = "RGB"
    if base_color_scale != 1.0:
        base_color_expression = unreal.MaterialEditingLibrary.create_material_expression(
            material,
            unreal.MaterialExpressionMultiply,
            -180,
            0,
        )
        base_color_expression.set_editor_property("const_b", base_color_scale)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sample,
            "RGB",
            base_color_expression,
            "A",
        )
        base_color_output = ""
    unreal.MaterialEditingLibrary.connect_material_property(
        base_color_expression,
        base_color_output,
        unreal.MaterialProperty.MP_BASE_COLOR,
    )

    texture_properties = (
        (normal_texture, unreal.MaterialProperty.MP_NORMAL, "RGB", 120),
        (roughness_texture, unreal.MaterialProperty.MP_ROUGHNESS, "R", 240),
        (ambient_occlusion_texture, unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "R", 360),
        (metallic_texture, unreal.MaterialProperty.MP_METALLIC, "R", 480),
    )
    for pbr_texture, material_property, output_name, y in texture_properties:
        if pbr_texture is None:
            continue
        pbr_sample = unreal.MaterialEditingLibrary.create_material_expression(
            material,
            unreal.MaterialExpressionTextureSample,
            -430,
            y,
        )
        pbr_sample.set_editor_property("texture", pbr_texture)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            coordinates,
            "",
            pbr_sample,
            "UVs",
        )
        unreal.MaterialEditingLibrary.connect_material_property(
            pbr_sample,
            output_name,
            material_property,
        )

    if roughness_texture is None:
        roughness_expression = _constant_expression(unreal, material, roughness, -250, 240)
        unreal.MaterialEditingLibrary.connect_material_property(
            roughness_expression,
            "",
            unreal.MaterialProperty.MP_ROUGHNESS,
        )
    specular_expression = _constant_expression(unreal, material, specular, -250, 600)
    unreal.MaterialEditingLibrary.connect_material_property(
        specular_expression,
        "",
        unreal.MaterialProperty.MP_SPECULAR,
    )

    unreal.MaterialEditingLibrary.recompile_material(material)


@skill_entry
def create_texture_material(
    texture_path: str = "",
    normal_texture_path: str = "",
    roughness_texture_path: str = "",
    ambient_occlusion_texture_path: str = "",
    metallic_texture_path: str = "",
    destination_path: str = "/Game/GeneratedMaterials",
    material_name: str = "",
    uv_scale: float = 1.0,
    base_color_scale: float = 1.0,
    roughness: float = 0.85,
    specular: float = 0.15,
    replace_existing: bool = False,
    **kwargs,
) -> dict:
    """Create a tiled opaque PBR material from imported textures."""
    import unreal  # noqa: PLC0415

    if not texture_path:
        return skill_error(
            "Missing required parameter: 'texture_path'",
            "texture_path must identify an imported texture asset",
        )
    if not material_name:
        return skill_error(
            "Missing required parameter: 'material_name'",
            "material_name must be a valid Unreal asset name",
        )
    if uv_scale <= 0:
        return skill_error("uv_scale must be greater than zero", f"Received {uv_scale}")
    if not 0.01 <= base_color_scale <= 4.0:
        return skill_error(
            "base_color_scale must be between 0.01 and 4",
            f"Received {base_color_scale}",
        )
    if not 0 <= roughness <= 1 or not 0 <= specular <= 1:
        return skill_error(
            "roughness and specular must be between 0 and 1",
            f"Received roughness={roughness}, specular={specular}",
        )

    texture = unreal.EditorAssetLibrary.load_asset(texture_path)
    if texture is None or not isinstance(texture, unreal.Texture):
        return skill_error(
            f"Texture asset not found: {texture_path}",
            "EditorAssetLibrary could not load a Texture at the requested path",
            possible_solutions=["Import the source image with unreal_assets__import_asset first"],
        )

    optional_texture_paths = {
        "normal_texture": normal_texture_path,
        "roughness_texture": roughness_texture_path,
        "ambient_occlusion_texture": ambient_occlusion_texture_path,
        "metallic_texture": metallic_texture_path,
    }
    optional_textures = {}
    for name, path in optional_texture_paths.items():
        optional_textures[name] = unreal.EditorAssetLibrary.load_asset(path) if path else None
        if path and not isinstance(optional_textures[name], unreal.Texture):
            return skill_error(
                f"Texture asset not found: {path}",
                f"'{name}_path' must identify an imported Texture asset",
                possible_solutions=["Import the source image with unreal_assets__import_asset first"],
            )

    destination_path = destination_path.rstrip("/") or "/Game/GeneratedMaterials"
    object_path = _material_object_path(destination_path, material_name)
    material = unreal.EditorAssetLibrary.load_asset(object_path)
    if material is not None:
        if not isinstance(material, unreal.Material):
            return skill_error(
                f"Existing asset is not a Material: {object_path}",
                f"Loaded asset type: {type(material).__name__}",
            )
        if not replace_existing:
            return skill_error(
                f"Material already exists: {object_path}",
                "Set replace_existing=true to rebuild its expression graph",
            )
    else:
        unreal.EditorAssetLibrary.make_directory(destination_path)
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            material_name,
            destination_path,
            unreal.Material,
            unreal.MaterialFactoryNew(),
        )
        if material is None:
            return skill_error(
                f"Failed to create material: {object_path}",
                "AssetTools.create_asset returned None",
            )

    _build_material_graph(
        unreal,
        material,
        texture,
        **optional_textures,
        uv_scale=float(uv_scale),
        base_color_scale=float(base_color_scale),
        roughness=float(roughness),
        specular=float(specular),
    )
    if not unreal.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False):
        return skill_error(
            f"Failed to save material: {object_path}",
            "EditorAssetLibrary.save_loaded_asset returned False",
        )

    return skill_success(
        f"Created material '{material_name}' from '{texture_path}'",
        prompt=f"Use get_asset_info to inspect '{object_path}'.",
        object_path=object_path,
        texture_path=texture_path,
        normal_texture_path=normal_texture_path,
        roughness_texture_path=roughness_texture_path,
        ambient_occlusion_texture_path=ambient_occlusion_texture_path,
        metallic_texture_path=metallic_texture_path,
        uv_scale=float(uv_scale),
        base_color_scale=float(base_color_scale),
        roughness=float(roughness),
        specular=float(specular),
    )

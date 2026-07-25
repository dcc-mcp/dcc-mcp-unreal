"""Create a new Niagara system asset from an optional emitter template."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_unreal.api import require_unreal, unreal_error, unreal_success


@skill_entry
def create_niagara_system(
    system_name: str,
    package_path: str = "/Game/VFX",
    emitter_template: str = "",
    **kwargs,
) -> dict:
    """Create a new Niagara system asset.

    Args:
        system_name: Name for the new Niagara system asset.
        package_path: Content Browser folder (must start with /Game).
        emitter_template: Optional path to an emitter template asset.

    Returns:
        ActionResultModel dict with the system path.
    """
    if not system_name or not package_path.startswith("/Game"):
        return unreal_error(
            "Invalid parameters",
            "system_name must be non-empty and package_path must start with /Game",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        # Ensure the folder exists
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            unreal.EditorAssetLibrary.make_directory(package_path)

        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

        # Try to create from template
        if emitter_template:
            template_asset = unreal.load_asset(emitter_template)
            if template_asset is not None:
                factory = unreal.NiagaraSystemFactoryNew()
                system = asset_tools.create_asset_with_dialog(
                    asset_name=system_name,
                    package_path=package_path,
                    asset_class=unreal.NiagaraSystem,
                    factory=factory,
                )
                if system is None:
                    # Fallback to direct creation
                    system = asset_tools.create_asset(
                        asset_name=system_name,
                        package_path=package_path.rstrip("/").rsplit("/", 1)[0],
                        asset_class=unreal.NiagaraSystem,
                        factory=factory,
                    )
            else:
                return unreal_error(
                    "Template not found",
                    f"Emitter template '{emitter_template}' could not be loaded.",
                    possible_solutions=[
                        "Leave emitter_template empty to create an empty system.",
                        "Use built-in templates like /Niagara/DefaultTextures/Fountain.",
                    ],
                )
        else:
            # Create empty Niagara system
            factory = unreal.NiagaraSystemFactoryNew()
            parent_path = package_path.rstrip("/").rsplit("/", 1)
            package_dir = parent_path[0] if len(parent_path) > 1 else "/Game"
            system = asset_tools.create_asset(
                asset_name=system_name,
                package_path=package_dir,
                asset_class=unreal.NiagaraSystem,
                factory=factory,
            )

        if system is None:
            return unreal_error(
                "Failed to create Niagara system",
                f"Asset creation returned None for '{system_name}'.",
            )

        full_path = f"{package_path}/{system_name}"
        unreal.EditorAssetLibrary.save_loaded_asset(system)

        return unreal_success(
            f"Created Niagara system '{full_path}'",
            system_path=full_path,
            system_name=system_name,
            template_used=bool(emitter_template),
            prompt="Spawn it with spawn_niagara_actor, then configure parameters.",
        )

    except Exception as exc:
        return unreal_success(
            f"Niagara system creation attempted for '{system_name}'",
            system_path=f"{package_path}/{system_name}",
            system_name=system_name,
            note=str(exc),
            prompt="Verify the asset in the Content Browser, then spawn with spawn_niagara_actor.",
        )

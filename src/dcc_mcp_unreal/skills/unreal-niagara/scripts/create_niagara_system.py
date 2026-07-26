"""Create a new Niagara system asset from an optional emitter template."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


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
    package_path = package_path.rstrip("/")
    if not system_name or not (package_path == "/Game" or package_path.startswith("/Game/")):
        return unreal_error(
            "Invalid parameters",
            "system_name must be non-empty and package_path must be /Game or start with /Game/",
        )
    if emitter_template:
        return unreal_error(
            "Emitter templates are not supported",
            "NiagaraSystemFactoryNew creates an empty system and cannot attach an emitter template. "
            "Leave emitter_template empty until a verified Unreal editor API is available.",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    system = None
    full_path = f"{package_path}/{system_name}"
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(full_path):
            return unreal_error("Niagara system already exists", f"An asset already exists at '{full_path}'.")

        # Ensure the folder exists
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            unreal.EditorAssetLibrary.make_directory(package_path)
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            return unreal_error("Failed to create package path", f"Could not create '{package_path}'.")

        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

        factory = unreal.NiagaraSystemFactoryNew()
        system = asset_tools.create_asset(
            asset_name=system_name,
            package_path=package_path,
            asset_class=unreal.NiagaraSystem,
            factory=factory,
        )

        if system is None:
            return unreal_error(
                "Failed to create Niagara system",
                f"Asset creation returned None for '{system_name}'.",
            )

        if not unreal.EditorAssetLibrary.save_loaded_asset(system):
            unreal.EditorAssetLibrary.delete_asset(full_path)
            return unreal_error("Failed to save Niagara system", f"Unreal could not save '{full_path}'.")
        saved_system = unreal.load_asset(full_path)
        if saved_system is None or not isinstance(saved_system, unreal.NiagaraSystem):
            unreal.EditorAssetLibrary.delete_asset(full_path)
            return unreal_error(
                "Niagara system verification failed", f"Saved asset '{full_path}' is unavailable or has the wrong type."
            )

        return unreal_success(
            f"Created Niagara system '{full_path}'",
            system_path=full_path,
            system_name=system_name,
            template_used=False,
            prompt="Spawn it with spawn_niagara_actor, then configure parameters.",
        )

    except Exception as exc:
        if system is not None:
            try:
                unreal.EditorAssetLibrary.delete_asset(full_path)
            except Exception:
                pass
        return unreal_from_exception(
            exc,
            f"Failed to create Niagara system '{system_name}'",
            system_path=f"{package_path}/{system_name}",
            system_name=system_name,
            possible_solutions=[
                "Enable the Niagara plugin.",
                "Verify that the package path is writable in the Content Browser.",
            ],
        )

"""Add a component to a Blueprint's component hierarchy in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def add_component_to_blueprint(
    blueprint_name: str,
    component_type: str,
    component_name: str,
    **kwargs,
) -> dict:
    """Add a component to a Blueprint.

    Args:
        blueprint_name: Name of the target Blueprint.
        component_type: Type of component (e.g. "StaticMeshComponent").
        component_name: Name for the new component.

    Returns:
        dict: ActionResultModel with the added component info.
    """
    import unreal  # noqa: PLC0415

    # Load the Blueprint
    blueprint_path = f"/Game/Blueprints/{blueprint_name}"
    blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
    if blueprint is None:
        # Try loading without path prefix
        blueprint = unreal.load_object(None, f"{blueprint_path}.{blueprint_name}")

    if blueprint is None:
        return skill_error(
            f"Blueprint not found: {blueprint_name}",
            f"Could not load asset at '{blueprint_path}'",
            prompt="Create the Blueprint first with create_blueprint_class.",
            possible_solutions=[
                f"Run create_blueprint_class with blueprint_name='{blueprint_name}' first",
                "Check that the Blueprint exists in the Content Browser",
            ],
        )

    # Resolve component class
    component_class_path = f"/Script/Engine.{component_type}"
    component_cls = unreal.load_class(None, component_class_path)
    if component_cls is None:
        # Try alternate paths
        alt_paths = [
            f"/Script/Engine.{component_type}",
            f"/Script/UMG.{component_type}",
        ]
        for alt in alt_paths:
            component_cls = unreal.load_class(None, alt)
            if component_cls is not None:
                break

    if component_cls is None:
        return skill_error(
            f"Component type not found: {component_type}",
            f"unreal.load_class returned None for '{component_type}'",
            prompt="Check the component type name.",
            possible_solutions=[
                "Use full path: '/Script/Engine.StaticMeshComponent'",
                "Common types: StaticMeshComponent, BoxComponent, SphereComponent, CameraComponent",
            ],
        )

    # Add component via SimpleConstructionScript
    scs = unreal.BlueprintEditorLibrary.get_blueprint_simple_construction_script(blueprint)
    if scs is None:
        return skill_error(
            f"Could not access Blueprint construction script for '{blueprint_name}'",
            "SCS is None",
            prompt="Ensure the Blueprint is fully loaded and editable.",
        )

    # Add the component node
    component_node = scs.create_node(component_cls, component_name)
    if component_node is None:
        return skill_error(
            f"Failed to add component '{component_name}' to '{blueprint_name}'",
            "SCS create_node returned None",
            prompt="Check that the component name is unique in this Blueprint.",
        )

    # Add to root nodes
    all_nodes = scs.get_all_nodes()
    root_nodes = [n for n in all_nodes if n.get_parent() is None]
    scs.set_root_nodes(root_nodes)

    return skill_success(
        f"Added {component_type} '{component_name}' to '{blueprint_name}'",
        prompt=f"Compile the Blueprint to apply changes: compile_blueprint('{blueprint_name}')",
        blueprint_name=blueprint_name,
        component_name=component_name,
        component_type=component_type,
    )

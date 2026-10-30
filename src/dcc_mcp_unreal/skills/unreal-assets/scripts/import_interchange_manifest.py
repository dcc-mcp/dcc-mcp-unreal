"""Import a typed Houdini -> Unreal offline-baked interchange manifest.

This is the Unreal-side consumer of the sidecar manifest produced by the
Houdini pipeline (COPS/Copernicus textures and baked HDA geometry).  It reads
and validates the manifest with the pure-Python ``_interchange_manifest``
contract, then delegates the actual Content Browser work to the existing
``import_asset`` and ``create_texture_material`` tools.

Coordinate-system conversions (unit scale, up-axis) are baked by the producer
at export time; the manifest declares them so the consumer can validate and
surface them as readback for ``get_asset_info`` verification.  The consumer
never double-applies a scale.

``validate_only=true`` returns the normalized import plan without touching
Unreal, which lets producers / CI validate a manifest against the contract on
any Python 3.7+ interpreter.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Private aliases skip skill_runner's auto-main discovery; the explicit main()
# below short-circuits it entirely. The shared runner owns script-dir path setup.
from _interchange_manifest import (
    MANIFEST_VERSION,
    ManifestError,
    duplicate_wired_roles,
    load_manifest,
    material_texture_kwargs,
    validate_manifest,
)
from create_texture_material import create_texture_material as _create_material_tool
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success
from import_asset import import_asset as _import_asset_tool


def _planned_asset(record: Dict[str, Any]) -> Dict[str, Any]:
    """Public, serializable view of one planned asset (no import kwargs)."""
    view = {
        "source_path": record["source_path"],
        "asset_name": record["asset_name"],
        "destination_path": record["destination_path"],
        "kind": record["kind"],
        "status": "planned",
        "object_path": "",
    }
    if record.get("kind") == "texture":
        view["map_type"] = record.get("map_type_canonical") or record.get("map_type")
        view["color_space"] = record.get("color_space")
    return view


@skill_entry
def import_interchange_manifest(
    manifest_path: str = "",
    validate_only: bool = False,
    build_material: bool = True,
    **kwargs: Any,
) -> dict:
    """Validate a typed interchange manifest and import its baked assets.

    Args:
        manifest_path: Path to the JSON sidecar manifest on disk.
        validate_only: When true, return the normalized plan without importing
            into Unreal (no Unreal runtime required).
        build_material: When true and the manifest declares a material block
            with a base-color texture, build a PBR material from the imported
            textures via ``create_texture_material``.

    Returns:
        dict: ActionResultModel with the normalized coordinate readback,
        per-asset import status, material result, and any warnings.
    """
    if not manifest_path:
        return skill_error(
            "Missing required parameter: 'manifest_path'",
            "missing_manifest_path",
            possible_solutions=["Provide the path to a typed Houdini->Unreal interchange manifest JSON file"],
        )

    try:
        raw = load_manifest(manifest_path)
        plan = validate_manifest(raw, manifest_path)
    except ManifestError as exc:
        return skill_error(
            "Invalid interchange manifest",
            "manifest_validation_failed",
            detail=str(exc),
            prompt="Fix the manifest and retry; validate_only=true can check the contract without Unreal.",
            possible_solutions=[
                "Check schema_version, assets[].source_path, and coordinate_system values",
                "See references/INTERCHANGE_MANIFEST.md for the field reference",
            ],
        )

    assets_view: List[Dict[str, Any]] = [_planned_asset(record) for record in plan["assets"]]
    warnings: List[str] = list(plan["warnings"])

    # Validate-only mode: no Unreal runtime needed, return the dry-run plan.
    if validate_only:
        return skill_success(
            "Interchange manifest validated (validate_only: nothing imported)",
            prompt="Set validate_only=false to import the planned assets into Unreal.",
            verified=True,
            schema_version=MANIFEST_VERSION,
            validate_only=True,
            coordinate_system=plan["coordinate_system"],
            destination_path=plan["destination_path"],
            producer=plan["producer"],
            assets=assets_view,
            material=plan["material"],
            warnings=warnings,
        )

    # --- import each asset via import_asset (inherits persistence + preflight) ---
    object_paths: Dict[int, str] = {}
    succeeded = 0
    failed = 0
    for record, view in zip(plan["assets"], assets_view):
        result = _import_asset_tool(**record["import_kwargs"])
        if isinstance(result, dict) and result.get("success"):
            context = result.get("context") or {}
            object_path = context.get("object_path") or context.get("asset_path") or ""
            # Key by per-entry identity, not source_path: a duplicate source
            # file must never overwrite another role's imported object path.
            object_paths[record["entry_key"]] = object_path
            view["status"] = "imported"
            view["object_path"] = object_path
            succeeded += 1
        else:
            view["status"] = "failed"
            message = result.get("message") if isinstance(result, dict) else str(result)
            warnings.append("Import failed for '{}': {}".format(record["asset_name"], message))
            failed += 1

    # --- optionally build the PBR material from imported texture roles ---
    material_result: Any = None
    material_failed = False
    material_error = ""
    material_spec = plan["material"]
    if build_material and material_spec and succeeded > 0:
        # CR-9: when a material is actually built, make a "same PBR role, many
        # textures" ambiguity explicit instead of silently wiring the first.
        # Import-only / validate_only / build_material=false paths never reach
        # here, so those manifests stay valid. Only warn once a base-color
        # texture exists (CR-11): no base_color means no material is built.
        texture_kwargs = material_texture_kwargs(plan["assets"], object_paths)
        if texture_kwargs.get("texture_path"):
            duplicates = duplicate_wired_roles(plan["assets"], object_paths)
            if duplicates:
                warnings.append(
                    "Material '{}' has multiple imported textures for PBR role(s) {}; "
                    "only the first per role is wired. Declare one texture per role "
                    "for a deterministic material.".format(material_spec["name"], ", ".join(duplicates))
                )
            call_kwargs = dict(texture_kwargs)
            call_kwargs["material_name"] = material_spec["name"]
            call_kwargs["destination_path"] = material_spec["destination_path"]
            call_kwargs["replace_existing"] = material_spec["replace_existing"]
            material_result = _create_material_tool(**call_kwargs)
            if not (isinstance(material_result, dict) and material_result.get("success")):
                material_failed = True
                if isinstance(material_result, dict):
                    material_error = str(material_result.get("message") or material_result.get("error") or "")
                else:
                    material_error = str(material_result)
                warnings.append("Material '{}' creation failed: {}".format(material_spec["name"], material_error))
        else:
            warnings.append(
                "Material '{}' declared but no base_color texture was imported; material not built".format(
                    material_spec["name"]
                )
            )

    postcondition = {
        "method": "import_interchange_manifest",
        "expected": "all {} assets imported".format(len(assets_view)),
        "actual": "{} imported, {} failed".format(succeeded, failed),
    }
    context: Dict[str, Any] = {
        "schema_version": MANIFEST_VERSION,
        "validate_only": False,
        "coordinate_system": plan["coordinate_system"],
        "destination_path": plan["destination_path"],
        "producer": plan["producer"],
        "assets": assets_view,
        "material": material_result,
        "imports_succeeded": succeeded,
        "imports_failed": failed,
        "warnings": warnings,
    }

    # A declared material that failed to build must never be reported as a
    # verified success (false acceptance). Surface it as an error while keeping
    # the import results available for inspection.
    if material_failed:
        return skill_error(
            "Interchange manifest imported {} assets but PBR material '{}' creation failed".format(
                succeeded, material_spec["name"]
            ),
            "material_creation_failed",
            prompt="Inspect the material creation error; the baked assets were imported and remain available.",
            material_error=material_error,
            **context,
        )

    return skill_success(
        "Interchange manifest processed: {} imported, {} failed".format(succeeded, failed),
        prompt="Use get_asset_info with include_details=true to verify imported bounds (cm) and colour space.",
        verified=failed == 0,
        postcondition=postcondition,
        **context,
    )


def main(**kwargs: Any) -> dict:
    """Explicit entry point; short-circuits skill_runner auto-discovery."""
    return import_interchange_manifest(**kwargs)

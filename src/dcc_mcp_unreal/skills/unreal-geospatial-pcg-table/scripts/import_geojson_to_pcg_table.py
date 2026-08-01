"""Import one GeoJSON city layer into a native Unreal PCG point DataTable."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Optional

from _geojson import SUPPORTED_LAYERS, build_point_specs, project_east_south_up
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _resolve_project_geojson(unreal, value: str) -> Path:
    path = Path(value).expanduser().resolve()
    allowed_roots = [
        Path(unreal.Paths.project_content_dir()).resolve(),
        Path(unreal.Paths.project_saved_dir()).resolve(),
    ]
    if not any(os.path.commonpath([str(path), str(root)]) == str(root) for root in allowed_roots):
        raise ValueError("geojson_path must be under the project Content or Saved directory")
    if path.suffix.lower() not in {".geojson", ".json"}:
        raise ValueError("geojson_path must end in .geojson or .json")
    if not path.is_file():
        raise ValueError("GeoJSON file does not exist: {}".format(path))
    return path


def _split_asset_path(asset_path: str) -> tuple[str, str]:
    normalized = asset_path.rstrip("/")
    if not normalized.startswith("/Game/") or normalized.count("/") < 2:
        raise ValueError("asset_path must be a /Game folder plus asset name")
    package_path, asset_name = normalized.rsplit("/", 1)
    if not asset_name or "." in asset_name:
        raise ValueError("asset_path must not contain an object suffix")
    return package_path, asset_name


def _find_georeference(unreal, label: str):
    candidates = []
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_class().get_name() != "CesiumGeoreference":
            continue
        if label and actor.get_actor_label() == label:
            return actor
        candidates.append(actor)
    if label:
        raise ValueError("CesiumGeoreference actor not found: {}".format(label))
    if len(candidates) > 1:
        raise ValueError("Multiple CesiumGeoreference actors found; pass cesium_georeference_label")
    return candidates[0] if candidates else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pcg_point_row(index: int, spec) -> dict:
    position = spec["position"]
    scale = spec.get("scale", (1.0, 1.0, 1.0))
    half_yaw = math.radians(float(spec["yaw"])) * 0.5

    def vector(value):
        return {"X": value[0], "Y": value[1], "Z": value[2]}

    return {
        "Name": "P{:08d}".format(index),
        "Transform": {
            "Rotation": {"X": 0.0, "Y": 0.0, "Z": math.sin(half_yaw), "W": math.cos(half_yaw)},
            "Translation": vector(position),
            "Scale3D": vector(scale),
        },
        "Density": 1.0,
        "BoundsMin": vector(spec["bounds_min"]),
        "BoundsMax": vector(spec["bounds_max"]),
        "Color": {"X": 1.0, "Y": 1.0, "Z": 1.0, "W": 1.0},
        "Steepness": 1.0,
        "Seed": int(spec["seed"]),
    }


def _load_or_create_table(unreal, asset_path: str, replace_existing: bool):
    package_path, asset_name = _split_asset_path(asset_path)
    existing = unreal.EditorAssetLibrary.load_asset(asset_path)
    if existing is not None:
        if not isinstance(existing, unreal.DataTable):
            raise ValueError("Existing asset is not a DataTable: {}".format(asset_path))
        if existing.get_row_struct() != unreal.PCGPoint.static_struct():
            raise ValueError("Existing DataTable does not use the PCGPoint row type: {}".format(asset_path))
        if not replace_existing:
            raise ValueError("Asset already exists; pass replace_existing=true to update it")
        return existing, False

    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", unreal.PCGPoint.static_struct())
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        package_path,
        unreal.DataTable,
        factory,
    )
    if asset is None:
        raise RuntimeError("Unreal failed to create DataTable at {}".format(asset_path))
    return asset, True


@skill_entry
def import_geojson_to_pcg_table(
    geojson_path: str,
    asset_path: str,
    layer: str,
    road_spacing_m: float = 25.0,
    max_points: int = 100_000,
    cesium_georeference_label: str = "",
    origin_longitude: Optional[float] = None,
    origin_latitude: Optional[float] = None,
    attribution: str = "OpenStreetMap contributors, ODbL 1.0",
    replace_existing: bool = False,
    **kwargs,
) -> dict:
    """Create or update a georeferenced PCGPoint DataTable from GeoJSON."""
    import unreal  # noqa: PLC0415

    try:
        source = _resolve_project_geojson(unreal, geojson_path)
        _split_asset_path(asset_path)
        if layer not in SUPPORTED_LAYERS:
            raise ValueError("Unsupported layer: {}".format(layer))
        if not 1.0 <= float(road_spacing_m) <= 500.0:
            raise ValueError("road_spacing_m must be between 1 and 500")
        if not 1 <= int(max_points) <= 500_000:
            raise ValueError("max_points must be between 1 and 500000")

        georeference = _find_georeference(unreal, cesium_georeference_label)
        if georeference is not None:
            georeference_transform = georeference.get_actor_transform()

            def projector(longitude: float, latitude: float, height_m: float):
                local = georeference.transform_longitude_latitude_height_position_to_unreal(
                    unreal.Vector(longitude, latitude, height_m)
                )
                world = georeference_transform.transform_location(local)
                return (float(world.x), float(world.y), float(world.z))

            coordinate_mode = "cesium_georeference"
            georeference_label = georeference.get_actor_label()
        else:
            if origin_longitude is None or origin_latitude is None:
                raise ValueError("No CesiumGeoreference is active; pass origin_longitude and origin_latitude")

            def projector(longitude: float, latitude: float, height_m: float):
                return project_east_south_up(
                    longitude,
                    latitude,
                    height_m,
                    float(origin_longitude),
                    float(origin_latitude),
                )

            coordinate_mode = "east_south_up_fallback"
            georeference_label = None

        with source.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        sampled = build_point_specs(
            payload,
            projector,
            [layer],
            float(road_spacing_m),
            int(max_points),
        )
        if sampled["total_points"] == 0:
            raise ValueError("No supported GeoJSON features produced PCG points")

        asset, created = _load_or_create_table(unreal, asset_path, bool(replace_existing))
        rows = [_pcg_point_row(index, spec) for index, spec in enumerate(sampled["points"][layer])]
        if not asset.fill_from_json_string(json.dumps(rows), unreal.PCGPoint.static_struct()):
            raise RuntimeError("Unreal failed to populate PCGPoint rows in {}".format(asset_path))
        unreal.EditorAssetLibrary.set_metadata_tag(asset, "GeoJSONLayer", layer)
        unreal.EditorAssetLibrary.set_metadata_tag(asset, "SourceAttribution", attribution)
        unreal.EditorAssetLibrary.set_metadata_tag(asset, "SourceSHA256", _sha256(source))
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Unreal failed to save {}".format(asset_path))

        return skill_success(
            "Imported {:,} georeferenced GeoJSON points into {}".format(sampled["total_points"], asset_path),
            prompt="Load this table with UE 5.8's native PCG Load Data Table node.",
            asset_path=asset_path,
            created=created,
            coordinate_mode=coordinate_mode,
            cesium_georeference_label=georeference_label,
            layer=layer,
            feature_counts=sampled["feature_counts"],
            point_counts=sampled["point_counts"],
            source_feature_count=sampled["source_feature_count"],
            total_points=sampled["total_points"],
            truncated=sampled["truncated"],
            source_path=str(source),
            source_sha256=_sha256(source),
            attribution=attribution,
        )
    except Exception as exc:
        return skill_error(
            "GeoJSON to PCG import failed",
            str(exc),
            prompt="Verify the GeoJSON path, destination asset path, selected layers, and active CesiumGeoreference.",
        )

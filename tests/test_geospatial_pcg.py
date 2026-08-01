"""Pure tests for the Unreal geospatial PCG importer."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dcc_mcp_unreal"
        / "skills"
        / "unreal-geospatial-pcg-table"
        / "scripts"
        / "_geojson.py"
    )
    spec = importlib.util.spec_from_file_location("unreal_geospatial_pcg_geojson", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _entry_module():
    scripts = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dcc_mcp_unreal"
        / "skills"
        / "unreal-geospatial-pcg-table"
        / "scripts"
    )
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "unreal_geospatial_pcg_import", scripts / "import_geojson_to_pcg_table.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_classifies_osm_semantic_layers() -> None:
    geo = _module()
    assert geo.classify_feature({"highway": "primary"}) == "roads"
    assert geo.classify_feature({"highway": "footway"}) == "pedestrian"
    assert geo.classify_feature({"highway": "pedestrian"}) == "pedestrian"
    assert geo.classify_feature({"highway": "steps"}) is None
    assert geo.classify_feature({"building": "yes"}) == "buildings"
    assert geo.classify_feature({"railway": "rail"}) == "railways"
    assert geo.classify_feature({"natural": "water"}) == "water"
    assert geo.classify_feature({"landuse": "commercial"}) == "landuse"
    assert geo.classify_feature({"amenity": "bench"}) is None


def test_projects_to_unreal_east_south_up_centimeters() -> None:
    geo = _module()
    origin = (-73.9855, 40.7580)
    east = geo.project_east_south_up(origin[0] + 0.001, origin[1], 2.0, *origin)
    north = geo.project_east_south_up(origin[0], origin[1] + 0.001, 0.0, *origin)
    assert east[0] > 8_000
    assert abs(east[1]) < 1e-6
    assert east[2] == 200.0
    assert north[1] < -11_000


def test_builds_bounded_road_pedestrian_and_building_points() -> None:
    geo = _module()
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "way/footway",
                "properties": {"highway": "footway"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-73.9855, 40.7581], [-73.9845, 40.7581]],
                },
            },
            {
                "type": "Feature",
                "id": "way/road",
                "properties": {"highway": "residential"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-73.9855, 40.7580], [-73.9845, 40.7580]],
                },
            },
            {
                "type": "Feature",
                "id": "way/building",
                "properties": {"building": "yes", "building:levels": "10"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-73.9855, 40.7580],
                            [-73.9854, 40.7580],
                            [-73.9854, 40.7581],
                            [-73.9855, 40.7581],
                            [-73.9855, 40.7580],
                        ]
                    ],
                },
            },
        ],
    }

    def projector(lon: float, lat: float, height: float):
        return geo.project_east_south_up(lon, lat, height, -73.9855, 40.7580)

    result = geo.build_point_specs(payload, projector, ["roads", "pedestrian", "buildings"], 25.0, 100)
    assert result["source_feature_count"] == 3
    assert result["feature_counts"] == {"roads": 1, "pedestrian": 1, "buildings": 1}
    assert result["point_counts"]["roads"] >= 4
    assert result["point_counts"]["pedestrian"] >= 4
    assert result["point_counts"]["buildings"] == 1
    assert result["points"]["roads"][0]["scale"] == (25.0, 6.0, 0.08)
    assert result["points"]["pedestrian"][0]["scale"] == (25.0, 2.0, 0.08)
    assert result["points"]["buildings"][0]["bounds_max"][2] == 3000.0
    assert result["truncated"] is False


def test_max_points_is_a_hard_ceiling() -> None:
    geo = _module()
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "way/road",
                "properties": {"highway": "primary"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-73.99, 40.75], [-73.90, 40.75]],
                },
            }
        ],
    }
    result = geo.build_point_specs(
        payload,
        lambda lon, lat, height: (lon * 100_000.0, lat * 100_000.0, height),
        ["roads"],
        1.0,
        3,
    )
    assert result["total_points"] == 3
    assert result["truncated"] is True


def test_reports_cap_when_input_exactly_matches_max_points() -> None:
    geo = _module()
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "building/one",
                "properties": {"building": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                },
            }
        ],
    }
    result = geo.build_point_specs(payload, lambda x, y, z: (x, y, z), ["buildings"], 25.0, 1)
    assert result["total_points"] == 1
    assert result["truncated"] is True


def test_pcg_point_row_uses_native_data_table_shape() -> None:
    entry = _entry_module()
    row = entry._pcg_point_row(
        7,
        {
            "position": (10.0, 20.0, 30.0),
            "yaw": 90.0,
            "scale": (25.0, 6.0, 0.08),
            "bounds_min": (-100.0, -200.0, -25.0),
            "bounds_max": (100.0, 200.0, 25.0),
            "seed": 42,
        },
    )
    assert row["Name"] == "P00000007"
    assert row["Transform"]["Translation"] == {"X": 10.0, "Y": 20.0, "Z": 30.0}
    assert row["Transform"]["Scale3D"] == {"X": 25.0, "Y": 6.0, "Z": 0.08}
    assert abs(row["Transform"]["Rotation"]["Z"] - 2**-0.5) < 1e-9
    assert row["Seed"] == 42


def test_data_table_creation_uses_native_pcg_point_schema() -> None:
    entry = _entry_module()

    class DataTable:
        pass

    class PCGPoint:
        @staticmethod
        def static_struct():
            return "PCGPointStruct"

    class DataTableFactory:
        def __init__(self):
            self.struct = None

        def set_editor_property(self, name, value):
            assert name == "struct"
            self.struct = value

    created_asset = DataTable()
    calls = []

    class AssetTools:
        def create_asset(self, *args):
            calls.append(args)
            return created_asset

    unreal = SimpleNamespace(
        EditorAssetLibrary=SimpleNamespace(load_asset=lambda _path: None),
        AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: AssetTools()),
        DataTable=DataTable,
        DataTableFactory=DataTableFactory,
        PCGPoint=PCGPoint,
    )

    asset, created = entry._load_or_create_table(unreal, "/Game/PCG/Manhattan/DT_OSM_Manhattan_Roads", False)

    assert asset is created_asset
    assert created is True
    assert calls[0][:3] == (
        "DT_OSM_Manhattan_Roads",
        "/Game/PCG/Manhattan",
        DataTable,
    )
    assert calls[0][3].struct == "PCGPointStruct"

"""Pure GeoJSON sampling helpers for Unreal PCG imports."""

from __future__ import annotations

import math
import zlib
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

EARTH_RADIUS_M = 6_378_137.0
SUPPORTED_LAYERS = ("roads", "pedestrian", "buildings", "railways", "water", "landuse")
PEDESTRIAN_HIGHWAYS = {"footway", "pedestrian", "cycleway", "path"}

Position = Tuple[float, float, float]
Projector = Callable[[float, float, float], Position]


def classify_feature(properties: Mapping[str, object]) -> str | None:
    """Return the supported semantic layer for OSM-style properties."""
    if properties.get("building") is not None or properties.get("building:part") is not None:
        return "buildings"
    highway = properties.get("highway")
    if highway in PEDESTRIAN_HIGHWAYS:
        return "pedestrian"
    if highway == "steps":
        return None
    if highway is not None:
        return "roads"
    if properties.get("railway") is not None:
        return "railways"
    if (
        properties.get("waterway") is not None
        or properties.get("water") is not None
        or properties.get("natural") == "water"
        or properties.get("landuse") in {"basin", "reservoir"}
    ):
        return "water"
    if properties.get("landuse") is not None:
        return "landuse"
    return None


def project_east_south_up(
    longitude: float,
    latitude: float,
    height_m: float,
    origin_longitude: float,
    origin_latitude: float,
) -> Position:
    """Project WGS84 coordinates to an Unreal-compatible local frame in cm."""
    lon_delta = math.radians(longitude - origin_longitude)
    lat_delta = math.radians(latitude - origin_latitude)
    x_cm = EARTH_RADIUS_M * lon_delta * math.cos(math.radians(origin_latitude)) * 100.0
    y_cm = -EARTH_RADIUS_M * lat_delta * 100.0
    return (x_cm, y_cm, height_m * 100.0)


def _line_strings(geometry: Mapping[str, object]) -> Iterable[Sequence[Sequence[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString" and isinstance(coordinates, list):
        yield coordinates
    elif geometry_type == "MultiLineString" and isinstance(coordinates, list):
        for line in coordinates:
            if isinstance(line, list):
                yield line


def _polygon_rings(geometry: Mapping[str, object]) -> Iterable[Sequence[Sequence[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, list) and coordinates:
        yield coordinates[0]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            if isinstance(polygon, list) and polygon:
                yield polygon[0]


def _sample_polyline(points: Sequence[Position], spacing_cm: float) -> Iterable[Tuple[Position, float]]:
    if len(points) < 2:
        return

    last_emitted = points[0]
    first_dx = points[1][0] - points[0][0]
    first_dy = points[1][1] - points[0][1]
    yield points[0], math.degrees(math.atan2(first_dy, first_dx))
    distance_to_next = spacing_cm

    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-6:
            continue
        yaw = math.degrees(math.atan2(dy, dx))
        while distance_to_next <= length:
            ratio = distance_to_next / length
            last_emitted = (
                start[0] + dx * ratio,
                start[1] + dy * ratio,
                start[2] + dz * ratio,
            )
            yield last_emitted, yaw
            distance_to_next += spacing_cm
        distance_to_next -= length

    final = points[-1]
    final_distance = math.dist(last_emitted, final)
    if final_distance > spacing_cm * 0.25:
        dx = final[0] - points[-2][0]
        dy = final[1] - points[-2][1]
        yield final, math.degrees(math.atan2(dy, dx))


def _ring_point_spec(
    ring: Sequence[Sequence[float]], projector: Projector, height_m: float
) -> Dict[str, object] | None:
    projected = [projector(float(value[0]), float(value[1]), height_m) for value in ring if len(value) >= 2]
    if len(projected) < 3:
        return None
    if projected[0] == projected[-1]:
        projected = projected[:-1]
    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]
    center = ((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, projected[0][2])
    half_x = max(50.0, (max(xs) - min(xs)) * 0.5)
    half_y = max(50.0, (max(ys) - min(ys)) * 0.5)
    height_cm = max(100.0, height_m * 100.0)
    return {
        "position": center,
        "yaw": 0.0,
        "bounds_min": (-half_x, -half_y, 0.0),
        "bounds_max": (half_x, half_y, height_cm),
    }


def _building_height(properties: Mapping[str, object]) -> float:
    raw_height = properties.get("height")
    if isinstance(raw_height, (int, float)):
        return max(1.0, float(raw_height))
    if isinstance(raw_height, str):
        try:
            return max(1.0, float(raw_height.split()[0]))
        except ValueError:
            pass
    raw_levels = properties.get("building:levels")
    try:
        return max(3.0, float(raw_levels) * 3.0)
    except (TypeError, ValueError):
        return 18.0


def _road_width(properties: Mapping[str, object], layer: str) -> float:
    if layer == "railways":
        return 2.5
    road_type = str(properties.get("highway") or "")
    return {
        "motorway": 14.0,
        "trunk": 12.0,
        "primary": 10.0,
        "secondary": 8.0,
        "tertiary": 7.0,
        "residential": 6.0,
        "service": 4.0,
        "pedestrian": 5.0,
        "cycleway": 2.5,
        "footway": 2.0,
        "path": 2.0,
    }.get(road_type, 5.0)


def _feature_specs(
    feature: Mapping[str, object],
    layer: str,
    projector: Projector,
    spacing_cm: float,
) -> Iterable[Dict[str, object]]:
    geometry = feature.get("geometry")
    properties = feature.get("properties")
    if not isinstance(geometry, Mapping) or not isinstance(properties, Mapping):
        return

    if layer in {"roads", "pedestrian", "railways"}:
        width_cm = _road_width(properties, layer) * 100.0
        for line in _line_strings(geometry):
            projected = [projector(float(value[0]), float(value[1]), 0.0) for value in line if len(value) >= 2]
            for position, yaw in _sample_polyline(projected, spacing_cm):
                yield {
                    "position": position,
                    "yaw": yaw,
                    "scale": (spacing_cm / 100.0, width_cm / 100.0, 0.08),
                    "bounds_min": (-spacing_cm * 0.5, -width_cm * 0.5, -25.0),
                    "bounds_max": (spacing_cm * 0.5, width_cm * 0.5, 25.0),
                }
        return

    height_m = _building_height(properties) if layer == "buildings" else 1.0
    for ring in _polygon_rings(geometry):
        spec = _ring_point_spec(ring, projector, height_m)
        if spec is not None:
            yield spec


def build_point_specs(
    payload: Mapping[str, object],
    projector: Projector,
    layers: Sequence[str],
    road_spacing_m: float,
    max_points: int,
) -> Dict[str, object]:
    """Build bounded per-layer point specifications from a FeatureCollection."""
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("GeoJSON root must be a FeatureCollection with a features array")
    selected = tuple(dict.fromkeys(layers or SUPPORTED_LAYERS))
    invalid = [layer for layer in selected if layer not in SUPPORTED_LAYERS]
    if invalid:
        raise ValueError("Unsupported layers: {}".format(", ".join(invalid)))

    grouped: Dict[str, List[Mapping[str, object]]] = {layer: [] for layer in selected}
    for feature in payload["features"]:
        if not isinstance(feature, Mapping):
            continue
        properties = feature.get("properties")
        layer = classify_feature(properties) if isinstance(properties, Mapping) else None
        if layer in grouped:
            grouped[layer].append(feature)

    points: Dict[str, List[Dict[str, object]]] = {layer: [] for layer in selected}
    remaining = max_points
    truncated = False
    for layer in selected:
        for feature in grouped[layer]:
            feature_id = str(feature.get("id") or "")
            seed = zlib.crc32(feature_id.encode("utf-8")) & 0x7FFFFFFF
            for spec in _feature_specs(feature, layer, projector, road_spacing_m * 100.0):
                if remaining <= 0:
                    truncated = True
                    break
                spec["seed"] = seed
                points[layer].append(spec)
                remaining -= 1
            if remaining <= 0:
                break
        if remaining <= 0:
            break

    return {
        "points": points,
        "feature_counts": {layer: len(grouped[layer]) for layer in selected},
        "point_counts": {layer: len(points[layer]) for layer in selected},
        "source_feature_count": len(payload["features"]),
        "total_points": max_points - remaining,
        "truncated": truncated or remaining == 0,
    }

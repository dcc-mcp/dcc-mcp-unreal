"""Typed sidecar manifest contract for Houdini -> Unreal offline-baked exchange.

This module is the **single definition** of the interchange manifest wire
format consumed by ``import_interchange_manifest``.  It is deliberately
pure-Python, standard-library-only and Python 3.7-grammar clean so it can be
unit-tested without an Unreal runtime and can be mirrored by the producing
side (``dcc-mcp-houdini``) without a shared runtime dependency.

The manifest is a JSON sidecar file that describes a bundle of already-baked
Houdini outputs (geometry + PBR textures) and how they should land in the
Unreal Content Browser.  Coordinate-system conversions (unit scale, up-axis)
are baked by the producer at export time; this contract declares them so the
Unreal consumer can validate and surface them for verification.

Minimal example::

    {
      "schema_version": 1,
      "producer": {"dcc": "houdini", "tool": "houdini-copernicus-unreal"},
      "coordinate_system": {
        "source_unit": "m", "source_up_axis": "y",
        "target_unit": "cm", "target_up_axis": "z"
      },
      "destination_path": "/Game/Houdini/CityBank",
      "assets": [
        {"source_path": "mesh/city_bank.fbx", "kind": "geometry",
         "asset_name": "SM_CityBank"},
        {"source_path": "tex/city_bank_basecolor.exr", "kind": "texture",
         "map_type": "base_color"},
        {"source_path": "tex/city_bank_normal.exr", "kind": "texture",
         "map_type": "normal"}
      ],
      "material": {"name": "M_CityBank"}
    }

See ``references/INTERCHANGE_MANIFEST.md`` for the full field reference.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Contract version + stable enumerations
# --------------------------------------------------------------------------

MANIFEST_VERSION = 1

VALID_KINDS = ("geometry", "texture")

# Canonical map roles and their default colour space.  "srgb" maps are colour
# textures (base colour / emissive); "linear" maps are data textures that must
# NOT be sRGB-decoded (normal / roughness / metallic / AO / masks / height).
_DATA_MAP_TYPES = (
    "normal",
    "roughness",
    "metallic",
    "ambient_occlusion",
    "opacity",
    "specular",
    "displacement",
)
MAP_TYPE_DEFAULT_COLOR_SPACE = {
    "base_color": "srgb",
    "emissive": "srgb",
}
for _data_map in _DATA_MAP_TYPES:
    MAP_TYPE_DEFAULT_COLOR_SPACE[_data_map] = "linear"

# Tolerant aliases so producers can emit common names without a tight
# cross-repo coupling.  Resolution is case-insensitive.
_MAP_TYPE_ALIASES = {
    "basecolor": "base_color",
    "base_color": "base_color",
    "albedo": "base_color",
    "diffuse": "base_color",
    "color": "base_color",
    "colour": "base_color",
    "emissive": "emissive",
    "emission": "emissive",
    "normal": "normal",
    "nrm": "normal",
    "normalmap": "normal",
    "roughness": "roughness",
    "rough": "roughness",
    "metallic": "metallic",
    "metalness": "metallic",
    "metal": "metallic",
    "ambient_occlusion": "ambient_occlusion",
    "ambientocclusion": "ambient_occlusion",
    "occlusion": "ambient_occlusion",
    "ao": "ambient_occlusion",
    "opacity": "opacity",
    "alpha": "opacity",
    "mask": "opacity",
    "specular": "specular",
    "spec": "specular",
    "displacement": "displacement",
    "disp": "displacement",
    "height": "displacement",
}

_COLOR_SPACE_ALIASES = {
    "srgb": "srgb",
    "s_rgb": "srgb",
    "gamma": "srgb",
    "color": "srgb",
    "colour": "srgb",
    "linear": "linear",
    "raw": "linear",
    "data": "linear",
    "non_color": "linear",
    "noncolor": "linear",
}

VALID_COLOR_SPACES = ("srgb", "linear")

# Unit conversion factors into centimetres (Unreal's native unit).
_UNIT_TO_CM = {"m": 100.0, "cm": 1.0, "mm": 0.1, "km": 100000.0, "in": 2.54, "ft": 30.48}
VALID_UNITS = tuple(sorted(_UNIT_TO_CM))
VALID_UP_AXES = ("y", "z")
VALID_GAMUTS = ("", "srgb")

# Field aliases at the manifest / asset level (producer tolerance).
_MANIFEST_ALIASES = {
    "schema_version": ("schema_version", "version", "manifest_version"),
    "assets": ("assets", "files", "entries"),
    "destination_path": ("destination_path", "destination", "content_path"),
    "coordinate_system": ("coordinate_system", "coords", "coordinate"),
    "material": ("material", "pbr_material"),
}
_ASSET_ALIASES = {
    "source_path": ("source_path", "path", "file", "source"),
    "kind": ("kind", "type"),
    "asset_name": ("asset_name", "name"),
    "map_type": ("map_type", "map", "slot", "role"),
    "color_space": ("color_space", "colorspace", "color"),
    "non_color_texture": ("non_color_texture", "non_color", "linear"),
    "import_as_geometry_cache": ("import_as_geometry_cache", "geometry_cache"),
}

# Extensions recognised for each kind (used only to infer kind / cache flag).
_GEOMETRY_EXTENSIONS = (".fbx", ".abc", ".obj")
_TEXTURE_EXTENSIONS = (".png", ".exr", ".tga", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".hdr")


class ManifestError(ValueError):
    """Raised when a manifest violates the contract.  Message is user-facing."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _first_present(mapping: Dict[str, Any], names: Tuple[str, ...], default: Any = None) -> Any:
    """Return the first present key from *names*, else *default*."""
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _as_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    raise ManifestError("'{}' must be a boolean".format(label))


def _resolve_map_type(value: str) -> Tuple[str, Optional[str]]:
    """Return (canonical_map_type, warning) for a producer-supplied value."""
    key = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    canonical = _MAP_TYPE_ALIASES.get(key)
    if canonical is None:
        return "data", "Unknown map_type '{}'; treated as linear data".format(value)
    return canonical, None


def _resolve_color_space(value: str) -> str:
    key = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    resolved = _COLOR_SPACE_ALIASES.get(key)
    if resolved not in VALID_COLOR_SPACES:
        raise ManifestError("Unsupported color_space '{}'; expected one of {}".format(value, list(VALID_COLOR_SPACES)))
    return resolved


# --------------------------------------------------------------------------
# Loading + validation
# --------------------------------------------------------------------------


def load_manifest(manifest_path: str) -> Dict[str, Any]:
    """Read a JSON manifest from disk.  Raises :class:`ManifestError` on I/O or JSON errors."""
    if not manifest_path:
        raise ManifestError("manifest_path is required")
    if not os.path.isfile(manifest_path):
        raise ManifestError("Manifest file not found: {}".format(manifest_path))
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:  # ValueError covers json.JSONDecodeError on all versions
        raise ManifestError("Could not read manifest '{}': {}".format(manifest_path, exc))
    if not isinstance(data, dict):
        raise ManifestError("Manifest root must be a JSON object")
    return data


def _normalize_coordinate_system(coords: Any) -> Dict[str, Any]:
    """Validate coordinate metadata and compute unit/axis conversion readback."""
    if coords is None:
        coords = {}
    if not isinstance(coords, dict):
        raise ManifestError("coordinate_system must be an object")
    source_unit = str(_first_present(coords, ("source_unit", "unit", "from_unit"), "cm")).strip().casefold()
    target_unit = str(_first_present(coords, ("target_unit", "to_unit"), "cm")).strip().casefold()
    source_up = str(_first_present(coords, ("source_up_axis", "up_axis", "from_axis"), "z")).strip().casefold()
    target_up = str(_first_present(coords, ("target_up_axis", "to_axis"), "z")).strip().casefold()

    if source_unit not in _UNIT_TO_CM:
        raise ManifestError("Unsupported source_unit '{}'; expected one of {}".format(source_unit, VALID_UNITS))
    if target_unit not in _UNIT_TO_CM:
        raise ManifestError("Unsupported target_unit '{}'; expected one of {}".format(target_unit, VALID_UNITS))
    if source_up not in VALID_UP_AXES or target_up not in VALID_UP_AXES:
        raise ManifestError("up_axis must be one of {}".format(list(VALID_UP_AXES)))

    unit_scale = _UNIT_TO_CM[source_unit] / _UNIT_TO_CM[target_unit]
    return {
        "source_unit": source_unit,
        "target_unit": target_unit,
        "source_up_axis": source_up,
        "target_up_axis": target_up,
        "unit_scale": unit_scale,
        "unit_conversion_required": abs(unit_scale - 1.0) > 1e-9,
        "axis_conversion_required": source_up != target_up,
        # Conversions are baked by the producer at export; declare that here
        # so the consumer does not double-apply a scale.
        "applied_by": "producer_export",
        "verification": "get_asset_info reports local bounds in cm after import",
    }


def _normalize_asset(
    entry: Any, index: int, manifest_dir: str, default_destination: str
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate one asset entry and produce its import_asset kwargs."""
    warnings: List[str] = []
    if not isinstance(entry, dict):
        raise ManifestError("assets[{}] must be an object".format(index))

    source_path = _first_present(entry, _ASSET_ALIASES["source_path"])
    if not source_path or not isinstance(source_path, str):
        raise ManifestError("assets[{}].source_path is required and must be a string".format(index))

    # Resolve relative paths against the manifest directory, then canonicalize
    # every path (absolute paths included) so the duplicate check compares
    # resolved spellings rather than raw strings.
    if not os.path.isabs(source_path):
        source_path = os.path.join(manifest_dir, source_path)
    source_path = os.path.normpath(source_path)

    extension = os.path.splitext(source_path)[1].lower()
    kind = _first_present(entry, _ASSET_ALIASES["kind"])
    if kind is None:
        if extension in _GEOMETRY_EXTENSIONS:
            kind = "geometry"
        elif extension in _TEXTURE_EXTENSIONS or _first_present(entry, _ASSET_ALIASES["map_type"]) is not None:
            kind = "texture"
        else:
            kind = "geometry"
    kind = str(kind).strip().casefold()
    if kind not in VALID_KINDS:
        raise ManifestError("assets[{}].kind '{}' must be one of {}".format(index, kind, list(VALID_KINDS)))

    asset_name = _first_present(entry, _ASSET_ALIASES["asset_name"], "")
    if not asset_name:
        asset_name = os.path.splitext(os.path.basename(source_path))[0]
    asset_name = str(asset_name)

    destination_path = str(_first_present(entry, ("destination_path", "destination"), default_destination))
    destination_path = destination_path.rstrip("/") or "/Game/Imports"

    import_kwargs: Dict[str, Any] = {
        "source_path": source_path,
        "destination_path": destination_path,
        "asset_name": asset_name,
    }

    result: Dict[str, Any] = {
        "source_path": source_path,
        "asset_name": asset_name,
        "destination_path": destination_path,
        "kind": kind,
        # Stable per-entry identity.  Keying imported object paths by this
        # (instead of by source_path) means a manifest that lists the same
        # file twice with different roles cannot cross-wire textures.
        "entry_key": index,
        "import_kwargs": import_kwargs,
    }

    if kind == "texture":
        map_value = _first_present(entry, _ASSET_ALIASES["map_type"])
        if map_value is None:
            map_type, warning = "data", "assets[{}] has no map_type; treated as linear data".format(index)
            if warning:
                warnings.append(warning)
            result["map_type"] = "data"
            default_space = "linear"
        else:
            map_type, warning = _resolve_map_type(str(map_value))
            if warning:
                warnings.append(warning)
            result["map_type"] = map_type
            default_space = MAP_TYPE_DEFAULT_COLOR_SPACE.get(map_type, "linear")

        if _first_present(entry, _ASSET_ALIASES["color_space"]) is not None:
            color_space = _resolve_color_space(str(_first_present(entry, _ASSET_ALIASES["color_space"])))
        elif _first_present(entry, _ASSET_ALIASES["non_color_texture"]) is not None:
            non_color = _as_bool(_first_present(entry, _ASSET_ALIASES["non_color_texture"]), "non_color_texture")
            color_space = "linear" if non_color else "srgb"
        else:
            color_space = default_space

        # Optional source gamut conversion for wide-gamut working spaces.
        gamut = str(_first_present(entry, ("source_gamut", "gamut"), "")).strip().casefold()
        if gamut not in VALID_GAMUTS:
            raise ManifestError("assets[{}].source_gamut must be one of {}".format(index, list(VALID_GAMUTS)))
        # A source gamut conversion only makes sense for colour (sRGB) maps.
        # On linear data maps it would produce source_color_space="srgb" plus
        # non_color_texture=True, a combination import_asset rejects.
        if gamut and color_space == "linear":
            raise ManifestError(
                "assets[{}].source_gamut '{}' requires an srgb color_space, not a linear data map".format(index, gamut)
            )

        result["color_space"] = color_space
        result["map_type_canonical"] = map_type
        import_kwargs["source_color_space"] = gamut
        import_kwargs["non_color_texture"] = color_space == "linear"
    else:  # geometry
        if extension == ".abc" and _first_present(entry, _ASSET_ALIASES["import_as_geometry_cache"]) is not None:
            import_kwargs["import_as_geometry_cache"] = _as_bool(
                _first_present(entry, _ASSET_ALIASES["import_as_geometry_cache"]), "import_as_geometry_cache"
            )

    return result, warnings


def _normalize_material(material: Any, default_destination: str) -> Optional[Dict[str, Any]]:
    if material is None:
        return None
    if not isinstance(material, dict):
        raise ManifestError("material must be an object")
    name = _first_present(material, ("name", "material_name"), "")
    if not name:
        raise ManifestError("material.name is required when a material block is present")
    return {
        "name": str(name),
        "destination_path": str(_first_present(material, ("destination_path", "destination"), default_destination)),
        "replace_existing": _as_bool(
            _first_present(material, ("replace_existing",), True), "material.replace_existing"
        ),
    }


def validate_manifest(data: Dict[str, Any], manifest_path: str = "") -> Dict[str, Any]:
    """Validate a raw manifest dict and return a fully normalized structure.

    The returned dict has: ``schema_version``, ``producer``,
    ``coordinate_system`` (normalized readback), ``destination_path``,
    ``assets`` (each with ready-to-use ``import_kwargs`` for ``import_asset``),
    ``material`` (or ``None``), and ``warnings``.
    """
    if not isinstance(data, dict):
        raise ManifestError("Manifest root must be a JSON object")

    version = _first_present(data, _MANIFEST_ALIASES["schema_version"], MANIFEST_VERSION)
    # Reject bool (a bool is an int subclass) and anything that is not already
    # an int; int() would silently coerce 1.5 and True to 1.
    if isinstance(version, bool) or not isinstance(version, int):
        raise ManifestError("schema_version must be an integer")
    if version != MANIFEST_VERSION:
        raise ManifestError("Unsupported schema_version {}; expected {}".format(version, MANIFEST_VERSION))

    destination_path = str(_first_present(data, _MANIFEST_ALIASES["destination_path"], "/Game/Imports"))
    destination_path = destination_path.rstrip("/") or "/Game/Imports"

    raw_assets = _first_present(data, _MANIFEST_ALIASES["assets"])
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ManifestError("Manifest must contain a non-empty 'assets' list")

    manifest_dir = os.path.dirname(os.path.abspath(manifest_path)) if manifest_path else os.getcwd()

    coordinate_system = _normalize_coordinate_system(_first_present(data, _MANIFEST_ALIASES["coordinate_system"], {}))
    material = _normalize_material(_first_present(data, _MANIFEST_ALIASES["material"]), destination_path)

    assets: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen_sources: Dict[str, int] = {}
    for index, entry in enumerate(raw_assets):
        normalized, entry_warnings = _normalize_asset(entry, index, manifest_dir, destination_path)
        # Duplicate source files are ambiguous: two entries could declare the
        # same image with different roles, and the last import would win.
        source = normalized["source_path"]
        if source in seen_sources:
            raise ManifestError(
                "assets[{}] duplicates source_path '{}' already used by assets[{}]".format(
                    index, source, seen_sources[source]
                )
            )
        seen_sources[source] = index
        assets.append(normalized)
        warnings.extend(entry_warnings)

    producer = _first_present(data, ("producer", "source"), {})
    if not isinstance(producer, dict):
        producer = {}

    return {
        "schema_version": version,
        "producer": dict(producer),
        "coordinate_system": coordinate_system,
        "destination_path": destination_path,
        "assets": assets,
        "material": material,
        "warnings": warnings,
    }


# Canonical PBR roles consumed by ``create_texture_material`` (role -> kwarg).
_WIRED_ROLE_PARAMS = {
    "base_color": "texture_path",
    "normal": "normal_texture_path",
    "roughness": "roughness_texture_path",
    "metallic": "metallic_texture_path",
    "ambient_occlusion": "ambient_occlusion_texture_path",
}


def duplicate_wired_roles(assets: List[Dict[str, Any]], object_paths: Dict[int, str]) -> List[str]:
    """Return canonical roles wired by more than one *imported* texture.

    A role fed by several textures is ambiguous: ``material_texture_kwargs``
    keeps only the first per role. This ambiguity matters only when a material
    is actually built, so callers consult it on the material-building path
    alone; import-only and ``build_material=false`` flows never call it.
    Roles without a successfully imported object path are ignored.
    """
    counts: Dict[str, int] = {}
    for asset in assets:
        if asset.get("kind") != "texture" or not object_paths.get(asset["entry_key"]):
            continue
        role = asset.get("map_type_canonical") or asset.get("map_type")
        if role in _WIRED_ROLE_PARAMS:
            counts[role] = counts.get(role, 0) + 1
    return sorted(role for role, count in counts.items() if count > 1)


def material_texture_kwargs(assets: List[Dict[str, Any]], object_paths: Dict[int, str]) -> Dict[str, str]:
    """Build ``create_texture_material`` kwargs from imported texture object paths.

    ``object_paths`` maps each asset's per-entry ``entry_key`` to the Content
    Browser object path returned by ``import_asset``.  Keying by entry (not by
    ``source_path``) avoids collisions when the same file appears more than once.
    Only canonical PBR roles are wired into the material; unknown roles are ignored.
    """
    kwargs: Dict[str, str] = {}
    for asset in assets:
        if asset.get("kind") != "texture":
            continue
        map_type = asset.get("map_type_canonical") or asset.get("map_type")
        param = _WIRED_ROLE_PARAMS.get(map_type)
        if param is None:
            continue
        object_path = object_paths.get(asset["entry_key"])
        if object_path and param not in kwargs:
            kwargs[param] = object_path
    return kwargs

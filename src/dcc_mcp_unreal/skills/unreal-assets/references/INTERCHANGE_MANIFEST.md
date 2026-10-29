# Houdini -> Unreal interchange manifest (v1)

The typed sidecar manifest is the **single contract** between a Houdini-side
producer (COPS/Copernicus texture bake or baked HDA geometry) and the Unreal
consumer tool `unreal_assets__import_interchange_manifest`. It is a JSON file
that ships next to the baked files. The authoritative field definitions live in
`scripts/_interchange_manifest.py`; this document is the portable,
language-neutral reference that the producing repository implements against.

The manifest describes **already-baked** outputs. No Houdini Engine plugin,
HAPI session, or live link is required on the Unreal side. Coordinate-system
conversions (unit scale, up-axis) are baked by the producer at export time and
**declared** here so the consumer can validate and surface them as readback for
`unreal_assets__get_asset_info` verification. The consumer never re-applies a
scale.

## Top-level fields

| Field | Type | Required | Default | Meaning |
|-------|------|----------|---------|---------|
| `schema_version` | int | no | `1` | Must equal `1`. Aliases: `version`, `manifest_version`. |
| `producer` | object | no | `{}` | Free-form provenance (`dcc`, `tool`, `hda`, ...). |
| `coordinate_system` | object | no | cm / Z-up | Source & target unit and up-axis metadata (below). Aliases: `coords`, `coordinate`. |
| `destination_path` | string | no | `/Game/Imports` | Default Content Browser folder. Aliases: `destination`, `content_path`. |
| `assets` | array | **yes** | — | Non-empty list of asset entries. Aliases: `files`, `entries`. |
| `material` | object | no | `null` | Optional PBR material to build after import. Aliases: `pbr_material`. |

## `coordinate_system`

| Field | Values | Default |
|-------|--------|---------|
| `source_unit` | `m`, `cm`, `mm`, `km`, `in`, `ft` | `cm` |
| `target_unit` | same set | `cm` (Unreal) |
| `source_up_axis` | `y`, `z` | `z` |
| `target_up_axis` | `y`, `z` | `z` |

Aliases: `unit`/`from_unit`, `up_axis`/`from_axis`, `to_unit`, `to_axis`. The
consumer computes `unit_scale = source_to_cm / target_to_cm` and
`unit_conversion_required` / `axis_conversion_required` flags as readback. These
are **informational**: the producer is responsible for baking the conversion
into the exported FBX/Alembic (e.g. Houdini `export_fbx(convert_units=True)`),
so the consumer does not double-transform. `applied_by` is always
`producer_export`.

## `assets[]` entry

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `source_path` | string | **yes** | Path to the baked file. Relative paths resolve against the manifest's directory. Aliases: `path`, `file`, `source`. |
| `kind` | `geometry` \| `texture` | no | Inferred from extension / presence of `map_type` when omitted. Alias: `type`. |
| `asset_name` | string | no | Content Browser asset name; defaults to the file stem. Alias: `name`. |
| `destination_path` | string | no | Per-asset override of the top-level destination. Alias: `destination`. |
| `map_type` | string | no | PBR role (below). Missing on a texture: treated as linear data with a warning and excluded from material role wiring. Aliases: `map`, `slot`, `role`. |
| `color_space` | `srgb` \| `linear` | textures | Overrides the map-type default. Aliases: `colorspace`, `color`. |
| `non_color_texture` | bool | textures | Alternative to `color_space`; `true` => linear, `false` => srgb. Aliases: `non_color`, `linear`. |
| `source_gamut` | `` \| `srgb` | textures | Optional source-gamut conversion for wide-gamut working spaces. Default empty. Only valid on `srgb` (colour) maps; declaring it on a linear data map is a validation error. Alias: `gamut`. |
| `import_as_geometry_cache` | bool | `.abc` geometry | Import Alembic as Geometry Cache. Alias: `geometry_cache`. |

### PBR map types and default colour space

| `map_type` (canonical) | Aliases | Default `color_space` | Effect |
|------------------------|---------|----------------------|--------|
| `base_color` | `basecolor`, `albedo`, `diffuse`, `color`, `colour` | `srgb` | `non_color_texture=false`, sRGB decode on. |
| `emissive` | `emission` | `srgb` | `non_color_texture=false`. |
| `normal` | `nrm`, `normalmap` | `linear` | `non_color_texture=true` (no sRGB decode). |
| `roughness` | `rough` | `linear` | `non_color_texture=true`. |
| `metallic` | `metalness`, `metal` | `linear` | `non_color_texture=true`. |
| `ambient_occlusion` | `ao`, `occlusion`, `ambientocclusion` | `linear` | `non_color_texture=true`. |
| `opacity` | `alpha`, `mask` | `linear` | `non_color_texture=true`. |
| `specular` | `spec` | `linear` | `non_color_texture=true`. |
| `displacement` | `disp`, `height` | `linear` | `non_color_texture=true`. |

Unknown `map_type` values are treated as generic linear data and produce a
warning (never a hard failure), keeping the contract forward-tolerant.

### Validation rules

- `schema_version` must be the integer `1` (not a bool, float, or string).
- Each `source_path` must be unique after path resolution. Listing the same
  file twice (e.g. with two different roles) is rejected rather than letting
  one import overwrite the other's material wiring.
- `coordinate_system`, when present, must be an object; `null`/missing uses
  defaults, but any other non-object value is an error.
- `source_gamut: srgb` is accepted only on `srgb` (colour) maps. Declaring it
  on a linear data map is rejected because it would yield an inconsistent
  `source_color_space` + `non_color_texture` combination.

## `material`

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `name` | string | **yes** | — |
| `destination_path` | string | no | top-level `destination_path` |
| `replace_existing` | bool | no | `true` |

The consumer wires imported textures into `create_texture_material` by canonical
role: `base_color` -> `texture_path`, `normal` -> `normal_texture_path`, etc. A
material is only built when a base-colour texture was successfully imported.

## Example

```json
{
  "schema_version": 1,
  "producer": {"dcc": "houdini", "tool": "houdini-copernicus-unreal", "hda": "city_bank.hda"},
  "coordinate_system": {
    "source_unit": "m", "source_up_axis": "y",
    "target_unit": "cm", "target_up_axis": "z"
  },
  "destination_path": "/Game/Houdini/CityBank",
  "assets": [
    {"source_path": "mesh/city_bank.fbx", "kind": "geometry", "asset_name": "SM_CityBank"},
    {"source_path": "tex/city_bank_basecolor.exr", "kind": "texture", "map_type": "base_color"},
    {"source_path": "tex/city_bank_normal.exr", "kind": "texture", "map_type": "normal"},
    {"source_path": "tex/city_bank_roughness.exr", "kind": "texture", "map_type": "roughness"},
    {"source_path": "tex/city_bank_ao.png", "kind": "texture", "map_type": "ao"}
  ],
  "material": {"name": "M_CityBank"}
}
```

## Verification workflow

1. Producer writes baked files + this manifest, with unit/up-axis conversions
   baked into the geometry at export.
2. Agent calls `unreal_assets__import_interchange_manifest` with `manifest_path`.
   `validate_only=true` first can dry-run the contract without Unreal.
3. The tool imports each asset via `import_asset` and optionally builds the
   material via `create_texture_material`; colour space is applied from map type.
4. Agent calls `unreal_assets__get_asset_info` with `include_details=true` to
   verify local bounds (cm), sRGB vs linear flags, and material slots.

---
name: unreal-assets
description: "Unreal Engine Content Browser asset management — list, import, export, and inspect assets"
dcc: unreal
version: "0.1.0"
tags: [unreal, assets, content-browser, import, export]
license: "MIT"
depends: []
tools:
  - name: list_assets
    description: "List assets in a Content Browser directory path"
    source_file: "scripts/list_assets.py"
  - name: import_asset
    description: "Import a file (FBX, PNG, WAV, …) into the Content Browser"
    source_file: "scripts/import_asset.py"
  - name: export_asset
    description: "Export an asset to a file on disk"
    source_file: "scripts/export_asset.py"
  - name: get_asset_info
    description: "Get metadata for an asset (type, path, dependencies)"
    source_file: "scripts/get_asset_info.py"
  - name: delete_asset
    description: "Delete one or more assets from the Content Browser"
    source_file: "scripts/delete_asset.py"
---

# unreal-assets

Unreal Engine asset management skill. Provides actions for working with assets
in the Content Browser.

## Scripts

- `list_assets` — List assets in a Content Browser directory path
- `import_asset` — Import a file (FBX, PNG, WAV, …) into the Content Browser
- `export_asset` — Export an asset to a file on disk
- `get_asset_info` — Get metadata for an asset (type, path, dependencies)
- `delete_asset` — Delete one or more assets from the Content Browser

## Usage Examples

### List all static meshes under /Game/Meshes

```python
# MCP tool call: unreal_assets__list_assets
# params: {"directory_path": "/Game/Meshes", "asset_class_filter": "StaticMesh"}
```

### Import an FBX file

```python
# MCP tool call: unreal_assets__import_asset
# params: {
#   "source_path": "C:/art/my_mesh.fbx",
#   "destination_path": "/Game/Meshes",
#   "asset_name": "SM_MyMesh"
# }
```

### Export a texture to PNG

```python
# MCP tool call: unreal_assets__export_asset
# params: {
#   "asset_path": "/Game/Textures/T_Rock.T_Rock",
#   "export_path": "C:/exports/T_Rock.png"
# }
```

### Get asset metadata

```python
# MCP tool call: unreal_assets__get_asset_info
# params: {"asset_path": "/Game/Meshes/SM_Cube", "include_dependencies": true}
```

### Delete an asset

```python
# MCP tool call: unreal_assets__delete_asset
# params: {"asset_paths": ["/Game/Meshes/SM_OldMesh", "/Game/Textures/T_Unused"]}
```

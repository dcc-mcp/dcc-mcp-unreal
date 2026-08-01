---
name: unreal-assets
description: >-
  Domain skill - Unreal Engine Content Browser asset management: list, import,
  export, inspect, and delete assets. Use for package and asset operations in
  the Unreal Editor. Not for actor placement or transforms - use unreal-actors
  for that.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: interchange
    search-hint: "unreal content browser asset registry import export delete fbx texture package"
    tags: "unreal, assets, content-browser, import, export, pipeline"
    tools: tools.yaml
---

# Unreal Assets

Tools for Content Browser asset discovery, import, export, inspection, and deletion.

## Scripts

- `list_assets`
- `import_asset`
- `export_asset`
- `get_asset_info`
- `delete_asset`
- `create_ocio_configuration`

---
name: unreal-assets
description: "Unreal Engine Content Browser asset management — list, import, export, and inspect assets"
dcc: unreal
version: "0.1.0"
tags: [unreal, assets, content-browser, import, export]
license: "MIT"
allowed-tools: ["Bash", "Read"]
depends: []
---

# unreal-assets

Unreal Engine asset management skill. Provides actions for working with assets
in the Content Browser.

## Scripts

- `list_assets` — List assets in a Content Browser directory path
- `import_asset` — Import a file (FBX, PNG, WAV, …) into the Content Browser
- `export_asset` — Export an asset to a file on disk
- `get_asset_info` — Get metadata for an asset (size, type, dependencies)
- `delete_asset` — Delete an asset from the Content Browser

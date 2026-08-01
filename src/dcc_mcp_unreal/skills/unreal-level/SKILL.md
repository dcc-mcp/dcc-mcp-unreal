---
name: unreal-level
description: >-
  Domain skill - Unreal Engine level and world management: inspect level state,
  load and save maps, and read or edit world settings. Use for active Editor
  level operations. Not for individual actor transform edits - use
  unreal-actors for that.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal level world settings gravity time dilation save load map streaming"
    tags: "unreal, level, world, streaming, scene"
    tools: tools.yaml
---

# Unreal Level

Tools for active level inspection, map loading/saving, and world settings.

## Scripts

- `create_level`
- `get_level_info`
- `load_level`
- `save_level`
- `get_world_settings`
- `set_world_settings`

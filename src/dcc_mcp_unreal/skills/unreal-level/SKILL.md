---
name: unreal-level
description: "Unreal Engine level management — load levels, get world info, save, and modify world settings"
dcc: unreal
version: "0.1.0"
tags: [unreal, level, world, streaming, gravity]
license: "MIT"
depends: []
tools:
  - name: get_level_info
    description: "Get current level name, actor count, and streaming level info"
    source_file: "scripts/get_level_info.py"
  - name: load_level
    description: "Load a level by Content Browser asset path"
    source_file: "scripts/load_level.py"
  - name: save_level
    description: "Save the current level (and optionally all dirty packages)"
    source_file: "scripts/save_level.py"
  - name: get_world_settings
    description: "Get world settings: gravity, time dilation, kill-Z, lightmass"
    source_file: "scripts/get_world_settings.py"
  - name: set_world_settings
    description: "Modify world settings: gravity_z, time_dilation, kill_z"
    source_file: "scripts/set_world_settings.py"
---

# unreal-level

Unreal Engine level management skill. Provides actions for working with levels
and world settings in the Editor.

## Scripts

- `get_level_info` — Get current level name, actor count, world type, and streaming levels
- `load_level` — Load a level by Content Browser asset path
- `save_level` — Save the current level (and optionally all dirty packages)
- `get_world_settings` — Get gravity, time dilation, kill-Z, and lightmass settings
- `set_world_settings` — Modify gravity_z, time_dilation, and kill_z

## Usage Examples

### Get info about the current level

```python
# MCP tool call: unreal_level__get_level_info
# params: {}
```

### Load a different level

```python
# MCP tool call: unreal_level__load_level
# params: {"level_path": "/Game/Maps/TestLevel", "save_current": true}
```

### Save the current level

```python
# MCP tool call: unreal_level__save_level
# params: {"save_all_dirty": false}
```

### Inspect world settings

```python
# MCP tool call: unreal_level__get_world_settings
# params: {}
```

### Set zero gravity and slow motion

```python
# MCP tool call: unreal_level__set_world_settings
# params: {"gravity_z": 0.0, "time_dilation": 0.25}
```

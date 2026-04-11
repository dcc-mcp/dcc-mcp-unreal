---
name: unreal-level
description: "Unreal Engine level management — load levels, get world info, manage streaming"
dcc: unreal
version: "0.1.0"
tags: [unreal, level, world, streaming]
license: "MIT"
allowed-tools: ["Bash", "Read"]
depends: []
---

# unreal-level

Unreal Engine level management skill. Provides actions for working with levels
and world settings.

## Scripts

- `get_level_info` — Get current level name, actor count, and world settings
- `load_level` — Load a level by asset path
- `save_level` — Save the current level
- `get_world_settings` — Get world settings (gravity, time dilation, etc.)
- `set_world_settings` — Modify world settings

---
name: unreal-hair
description: >-
  Domain skill - bind and inspect Unreal Groom assets and versioned Groom
  Caches on an explicit GroomComponent, and add a Groom Cache Sequencer track.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: lookdev
    search-hint: "unreal hair groom cache component sequencer vellum"
    tags: "unreal,hair,groom,cache,sequencer,lookdev"
    tools: tools.yaml
---

# Unreal Hair

Use exact object paths to bind and inspect one GroomComponent, then add a
versioned Groom Cache track without replacing the referenced cache asset.

## Scripts

- `bind_groom_cache`
- `get_groom_component_info`
- `add_groom_cache_track`

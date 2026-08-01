---
name: unreal-runtime
description: >-
  Domain skill - control Unreal's Simulation-in-Editor lifecycle for validating
  live physics behavior without exposing arbitrary editor scripting.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: validation
    search-hint: "unreal simulation in editor physics chaos runtime play test"
    tags: "unreal, runtime, simulation, physics, validation"
    tools: tools.yaml
---

# Unreal Runtime

- `start_physics_simulation`
- `stop_physics_simulation`

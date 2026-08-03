---
name: unreal-pcg
description: Refresh generated Unreal PCG output after changing source assets or graph settings.
license: MIT
compatibility: Unreal Engine 5.8+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal PCG refresh rebuild regenerate generated output"
    tags: "unreal, pcg, procedural, regenerate"
    tools: tools.yaml
---

# Unreal PCG

Use `refresh_pcg` after replacing a mesh or material used by a PCG graph. It
operates on live `PCGComponent` instances in the current editor level and
returns the number of components that were rebuilt.

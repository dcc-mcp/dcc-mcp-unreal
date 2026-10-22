---
name: unreal-pcg
description: Inspect PCG capabilities without mutations, or refresh generated Unreal PCG output after source changes.
license: MIT
compatibility: Unreal Python host, Python 3.9+; individual PCG APIs and plugins are detected at runtime
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal PCG capabilities inspect graph grammar spline pathfinding refresh regenerate"
    tags: "unreal, pcg, procedural, capabilities, regenerate"
    tools: tools.yaml
---

# Unreal PCG

Start with `inspect_pcg_capabilities`. It observes fixed Python class/method
names, engine identity and current-process plugin metadata. It does not create
objects, load graphs, generate output, save assets, enable plugins or start a
service. Inspection does not require an open level.

`python_surface_status` describes only the listed names, not complete feature
support. Missing Python names may still have native or official MCP routes.
`execution_verified` remains false; no native authoring operation is tested by
this tool. Unknown plugin metadata stays unknown rather than being guessed from
the engine version. The reported documented versions are reference points, not
minimum-version gates.

Epic's optional MCP bridge is a separate UE 5.8+ route. Use its `status`,
`list_toolsets` and `describe_toolset` operations off the game thread before
calling an actual registered tool. Enabling PCGToolset requires explicit
`prepare_official_mcp(include_pcg_toolset=true)` intent; inspection never enables
it automatically. See [the versioned workflow](../../../../docs/pcg-capability-workflow.md).

Use `refresh_pcg` after replacing a mesh or material used by a PCG graph. It
operates on live `PCGComponent` instances in the current editor level and
returns the number of components for which a generation method was invoked.
This trigger result alone does not verify generation completion or saved output.

# Canvas extension contract

Unreal Canvas represents a pipeline as typed nodes inside an Action-card Graph.
The outer Canvas holds cards, references, frames, and annotations. The graph
owns the input, processing, and output connections.

`prepare_hyper3d_canvas_workflow` returns a provider-neutral contract with:

- a node id and MCP tool name
- typed input and output pins
- explicit connections
- an output destination for Unreal import
- a declaration that the contract is intended for an Action-card Graph

The complete Showcase contract also includes a `canvas.dcc_mcp.call` node and
an `unreal_cinematics__queue_sequence_render` node. The DCC-MCP node exposes
`endpoint`, `skill_name`, `tool_name`, and JSON `arguments` as `source: setting`
inputs. This lets a Canvas author enter a local or approved gateway profile and
select a marketplace-installed skill without embedding credentials in the
Graph. The render node exposes the sequence, output directory, resolution,
format, and temporal samples as manual settings. `canvas.output.showcase`
collects imported assets, the DCC-MCP result, and the render job for the outer
Canvas.

To add another provider, keep the same lifecycle:

1. A submission node returns a task UUID and a task-scoped status key.
2. A status node returns job states and terminal flags.
3. A download node writes a local artifact and returns its path.
4. An Unreal node imports the artifact and returns Content Browser object paths.

Provider API keys belong in environment variables or the Canvas provider
settings. They must never appear in `SKILL.md`, `tools.yaml`, Graph metadata,
logs, or result contexts.

The current repository does not include Epic's Canvas extension SDK or
redistribute the native Canvas plugins. When an installed UE 5.9 build exposes
the Canvas Bridge, the skill detects that native surface and keeps the Graph
handoff contract available through the shared gateway. The same provider
lifecycle remains usable when the native Bridge is unavailable, without
changing the Hyper3D lifecycle, DCC-MCP settings, render settings, or Unreal
import contract.

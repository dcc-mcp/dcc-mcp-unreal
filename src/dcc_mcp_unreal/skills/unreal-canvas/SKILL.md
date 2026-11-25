---
name: unreal-canvas
description: >-
  Unreal Engine 5.9 Canvas integration skill for native Canvas support discovery,
  typed Action-card Graph workflows, and Hyper3D Rodin image-to-3D or text-to-3D generation.
  It exposes DCC-MCP tools that can be used by Unreal Canvas agents and future
  Canvas extensions. It does not claim native Canvas plugin registration when
  the engine build does not provide the Canvas SDK.
license: MIT
compatibility: Unreal Engine 5.7+ for the adapter, Unreal Canvas 5.9 or newer when the native Canvas plugins are installed, Python 3.9+
allowed-tools: Read Bash
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: integration
    stage: generative-pipeline
    search-hint: "unreal canvas graph action card custom node extension toolbox hyper3d rodin image to 3d text to 3d"
    tags: [unreal, canvas, graph, extension, hyper3d, rodin, generative, pipeline]
    tools: tools.yaml
---

# Unreal Canvas 5.9 and Hyper3D

This skill connects the Unreal adapter to the native Unreal Canvas workflow
through typed DCC-MCP tools. Unreal Canvas is the UE 5.9 shared workspace for
references, generated results, notes, agents, toolshelf operations, and
reusable Graph processes. It is separate from the UMG Canvas Panel widget.

## Native Canvas support

Use `inspect_canvas_support` before enabling a Canvas-specific workflow. It
checks the project and engine plugin locations for Unreal Canvas Bridge, Unreal
Canvas Graph, Unreal MCP, All Toolsets, Toolset Registry, Python support, and
Spatial Annotations. It also reports the live runtime plugin names when Unreal
exposes them, the UE 5.9 version gate, native Canvas capabilities, and the
MCP/Action-card fallback.

Before setup, verify that the intended Editor and project own the loopback
listener, confirm the exact configured port, and confirm the effective bind
address is loopback. For a native setup, call
`unreal_official_mcp__prepare_official_mcp` with the verified
`server_port`, `include_all_toolsets=true`, `include_canvas_bridge=true`, and
`include_spatial_annotations=true`. The setup enables project references to
installed Epic plugins and writes autostart settings. It returns
`restart_required` and does not start or restart the server. After an
authorized restart, verify the actual listener and official MCP status before
using the Canvas surface. It does not download the Canvas server, local AI
models, provider credentials, or agent runtime. Complete those steps in the
Unreal Canvas tab as documented by Epic.

When the native Canvas plugins are unavailable, DCC MCP still exposes the
typed Graph contract and the Hyper3D lifecycle through its normal MCP gateway.
The adapter never writes a synthetic Epic plugin descriptor.

## Native UE 5.9 capabilities

The installed Canvas Bridge can provide viewport renders and snapshots,
Beauty, Depth, Normal, and Edges passes, sequence renders, spatial annotation
inputs, mesh and splat imports, cutout actor placement, and typed Action-card
Graphs. The official MCP bridge dynamically discovers the corresponding native
toolsets and preserves their names and schemas.

## Hyper3D workflow

1. Call `prepare_hyper3d_canvas_workflow` to obtain the typed node and pin
   contract for an Action-card Graph.
2. Call `submit_hyper3d_generation` with one to five reference images or a text
   prompt. The API key is read from `HYPER3D_API_KEY`, with `RODIN_API_KEY` as
   a compatibility fallback.
3. Call `get_hyper3d_generation_status` with the returned
   `subscription_key`. The top-level task UUID is kept for downloading.
4. Call `download_hyper3d_result` after all jobs report `Done`.
5. Call `import_hyper3d_asset` inside Unreal to import the downloaded GLB, FBX,
   OBJ, USDZ, or STL result into the Content Browser.
6. Fill the `dcc_mcp_action` settings with a local or approved DCC-MCP endpoint,
   marketplace skill slug, tool name, and JSON arguments. Imported assets are
   available on its `asset_paths` input.
7. Fill the `render_showcase` sequence and output settings to queue a Movie
   Render Queue job. `canvas_output` collects the imported assets, DCC-MCP
   result, and render job for the Showcase.

The API key is never included in tool results. The returned subscription key is
the task-scoped identifier required by Hyper3D's status endpoint and should be
treated as a short-lived job capability.

## Extension points

The `references/canvas-extension.md` file documents the stable local contract
for adding another provider or another typed Canvas node. New providers should
keep the same separation between submission, status, download, and Unreal
import so a Graph can replace one node without changing the rest of the path.

## Scripts

- `inspect_canvas_support`
- `prepare_hyper3d_canvas_workflow`
- `submit_hyper3d_generation`
- `get_hyper3d_generation_status`
- `download_hyper3d_result`
- `import_hyper3d_asset`

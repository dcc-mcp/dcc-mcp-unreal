# Unreal Engine 5.9 integration

Unreal Engine 5.9 adds Unreal Canvas and expands the native Unreal MCP. DCC
MCP Unreal keeps those engine capabilities available through the official
loopback endpoint while adding shared gateway routing, cross-DCC skills,
capability metadata, and the Canvas workflow contract.

## Integration matrix

| UE 5.9 capability | Integration path | Adapter behavior |
| --- | --- | --- |
| Unreal MCP and Toolset Registry | `unreal-official-mcp` | Discovers the installed server dynamically and preserves Epic toolset names and schemas. |
| All Toolsets | `prepare_official_mcp(include_all_toolsets=true)` | Verifies the installed descriptor before adding the project plugin entry. |
| Tool search | `official_mcp_bridge` with `list_toolsets`, `describe_toolset`, `describe_tools`, and `call_tool` | Supports the UE 5.9 discovery meta-tools and does not assume every tool is listed up front. |
| MCP Resources | `official_mcp_bridge` with `list_resources` and `read_resource` | Forwards resources exposed by the engine, including future project context providers. |
| Unreal Canvas Bridge | `unreal-canvas` and `prepare_official_mcp(include_canvas_bridge=true)` | Detects and enables the installed native Canvas hub without shipping Epic binaries. |
| Spatial Annotations | `inspect_canvas_support` and `prepare_official_mcp(include_spatial_annotations=true)` | Reports annotation support and enables the installed plugin when requested. |
| Canvas Graph and Action cards | `prepare_hyper3d_canvas_workflow` | Returns typed nodes, pins, connections, import paths, DCC-MCP actions, and render outputs for a reusable Action-card Graph. |
| Viewport and sequence rendering | Native Canvas Bridge and official MCP toolsets | Remains owned by Epic's Canvas and toolset implementations. The adapter discovers the live schemas. |
| Blueprint, graph, node, variable, StateTree, Chooser, and Dataflow editing | Native UE 5.9 MCP toolsets | Available through the official bridge when the corresponding installed toolset is registered. |
| Semantic Search, Knowledge Base, and MCP Client | Native UE 5.9 MCP toolsets | Available through dynamic toolset discovery. No stale adapter allow-list blocks new toolsets. |
| Python search paths and Python 5.9 API additions | Unreal Python runtime | DCC MCP keeps its own package path bootstrap and leaves Epic's Python search-path settings available to the engine. |

## Native setup

1. Install a UE 5.9 build that contains Unreal Canvas and the official MCP
   plugins.
2. Install and enable `DccMcpUnreal` in the project.
3. Run the following command through the DCC MCP gateway for an authorized
   project configuration change.

   ```powershell
   dcc-mcp-cli call unreal_official_mcp__prepare_official_mcp --json '{"include_all_toolsets":true,"include_canvas_bridge":true,"include_spatial_annotations":true}'
   ```

4. Restart the editor when the tool reports `restart_required=true`.
5. Call `unreal_canvas__inspect_canvas_support` and then verify the official
   endpoint with `unreal_official_mcp__official_mcp_bridge` using
   `operation=status` and the configured loopback endpoint.
6. Open **Tools → Unreal Canvas**, install the Canvas server and optional local
   models, configure providers, and run the Canvas health check.

The adapter does not download the Canvas server, local model files, provider
keys, or external agent runtimes. Epic's Canvas Bridge manages those resources
and its version matching rules.

## Compatibility boundary

The official Unreal MCP server remains experimental and serializes tool calls
on the editor game thread. The DCC bridge runs its HTTP request off the Unreal
game thread and preserves the official endpoint's loopback boundary. DCC MCP
skills continue to work when the optional Epic plugins are absent, so older
engines and Pythonless sidecar deployments retain their existing path.

The release notes also list provider integrations, live AI viewport previews,
and other editor features. Those stay managed by the native UE 5.9 plugins or
the configured provider. The adapter exposes their registered MCP surfaces and
does not duplicate provider credentials or proprietary server packages.

References include the [UE 5.9 release notes](https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-9-release-notes),
[Unreal Canvas overview](https://dev.epicgames.com/documentation/unreal-engine/unreal-canvas-overview-in-unreal-engine),
[Canvas setup](https://dev.epicgames.com/documentation/en-us/unreal-engine/getting-started-with-unreal-canvas-in-unreal-engine),
and [Unreal MCP in Unreal Editor](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor).

---
name: unreal-official-mcp
description: >-
  Enable, discover, and call Unreal Engine 5.8+ built-in Unreal MCP tools
  through the DCC MCP gateway. Use when the user asks to set up, include,
  compare, inspect, or use Epic's official MCP or Toolset Registry
  capabilities. Not a replacement for DCC MCP on Unreal 4.18-5.7.
license: MIT
compatibility: DCC MCP Unreal 0.2+, optional Unreal Engine 5.8+ Unreal MCP plugin
allowed-tools: Read Bash
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.2.0"
    layer: integration
    stage: runtime
    search-hint: "enable setup bootstrap official epic unreal mcp model context protocol toolset registry bridge"
    tags: [unreal, mcp, epic, toolset-registry, compatibility]
    tools: tools.yaml
---

# Unreal Official MCP Bridge

Enable and bridge Epic's optional Unreal MCP into DCC MCP without
redistributing the Epic plugin. The engine plugin must be installed with the
engine; this skill can enable it for the current project and configure its
loopback HTTP endpoint.

## Workflow

1. Call `official_mcp_bridge` with `operation=status`.
2. If status is unavailable on Unreal Engine 5.8+, obtain explicit permission
   to change project configuration, then call `prepare_official_mcp`. Enable
   `NiagaraToolsets` only when the task needs Niagara authoring. Set
   `include_pcg_toolset=true` only for a PCG task; it defaults to false.
3. When `restart_required` is true, restart the editor and verify the DCC MCP
   instance before retrying `operation=status`. Do not claim success from the
   configuration write alone.
4. Use `list_toolsets`, then `describe_toolset`, before calling an unfamiliar
   tool. Preserve Epic's tool names and schemas.
5. Use `call_tool` with the selected toolset and arguments. Do not issue
   overlapping mutating calls; Epic serializes tool invocations on the game
   thread.
6. Fall back to the normal DCC MCP Unreal skills when the official endpoint is
   unavailable or the running engine is older than 5.8.

The bridge accepts loopback HTTP endpoints only. Run it with `affinity:any`;
never block Unreal's game thread while making an HTTP request back into the
same editor process.

## PCG opt-in and safe setup

`prepare_official_mcp` checks actual installed descriptors, not an engine-version
guess. Epic's experimental `PCGToolset` descriptor is at
`Engine/Plugins/Experimental/Toolsets/PCGToolset/PCGToolset.uplugin` and declares
`PCG` as a required dependency. UE 5.8.1 also declares `ToolsetRegistry`, whose
descriptor is at `Engine/Plugins/Experimental/ToolsetRegistry/ToolsetRegistry.uplugin`.
Setup follows the installed dependency declarations, not the version string;
it does not require `ToolsetRegistry` when an older descriptor does not declare it.
Setup parses those declarations and the installed
PCG descriptor at `Engine/Plugins/PCG/PCG.uplugin` (or the legacy
`Engine/Plugins/Experimental/PCG/PCG.uplugin` location). Missing, malformed,
ambiguous, unsupported, or explicitly project-disabled direct dependencies block
setup before any writes. It does not silently override a disabled dependency or
change unrelated project plugins. Newly encountered direct dependencies outside
the supported descriptor paths require manual review rather than an engine scan.

Both the project JSON and existing editor INI are validated before writing.
Setup preserves all existing INI bytes, including comments, repeated sections,
duplicate entries and array commands, appending only a final MCP settings block
when the four scalar settings need updating. Repeating setup makes no further
changes. Writes use atomic replacement; on a write failure, setup attempts to
restore the exact original file bytes or original absence. An incomplete
rollback is reported explicitly with the affected file paths. This is not a
crash-safe transaction across both files; keep normal project backups.

Successful setup means configuration was prepared, not that any plugin loaded
or PCG tool is available. `runtime_verified` remains false. Restart when requested,
then verify the live endpoint and discover its actual toolsets before authoring;
setup never starts a service, loads Unreal, or mutates a PCG graph.

References: [PCGToolset](https://dev.epicgames.com/documentation/unreal-engine/API/PluginIndex/PCGToolset),
[PCG](https://dev.epicgames.com/documentation/unreal-engine/API/PluginIndex/PCG), and
[Unreal plugins](https://dev.epicgames.com/documentation/en-us/unreal-engine/plugins-in-unreal-engine).

## Scripts

- `prepare_official_mcp`
- `official_mcp_bridge`

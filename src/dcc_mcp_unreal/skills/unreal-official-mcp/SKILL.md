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
   `NiagaraToolsets` only when the task needs Niagara authoring.
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

## Scripts

- `prepare_official_mcp`
- `official_mcp_bridge`

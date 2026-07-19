---
name: unreal-official-mcp
description: >-
  Discover and call Unreal Engine 5.8+ built-in Unreal MCP tools through the
  DCC MCP gateway. Use when the user asks to include, compare, inspect, or use
  Epic's official MCP or Toolset Registry capabilities. Not a replacement for
  DCC MCP on Unreal 4.18-5.7.
license: MIT
compatibility: DCC MCP Unreal 0.2+, optional Unreal Engine 5.8+ Unreal MCP plugin
allowed-tools: Read Bash
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: integration
    stage: runtime
    depends: []
    search-hint: "official epic unreal mcp model context protocol toolset registry bridge"
    tags: [unreal, mcp, epic, toolset-registry, compatibility]
    tools: tools.yaml
---

# Unreal Official MCP Bridge

Bridge Epic's optional Unreal MCP into DCC MCP without redistributing the Epic
plugin. The engine plugin must already be installed, enabled, and serving on a
loopback HTTP endpoint.

## Workflow

1. Call `official_mcp_bridge` with `operation=status`.
2. Use `list_toolsets`, then `describe_toolset`, before calling an unfamiliar
   tool. Preserve Epic's tool names and schemas.
3. Use `call_tool` with the selected toolset and arguments. Do not issue
   overlapping mutating calls; Epic serializes tool invocations on the game
   thread.
4. Fall back to the normal DCC MCP Unreal skills when the official endpoint is
   unavailable or the running engine is older than 5.8.

The bridge accepts loopback HTTP endpoints only. Run it with `affinity:any`;
never block Unreal's game thread while making an HTTP request back into the
same editor process.

## Scripts

- `official_mcp_bridge`

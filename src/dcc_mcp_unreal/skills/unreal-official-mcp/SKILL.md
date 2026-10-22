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
HTTP port and path. It does not configure or verify the listener's bind address.

## Workflow

1. Identify the intended DCC MCP instance, isolated project and authorized port.
   Verify ownership and the actual loopback listener before calling
   `official_mcp_bridge` with `operation=status` and its explicit `endpoint`.
2. If status is unavailable on Unreal Engine 5.8+, obtain explicit permission
   to change project configuration, then call `prepare_official_mcp`. Enable
   `NiagaraToolsets` only when the task needs Niagara authoring. Set
   `include_pcg_toolset=true` only for a PCG task; it defaults to false. Pass
   `server_port` for a non-default port; omission retains the 8000 default.
3. When `restart_required` is true, obtain authorization for the isolated
   instance restart after the ownership, port and binding checks below. Verify
   the DCC MCP instance, then retry `operation=status` with the returned
   `configured_endpoint`. Do not claim success from configuration alone.
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

## Explicit ports and verification boundaries

`server_port` must be an integer from 1 through 65535; booleans, strings,
floats, null and port 0 are rejected before writing. Setup never scans for a
free port, chooses a replacement, starts a listener or changes firewall/bind
settings. Each call has independent settings. Changing only the INI still sets
`restart_required=true`; the running server is not reconfigured by this tool.

Setup reads the current process's native startup arguments using Windows
`GetCommandLineW` / `CommandLineToArgvW`, or Linux `/proc/self/cmdline`.
It never substitutes embedded Python's potentially incomplete `sys.argv`.
Unreadable arguments, an unsupported reader (currently including macOS), or
an invalid, repeated or conflicting `-ModelContextProtocolPort=N` block setup.
A single matching override is accepted. This reads process startup arguments,
not later changes to Unreal's command line or its merged runtime config.

`configuration_verified=true` means both project files were read back and
matched their expected bytes. `configured_port` is parsed from that INI readback;
`configured_endpoint` is the corresponding loopback client URL. Neither proves
that saved/user config, command-line overrides or a running server use that
endpoint. The bridge's `endpoint` selects a client destination only; it does not
change any server setting. Pass `configured_endpoint` explicitly on every bridge
operation rather than silently falling back to the default 8000 endpoint.

Before invoking setup or starting/restarting an Editor, independently verify
the isolated project's ownership, intended port availability and effective
`[HTTPServer.Listeners] DefaultBindAddress`. Unknown, denied, non-loopback or
conflicting state is a stop condition, not permission to probe another way,
change a shared project, take over a listener or select another port. A loopback
client URL alone does not prove loopback-only binding. After an authorized
startup, verify the actual listener address/port and owning Editor/project, then
the DCC MCP instance and official `status`/tool schemas. A successful HTTP reply
alone does not identify the owning instance. Setup provides none of these runtime
checks and always returns `runtime_verified=false`.

Epic documents `-ModelContextProtocolPort=N` for UE 5.8 (invalid values can fall
back to settings). An explicitly validated launch override may suit an isolated
temporary instance without changing persistent settings, but is not native
acceptance of this setup parameter. UE 5.8+ support depends on installed plugins;
older adapter build coverage does not qualify official MCP. A normal Editor
with `NullRHI`/`Unattended` remains a host-specific test proposal. Commandlet HTTP
startup does not establish the Slate ticks or DCC MCP/Toolset Registry workflow.

Reference: [Epic Unreal MCP configuration](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor?application_version=5.8).

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
changes. Writes use atomic replacement and readback, including unchanged files.
On a write/readback failure, setup restores original bytes or absence only where
the current bytes still match its own write; detected external edits are left
untouched. An incomplete rollback is reported with the affected paths. These
optimistic checks are not a file lock or a crash-safe transaction across both
files; do not run concurrent configuration writers, and keep project backups.

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

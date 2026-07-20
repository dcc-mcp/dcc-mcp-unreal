# Unreal Engine compatibility contract

DCC MCP Unreal targets Unreal Engine 4.18 and newer through capability
negotiation. Features are gated by installed engine modules instead of assuming
that a current Unreal Python API exists on every version.

| Engine | Integration tier | Contract |
| --- | --- | --- |
| 4.18+ without `PythonScriptPlugin` | Native baseline | The C++ plugin and native automation bridge remain buildable with that engine's required toolchain; Python skills require an external sidecar. |
| Engine with `PythonScriptPlugin` through 5.7 | DCC MCP Python | The DCC MCP server, skill discovery, asset, actor, level, automation, and app-ui integrations are available subject to per-API gates. |
| 5.8+ | DCC MCP plus Epic | All normal DCC MCP capabilities remain available; `unreal-official-mcp` can optionally bridge Epic's installed Unreal MCP and Toolset Registry. |

Epic's `ModelContextProtocol` plugin is experimental and marked `NoRedist`.
The adapter detects and calls an installed loopback endpoint; it does not copy
or redistribute Epic source or binaries. Editor-only MCP dependencies must not
be enabled for packaged game targets.

## Compatibility rules

1. The `.uplugin` reference to `PythonScriptPlugin` remains optional, so older
   engines can load the native module.
2. Every engine API that changed signature is isolated behind compile-time or
   runtime gates. Missing APIs return a structured capability error.
3. Unreal object mutation stays on the game thread. Network calls back into
   Epic Unreal MCP run off the game thread to avoid same-process deadlocks.
4. CI should test the oldest supported engine, the oldest Python-enabled
   engine available to the project, the latest stable 5.x engine, and 5.8's
   optional official-MCP composition path.

The local UE 4.18 audit successfully built the native plugin with Visual Studio
2017 Build Tools and MSVC 14.16. Use `msvc-kit install-into-vs --check` to audit
the registered toolchains before building. See the
[MSVC-Kit guide](msvc-kit-guide.md#unreal-engine-418) for the tested setup.

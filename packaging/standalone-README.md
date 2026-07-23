# DCC MCP Unreal standalone sidecar

This package includes its own Python interpreter and `dcc-mcp-server`. A system
Python installation is not required.

## Windows installation

The recommended installer verifies the release checksums, installs the package
under `%LOCALAPPDATA%\dcc-mcp-unreal\standalone`, and configures
`DCC_MCP_SERVER_EXECUTABLE`:

```powershell
irm https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/scripts/install-standalone.ps1 | iex
```

Restart Unreal Editor after installation. The plugin selects this sidecar
automatically on Unreal Engine 4.x and whenever the PythonScriptPlugin is
unavailable.

## Manual installation

1. Extract the archive to a stable directory.
2. Verify each file against `SHA256SUMS`.
3. Set `DCC_MCP_SERVER_EXECUTABLE` to the absolute path of the bundled
   `dcc-mcp-server` executable.
4. Install the matching `DccMcpUnreal` plugin release in your project or engine.
5. Restart Unreal Editor.

Run `dcc-mcp-unreal --version` from this directory to verify the packaged
launcher. Set `DCC_MCP_UNREAL_RUNTIME=sidecar` to force the standalone runtime,
or `DCC_MCP_UNREAL_RUNTIME=python` only when the engine embeds Python 3.9 or
newer.

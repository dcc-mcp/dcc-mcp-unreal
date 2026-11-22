DCC MCP Unreal - Fab edition

An editor-only Unreal Engine plugin for MCP-compatible AI assistants.
This submission targets Windows x64. The included Python dependency contains
a Windows native extension and is not a macOS or Linux distribution.

INSTALLATION
Install the plugin for a supported engine version through Fab and the Epic
Games Launcher. For a source review package, extract DccMcpUnreal into your
project's Plugins directory. A source installation requires a matching Unreal
C++ toolchain to build the editor module.

Enable DCC MCP Unreal and the engine's Python Editor Script Plugin, then restart
the editor. The embedded MCP server starts during the first editor tick.
Use the DCC MCP menu and the Output Log to inspect the active server address.
The engine-bundled Python is used; a separate system Python is not required.
The dcc-mcp-core Python package and its native extension are included.

CONNECT AN ASSISTANT
Configure an MCP-aware assistant for the active Streamable HTTP MCP address
reported by the plugin. Connection setup and AI-provider access depend on the
assistant you choose. The plugin does not include an AI model or AI API credits.
The optional DCC MCP shared gateway and dcc-mcp-cli can discover and route tools
across multiple DCC applications. They are distributed separately:
https://github.com/dcc-mcp/dcc-mcp-core/releases

USE THE PLUGIN
Inspect actors and assets before making changes. Start with a request to list
the actors in the current level. Select the relevant typed skill before authoring
assets, Blueprints, materials, cinematics, effects or automation tasks.
Tool availability depends on the engine version and enabled engine plugins.
Niagara and other optional engine capabilities require their matching plugins.
Save a copy of your project before allowing an assistant to modify it.

NETWORK AND EXTERNAL SOFTWARE
The embedded server uses a local MCP endpoint. An AI assistant may transmit
project context to the provider configured in that assistant. External asset
services and optional integrations have their own accounts and terms.
The optional native sidecar, gateway, CLI and DCC-CUA runtime are not included
in this Fab submission. Embedded operation does not require the sidecar.
Epic's experimental ModelContextProtocol plugin is not redistributed here.

TROUBLESHOOTING
If tools do not appear, check that Python Editor Script Plugin is enabled,
restart Unreal, and inspect the Output Log for dcc-mcp-unreal bootstrap errors.
If an engine capability is unavailable, enable its engine plugin and use the
documented supported engine version. This is an editor tool, not a shipping
game runtime plugin.

Documentation:
https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/docs/installation.md
Source and releases:
https://github.com/dcc-mcp/dcc-mcp-unreal
Support:
https://github.com/dcc-mcp/dcc-mcp-unreal/issues

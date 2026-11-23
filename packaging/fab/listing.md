# DCC MCP Unreal - AI Editor Tools

## Listing fields

| Field | Value |
| --- | --- |
| Title | DCC MCP Unreal - AI Editor Tools |
| Price | Free |
| Category | Tools & Plugins / Engine Tools |
| Distribution | Unreal Engine code plugin |
| Platform for this submission | Windows x64 |
| Engine for this submission | Unreal Engine 5.8 |
| Version | 0.3.12 |
| Tags | AI, MCP, Editor Utilities, Blueprint, Automation, Cinematics |
| Support | https://github.com/dcc-mcp/dcc-mcp-unreal/issues |
| Documentation | https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/docs/installation.md |

## Short description

Connect MCP-compatible AI assistants to Unreal Editor. Inspect scenes and
assets, author Blueprints and cinematics, and run typed editor workflows through
the open Model Context Protocol.

## Description

Bring your AI assistant into your Unreal Editor workflow.

DCC MCP Unreal connects MCP-compatible assistants such as Claude, Cursor and
Codex to Unreal Editor through a local Streamable HTTP MCP server. Use typed
tools to inspect a project, work with actors and assets, author Blueprints,
materials and cinematics, and validate changes through editor automation.
Client connection details depend on the assistant you use.

**One protocol, a broad editor toolbox.**

Work with actors and components, assets and levels, Blueprint authoring,
materials, Sequencer, Niagara, MetaSound, Chaos, PIE and automation tasks.
Capabilities depend on your engine version and enabled engine plugins. Load
the skills relevant to your task instead of sending an assistant the entire
tool catalog at once.

**Build workflows across your DCC pipeline.**

The optional DCC MCP gateway and CLI can discover multiple application
instances and route tools through the shared DCC MCP ecosystem. These
companions are distributed separately. You can also connect a compatible
assistant directly to the plugin's reported MCP address.

**Extend it with your own tools.**

Add skills using the documented `SKILL.md`, `tools.yaml` and Python script
contract. Tool metadata describes input schemas and execution requirements.
On compatible UE 5.8 installations, the optional Epic MCP bridge can use
Epic's installed toolsets. Epic's experimental plugin is not included.

**Free and open source.**

The project source is available on GitHub under the Apache-2.0 license. See the repository LICENSE, NOTICE, and TRADEMARKS.md files. The plugin
does not include an AI model or AI service credits. AI-provider access and
external service costs depend on the tools you choose.

**Getting started**

1. Install the plugin for your Unreal Engine version.
2. Enable DCC MCP Unreal and the engine's Python Editor Script Plugin.
3. Restart the editor and inspect the DCC MCP menu or Output Log for the
   server address.
4. Configure your MCP-compatible assistant and start by inspecting the actors
   in the current level.

Documentation: https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/docs/installation.md

Source and releases: https://github.com/dcc-mcp/dcc-mcp-unreal

Support: https://github.com/dcc-mcp/dcc-mcp-unreal/issues

## Technical information

- Module: `DccMcpUnreal`, Editor, PostEngineInit.
- Supported development platform for this submission: Windows x64.
- Engine version validated for the Fab layout: UE 5.8.1, including a local
  Unreal AutomationTool BuildPlugin pass.
- Shipping game runtime: not supported by this editor-only submission.
- Required engine plugin: Python Editor Script Plugin, enabled by the plugin
  descriptor. The engine-bundled Python is used.
- Included dependency: `dcc-mcp-core` 0.20.52, with its Windows native Python
  extension. License notices and dependency source links are included.
- Optional engine plugins: Niagara and any other engine plugins required by
  the specific editor workflow you invoke.
- Optional external companions: DCC MCP gateway, CLI, native sidecar and
  DCC-CUA. They are not included in this Fab package; embedded MCP operation
  does not require a separate sidecar.
- The server runs locally. Your assistant's configured AI provider can receive
  project context; external integrations have their own accounts and terms.
- Additional setup and troubleshooting are in `Documentation/README.txt`.

## Submission notes

This source plugin preserves the native module from the v0.3.12 release and
repackages Python into Fab's required locations. It excludes precompiled
editor DLLs, build intermediates, standalone launcher executables, local build
paths and nested plugin copies. The Python bootstrap supports both the
existing GitHub release layout and the Fab layout.

The upstream v0.3.12 release also has builds for other engines. This submission
claims only the engine and platform validated for this Fab package.

AI disclosure fields must be answered truthfully in the publisher portal.
The existing plugin artwork has documented AI-generation provenance in
`docs/assets/UNREAL_PLUGIN_ICON_SOURCES.md`; this listing's code and copy were
prepared with AI assistance.

## Fab requirements

- [Publishing workflow](https://dev.epicgames.com/documentation/en-us/fab/publishing-assets-for-sale-or-free-download-in-fab)
- [Plugin layout, Python locations and media requirements](https://dev.epicgames.com/documentation/fab/asset-file-format-and-structure-requirements-in-fab?lang=en-US)

Gallery exports use the existing approved repository artwork. They must be at
least 1920 by 1080 pixels and each remain under 3 MB.

---
name: unreal-build-package
description: >-
  Build installable DCC MCP Unreal plugin archives and package Unreal projects
  as Windows executables. Use for long-running compilation, cooking, staging,
  and packaging tasks. Do not use for Automation Test execution or asset export.
license: MIT
compatibility: Windows, Unreal Engine 4.18+, Python 3.7+
allowed-tools: Read Bash
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: runtime
    search-hint: "unreal build compile package exe executable cook stage plugin zip RunUAT BuildCookRun BuildPlugin"
    tags: [unreal, pipeline, build, packaging, executable]
    tools: tools.yaml
---

# Unreal Build and Package

Run bounded, asynchronous Unreal build workflows and return their artifacts and
log paths. Both tools execute off the Unreal game thread and support cooperative
cancellation while waiting for the external build process.

## Workflow

1. Use `build_plugin_package` for this repository's installable
   `DccMcpUnreal` ZIP. Pass a source checkout and an Unreal Engine root.
2. Use `package_project_executable` for a saved `.uproject`. Configure maps,
   default game mode, and packaging settings in the project before calling it.
3. Poll the returned DCC MCP job until it completes, then inspect `artifacts`
   and `log_path`. A queued job is not proof that an executable was produced.

The project packaging tool targets Windows `Win64` and uses Unreal's
`BuildCookRun` with build, cook, stage, pak, and archive enabled. It does not
publish, upload, sign, or install the result.

## Scripts

- `build_plugin_package`
- `package_project_executable`


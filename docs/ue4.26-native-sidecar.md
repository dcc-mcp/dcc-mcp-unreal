# UE4.26 native sidecar compatibility

## Overview

`dcc-mcp-unreal` provides a validated Unreal Engine 4.26 native sidecar
baseline. It is not a feature-equivalent port of the complete UE5 Python tool
surface.

UE4.26 embeds Python 3.7, while this project and `dcc-mcp-core` require
Python 3.9 or newer. The UE4.26 runtime therefore uses:

1. a C++ bridge inside Unreal Editor;
2. the self-contained `dcc-mcp-unreal` launcher and native sidecar;
3. a read-only discovery endpoint bundled with the launcher;
4. the shared gateway at `http://127.0.0.1:9765/mcp`;
5. main-thread execution through the C++ bridge.

The discovery endpoint publishes the Unreal actions implemented by the C++
bridge, so gateway clients can search and describe them before dispatch.

## Installation

1. Extract `DccMcpUnreal-<version>-ue4.26-win64.zip` to:

   ```text
   <UE426Project>\Plugins\DccMcpUnreal
   ```

2. Extract the Windows standalone archive to a stable directory.

3. Point the plugin at the standalone launcher:

   ```powershell
   $env:DCC_MCP_SERVER_EXECUTABLE =
     "C:\Tools\dcc-mcp-unreal\dcc-mcp-unreal.exe"
   ```

4. Start Unreal Editor. `auto` runtime selection chooses the native sidecar
   on UE4. To force the same path while diagnosing startup:

   ```powershell
   $env:DCC_MCP_UNREAL_RUNTIME = "sidecar"
   ```

5. Connect the MCP client to:

   ```text
   http://127.0.0.1:9765/mcp
   ```

## Native UE4 baseline tool surface

| Domain | MCP tool | Type |
|---|---|---|
| Actor | `unreal_actors__list_actors` | Read |
| Actor | `unreal_actors__spawn_actor` | Write |
| Actor | `unreal_actors__delete_actor` | Destructive write |
| Actor | `unreal_actors__get_actor_transform` | Read |
| Actor | `unreal_actors__set_actor_transform` | Write |
| Level | `unreal_level__get_level_info` | Read |
| Level | `unreal_level__save_level` | Write |
| Asset | `unreal_assets__list_assets` | Read |
| Blueprint | `unreal_assets__create_blueprint` | Write |
| Blueprint | `unreal_blueprints__create_blueprint_class` | Write |
| Blueprint | `unreal_blueprints__add_component_to_blueprint` | Write |
| Blueprint | `unreal_blueprints__compile_blueprint` | Write |

This native baseline does not expose material graphs, PBR texture assembly,
arbitrary Unreal Python, Fab, or UE5-only official MCP toolsets. Add those
workflows to the C++ bridge only after validating the required UE4 project
use case.

The validation below is engine-level and uses an isolated test project.
Production projects must still run their own startup, plugin-conflict, and
project-content smoke tests before adopting the package.

## Validation

The compatibility path was validated against a UE4.26.2 source engine with
the following gates:

- UAT `BuildPlugin`: successful Win64 Development build;
- post-install import checks: passed;
- UE Automation `DccMcp.Smoke.NativeBridge`: 1 passed, 0 failed;
- standalone launcher startup and bundled server help: passed.

The commandlet emitted optional-platform and unavailable shared-cache
warnings, but no plugin or native bridge error.

## Build and smoke test

Build with a UE4.26 source or installed engine:

```powershell
python packaging\build_distributable.py `
  --ue-root "<UE426_ENGINE_ROOT>" `
  --mode native
```

Run the native automation smoke:

```powershell
$env:DCC_MCP_SERVER_EXECUTABLE =
  "<StandaloneRoot>\dcc-mcp-unreal.exe"

.\scripts\run_ue_smoke.ps1 `
  -Project "<TestProject>\TestProject.uproject" `
  -UERoot "<UE426_ENGINE_ROOT>" `
  -Mode native
```

The expected `Saved\Automation\Reports\index.json` summary is:

```text
succeeded = 1
failed = 0
```

For UE4 source engines, the packager allows UAT to compile AutomationTool.
Installed UE4 engines with precompiled AutomationTool continue to use
`-nocompile`. Native UE4 packages omit embedded Python dependencies because
the sidecar supplies the Python runtime.

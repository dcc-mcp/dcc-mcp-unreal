# Installation Guide

Choose the path that matches your Unreal Engine version and workflow.

## Quick Install

```bash
# Inside Unreal's bundled Python — one command per engine version
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal
```

The plugin auto-detects the running engine and activates the correct capability
tier. Engines whose bundled Python is older than 3.9 use the self-contained
standalone sidecar below.

---

## UE Version Matrix

| UE Version | Install Mode | Required Python | Notes |
|---|---|---|---|
| **4.18 – 4.26** | C++ plugin + standalone sidecar | No system Python required | Internal Python 3.9+ builds may select embedded mode |
| **4.27** | C++ plugin + standalone sidecar | No system Python required | Stock Python 3.7 is unsupported; internal Python 3.9+ builds may select embedded mode |
| **5.0 – 5.2** | C++ plugin + `PythonScriptPlugin` | Engine-bundled Python 3.9 | Full DCC MCP skill catalog |
| **5.3 – 5.6** | C++ plugin + `PythonScriptPlugin` | Engine-bundled Python 3.11 | Full DCC MCP skill catalog |
| **5.7+** | C++ plugin + `PythonScriptPlugin` + optional Epic MCP bridge | Engine-bundled Python 3.12 | DCC MCP tools + optional Epic MCP bridge where available |

### Per-Tier Detail

**UE 4.18 (native baseline)**
The C++ plugin builds with Visual Studio 2017 Build Tools and MSVC 14.16.
Python skills use the self-contained standalone sidecar outside the editor. See the
[MSVC-Kit guide](msvc-kit-guide.md#unreal-engine-418) for the tested
toolchain.

**UE 5.0+ (Python-enabled)**
Full DCC MCP server inside the editor. Install `dcc-mcp-unreal` into the
engine's bundled Python, enable `PythonScriptPlugin`, and the server runs
in-process. The C++ plugin handles subprocess lifecycle and main-thread
dispatch.

**UE 5.8+ (Epic MCP bridge)**
All DCC MCP capabilities remain available. The `unreal-official-mcp` skill
can optionally bridge Epic's installed `ModelContextProtocol` plugin —
discover and call Epic tools through the same MCP endpoint without
redistribution. Keep the Epic plugin installed with the engine; the adapter
detects and calls its loopback endpoint only.

---

## Pip Install (per Engine Version)

Each Unreal Engine ships a self-contained Python interpreter. Install
directly into it with one command. Replace the engine path to match your
installed version.

### UE 5.5 / 5.4 / 5.3 (Python 3.11)

```bash
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal
```

For engine versions with `python.exe` missing from the ThirdParty directory,
first enable the **Python Editor Script Plugin** (Edit → Plugins → search
"Python"), restart the editor, then use the editor's own Python:

```bash
"C:\Program Files\Epic Games\UE_5.4\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
    "C:\Path\To\YourProject.uproject" -run=pythonscript -script="path\to\install.py" -stdout -unattended -nosplash
```

### UE 5.2 / 5.1 / 5.0 (Python 3.9)

```bash
"C:\Program Files\Epic Games\UE_5.2\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal
```

### UE 4.x

Stock Python 2.7/3.7 builds use the standalone sidecar installer below.
Internal engine builds with Python 3.9 or newer may install the Python package
and set `DCC_MCP_UNREAL_RUNTIME=python` to use embedded mode. UE4 defaults to
sidecar even when an older `PythonScriptPlugin` is loaded.

### Development Install

```bash
git clone https://github.com/dcc-mcp/dcc-mcp-unreal
cd dcc-mcp-unreal
pip install -e ".[dev]"
```

---

## Uplugin Deployment

Download a pre-built plugin ZIP from GitHub Releases and copy it into your
project or engine installation.

### From GitHub Releases

1. Go to the [Releases page](https://github.com/dcc-mcp/dcc-mcp-unreal/releases)
2. Download the ZIP matching your engine: `DccMcpUnreal-0.2.0-ue5.7.zip`,
   `DccMcpUnreal-0.2.0-ue5.8.zip`, or `DccMcpUnreal-0.2.0-ue4.18.zip`
3. Extract into your project or engine:

**Project plugin** (recommended — keeps the engine clean):
```
MyProject/
├── MyProject.uproject
└── Plugins/
    └── DccMcpUnreal/       ← extract here
        ├── DccMcpUnreal.uplugin
        ├── Content/
        ├── python/
        └── ...
```

**Engine plugin** (shared across all projects on this engine):
```
C:\Program Files\Epic Games\UE_5.7\Engine\Plugins\DccMcpUnreal\
```

4. Open your project in Unreal Editor
5. **Edit → Plugins → search "DCC MCP Unreal"** → enable the plugin
6. Restart the editor

### Build from Source

```bash
# Clone and build the plugin package
git clone https://github.com/dcc-mcp/dcc-mcp-unreal
cd dcc-mcp-unreal
pip install -e ".[dev]"

# Build for your engine (adjust UE_ROOT)
set UE_ROOT=C:\Program Files\Epic Games\UE_5.7
vx just package             # builds to dist/DccMcpUnreal/
vx just package-zip         # builds + creates ZIP archive

# Deploy directly into a project
vx just deploy "C:\Path\To\MyProject"
```

CI builds the uplugin for UE 5.7, UE 5.8, and UE 4.18 automatically on
every release. The UE 4.18 artifact is Python-only (no native module
compiled).

---

## Enable the Python Plugin

For UE 4.27+:

1. Open your Unreal Engine project
2. **Edit → Plugins → search "Python"**
3. Enable **"Python Editor Script Plugin"**
4. Restart the editor

The `PythonScriptPlugin` dependency in `DccMcpUnreal.uplugin` is marked
`Optional: true` — the native plugin loads on older engines even when
the Python plugin is absent.

---

## Verification

### Standalone sidecar (no system Python)

For Windows machines without Python, an agent should run the repository's
PowerShell installer. It downloads only from the official GitHub repository,
verifies every file listed in `SHA256SUMS`, smoke-tests the bundled interpreter,
and persists `DCC_MCP_SERVER_EXECUTABLE` for the current user:

```powershell
irm https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/scripts/install-standalone.ps1 | iex
```

Install a specific release by downloading the script first:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/scripts/install-standalone.ps1 -OutFile install-standalone.ps1
.\install-standalone.ps1 -Version v0.2.0
```

The default install directory is
`%LOCALAPPDATA%\dcc-mcp-unreal\standalone`. Restart Unreal after installation
so it inherits the persisted environment variable. The archive contains its
own PyOxidizer interpreter and native `dcc-mcp-server`; neither `python` nor
`pip` is required on the target machine.

### Smoke Test (Quick)

Open Unreal Editor's **Output Log → Python** console and run:

```python
import dcc_mcp_unreal
handle = dcc_mcp_unreal.start_server()
print(handle.mcp_url())   # e.g. http://127.0.0.1:9876/mcp
```

Connect any MCP client to the printed URL. The server auto-selects a free
OS-assigned port.

### Native Automation Test (CI-grade)

```bash
# Run inside the editor with UnrealEditor-Cmd.exe
vx just ue-smoke "C:\Path\To\YourProject"
```

Runs the native Unreal Automation Test `DccMcp.Smoke.ServerStarts`, verifies
HTTP readiness, and confirms the built-in tools are registered. Reports are
written to `Saved/Automation/Reports`.

### CLI Discovery

If `dcc-mcp-cli` is installed:

```bash
dcc-mcp-cli list              # list live DCC sessions (should show Unreal)
dcc-mcp-cli dcc-types         # list supported DCC types in the release catalog
```

The stable gateway is at `http://127.0.0.1:9765/mcp`. The CLI resolves it
automatically; pass the direct instance URL if you need to bypass the
gateway.

### pip Install Verification

```bash
# From the engine's Python, confirm the package imports cleanly
"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -c "import dcc_mcp_unreal; print(dcc_mcp_unreal.__version__)"
```

Expected output: `0.2.0` (or the installed version).

---

## Agent-Oriented Installation

When an AI agent needs to install `dcc-mcp-unreal` programmatically, use
the single-command paths below. These assume the standard engine install
location; adjust the path if your engine is elsewhere.

### Agent Quick Path

```bash
# Detect and install into the newest UE engine on the machine
for /D %e in ("C:\Program Files\Epic Games\UE_*") do if exist "%e\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" "%e\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal
```

**PowerShell equivalent:**

```powershell
Get-ChildItem "C:\Program Files\Epic Games\UE_*" -Directory |
    ForEach-Object { $py = Join-Path $_.FullName "Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
                     if (Test-Path $py) { & $py -m pip install dcc-mcp-unreal } }
```

### Verifying Dependencies

```bash
"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip show dcc-mcp-unreal
```

Expected output includes:
```
Name: dcc-mcp-unreal
Version: 0.2.0
Requires: dcc-mcp-core>=0.19.45,<1.0.0
```

### Required Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DCC_MCP_UNREAL_SKILL_PATHS` | built-in skills only | Semicolon-delimited paths to custom skill directories |
| `DCC_MCP_UNREAL_PORT` | OS-assigned (`0`) | Override the MCP instance port |
| `DCC_MCP_UNREAL_SERVER_NAME` | `unreal-mcp` | Server display name |
| `DCC_MCP_SERVER_EXECUTABLE` | auto-discovered | Override path to `dcc-mcp-server` binary |
| `DCC_MCP_UNREAL_RUNTIME` | `auto` | Select `auto`, `python`, or `sidecar`; auto prefers an active `PythonScriptPlugin` |
| `DCC_MCP_UNREAL_PYTHON_PLUGIN` | `PythonScriptPlugin` | Python plugin dependency name in `.uplugin` |
| `UE_ROOT` | `C:\Program Files\Epic Games\UE_5.2` | Engine root (for `vx just package`) |
| `DCC_MCP_CORE_SPEC` | `dcc-mcp-core>=0.18.7,<1.0.0` | Core version spec (for plugin builds) |

Set environment variables before the editor starts. Example:

```bash
set DCC_MCP_UNREAL_SKILL_PATHS=C:\studio\skills;C:\shared\pipeline\skills
set DCC_MCP_UNREAL_PORT=9000
```

Then start Unreal Editor — the server picks up these values on module init.

---

## Distribution Channels

| Channel | What You Get | Best For |
|---|---|---|
| **PyPI** | `dcc-mcp-unreal` wheel (pure Python + entry points) | pip install into any Python environment |
| **GitHub Releases** | `.whl` + `.zip` archives per engine version | Manual deployment, air-gapped setups |
| **GitHub Actions CI** | `python-dist` artifact (wheel+sdist), `DccMcpUnreal-*-ue*.zip` artifacts | CI/CD pipeline integration |
| **Source** | `git clone` + `pip install -e .` | Development and customization |

---

## Troubleshooting

### `pip install` can't find the engine's `python.exe`

Some UE versions don't ship a standalone `python.exe` in the ThirdParty
directory by default. Enable the Python Editor Script Plugin inside Unreal
Editor first, restart, then the engine registers the Python environment.

### Plugin doesn't appear in the Plugins list

- Confirm the `Plugins/DccMcpUnreal/` directory is directly under your
  project root (not nested one level deeper).
- The `.uplugin` file must be at `Plugins/DccMcpUnreal/DccMcpUnreal.uplugin`.
- Regenerate the project files: right-click the `.uproject` in Explorer →
  "Generate Visual Studio project files" (or run `UnrealVersionSelector.exe`).

### MCP server starts but CLI can't discover it

- Ensure `dcc-mcp-cli` is installed and up-to-date:
  ```bash
  dcc-mcp-cli update check
  dcc-mcp-cli update apply
  ```
- Check the stable gateway port: `curl http://127.0.0.1:9765/mcp`
- If the gateway is down, connect directly to the instance URL printed
  by `handle.mcp_url()`.

### C++ compilation errors (FTicker, etc.)

UE 5.7+ deprecated older APIs. Make sure you are using the plugin version
built for your engine. The `build-uplugin` CI builds per-engine artifacts;
do not cross-deploy a UE 5.2 uplugin into UE 5.7.

### Python `dcc-mcp-core` version mismatch

`dcc-mcp-unreal` pins `dcc-mcp-core>=0.19.45,<1.0.0`. If a newer core
broke compatibility, pin the known-good version:

```bash
"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install "dcc-mcp-core>=0.19.45,<0.20.0"
```

### Engine Python pip TLS / SSL errors

Older engine Python builds may have outdated `certifi`. Upgrade pip and
certifi before the main install:

```bash
"C:\Program Files\Epic Games\UE_5.2\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install --upgrade pip certifi
```

## Next Steps

- Read the [Unreal version compatibility contract](unreal-version-compatibility.md)
  for capability gating details
- Follow the [README Quick Start](../README.md#quick-start) to start the
  server and connect an agent
- Browse [built-in skills](../src/dcc_mcp_unreal/skills/) to see available
  MCP tools
- Read the [MSVC-Kit guide](msvc-kit-guide.md) if you need to build the
  C++ plugin from source for UE 4.18

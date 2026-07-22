# dcc-mcp-unreal

<p align="center">
  <img src="docs/assets/dcc-mcp-unreal.svg" alt="DCC-MCP · UNREAL" width="600">
</p>

## Agent workflow

AI agents should use the shared gateway through `dcc-mcp-cli`; IDE users may
continue to use the MCP endpoint. Prefer typed skills and tools over raw scripts.

### Install or update the CLI

`dcc-mcp-cli` is the preferred control path for every shell-capable agent. If
it is missing, ask the user before installing the latest official release:

```bash
# Linux/macOS
curl -fsSL https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-core/main/scripts/install-cli.sh | sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-core/main/scripts/install-cli.ps1 | iex"
```

Keep an official build current through the release manifest:

```bash
dcc-mcp-cli update check
dcc-mcp-cli update apply
```

`update apply` downloads and stages the latest CLI for the next launch. It
does not update a running `dcc-mcp-server`; update that server in its own
environment.

```bash
dcc-mcp-cli dcc-types
dcc-mcp-cli list
dcc-mcp-cli search --query "<task>" --dcc-type unreal
dcc-mcp-cli describe <tool-slug>
dcc-mcp-cli call <tool-slug> --json '{"key":"value"}'
```

`dcc-types` reports release-catalog support; `list` reports live sessions. If a
tool belongs to an inactive progressive skill, call `dcc-mcp-cli load-skill <skill-name> --dcc-type unreal` before retrying. For post-task improvement,
attach a stable session id with `--meta-json`, query `dcc-mcp-cli stats --range 24h --session-id <task-id>`, then pass the bounded evidence to the
`review_skill_improvement` prompt from `dcc-mcp-skills-creator`.


> **Status**: Pre-Alpha — placeholder / scaffold. Core skill authoring API is
> functional; full Unreal Engine integration requires iterative testing inside UE5.

<!-- Badges -->
[![PyPI](https://img.shields.io/pypi/v/dcc-mcp-unreal)](https://pypi.org/project/dcc-mcp-unreal/)
[![Python](https://img.shields.io/pypi/pyversions/dcc-mcp-unreal)](https://pypi.org/project/dcc-mcp-unreal/)
[![License](https://img.shields.io/github/license/dcc-mcp/dcc-mcp-unreal)](LICENSE)

Unreal Engine plugin for the **DCC Model Context Protocol (MCP)** ecosystem.
Embeds a standards-compliant MCP Streamable HTTP server (2025-03-26 spec)
directly inside Unreal Engine using the current
[dcc-mcp-core](https://github.com/dcc-mcp/dcc-mcp-core).

MCP-compatible agents (Claude Desktop, Cursor, OpenClaw, …) can call Unreal
Editor operations as **tools** — list actors, spawn blueprints, batch-process
assets, run Python scripts — all through a single HTTP endpoint.

---

## Overview

`dcc-mcp-unreal` follows the same architecture as
[dcc-mcp-maya](https://github.com/dcc-mcp/dcc-mcp-maya):

```
Agent (Claude / Cursor)
    │  MCP tools/call  (HTTP POST /mcp)
    ▼
UnrealMcpServer  ←  dcc-mcp-core DccServerBase  ←  SkillCatalog
    │
    ▼  in-process HostExecutionBridge
Python skill scripts  →  Unreal main-thread dispatcher  →  Unreal Editor API
```

Each skill script is a standalone Python file that uses Unreal Engine's
`unreal` Python module. Scripts are discovered from `SKILL.md` plus sibling
`tools.yaml` metadata and exposed as MCP tools automatically.

---

## Features

- **Skills-First workflow** — drop a `SKILL.md` + `scripts/` directory anywhere
  and it becomes MCP tools automatically
- **Zero boilerplate** — use `@skill_entry`, `unreal_success()`, `unreal_error()`
  helpers identical in spirit to `dcc-mcp-maya`'s `@with_maya`, `maya_success()`
- **Hot-reload** — `SkillWatcher` detects `SKILL.md` changes without restart
  (future iteration)
- **Thread-safe singleton** — `start_server()` / `stop_server()` module helpers
  for easy use from Unreal's Python console
- **Collision-free instances** — the OS assigns a free MCP instance port by default
- **Built-in actor skill** — `unreal-actors` ships out of the box (list, spawn,
  delete, transform actors)

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Unreal Engine | 4.18+ (capability-gated) |
| Unreal Python Editor Script Plugin | optional; required for in-editor Python skills |
| Python (embedded in UE) | version supplied by the installed engine |
| dcc-mcp-core | >= 0.19.45, < 1.0.0 |

See the [Unreal version compatibility contract](docs/unreal-version-compatibility.md)
for native-only, Python-enabled, and UE 5.8 official-MCP integration tiers.

### Enable the Python Plugin

1. Open your Unreal Engine project
2. **Edit → Plugins → search "Python"**
3. Enable **"Python Editor Script Plugin"**
4. Restart the editor

---

## Installation

📖 **[Full installation guide](docs/installation.md)** — covers pip install,
uplugin deployment, GitHub Releases, UE 4.18–5.8+ matrix, agent-oriented
paths, environment variables, and troubleshooting.

### Quick Install

No system Python (Windows native sidecar):

```powershell
irm https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/scripts/install-standalone.ps1 | iex
```

For Python-enabled engines, pick the one-liner for your engine version:

```bash
# UE 5.5 / 5.4 / 5.3 (Python 3.11)
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal

# UE 5.2 / 5.1 (Python 3.9)
"C:\Program Files\Epic Games\UE_5.2\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal

# UE 5.0 / 4.27 (Python 3.9 / 3.7)
"C:\Program Files\Epic Games\UE_5.0\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -m pip install dcc-mcp-unreal

# UE 4.18 (external sidecar)
pip install dcc-mcp-unreal
```

Enable the **Python Editor Script Plugin** in Unreal Editor (**Edit → Plugins → "Python"**), restart, and you're ready.

### Uplugin (from GitHub Releases)

Download `DccMcpUnreal-0.2.0-ue5.7.zip` from [Releases](https://github.com/dcc-mcp/dcc-mcp-unreal/releases), extract into `<project>/Plugins/DccMcpUnreal/`, enable in Editor.

### Development Install

```bash
git clone https://github.com/dcc-mcp/dcc-mcp-unreal
cd dcc-mcp-unreal
pip install -e ".[dev]"
```

### Build Plugin Package

```bash
set UE_ROOT=C:\Program Files\Epic Games\UE_5.7
vx just package          # Output: dist/DccMcpUnreal/
vx just deploy "C:\Path\To\MyUnrealProject"
```

See the [installation guide](docs/installation.md) for build-from-source,
UE version matrix, and agent-oriented automation paths.

---

## Quick Start

Open Unreal Engine's **Output Log** → **Python** console (or use the Python
Script Plugin terminal):

```python
import dcc_mcp_unreal

# Start on an OS-assigned instance port
handle = dcc_mcp_unreal.start_server()
print(handle.mcp_url())

# Connect your MCP agent to the URL above.
# When done:
handle.shutdown()
```

Agents normally connect to the stable gateway at `http://127.0.0.1:9765/mcp`.
Use `dcc-mcp-cli list` when a direct instance URL is needed.

### Available tools (built-in)

| Tool name | Description |
|-----------|-------------|
| `unreal_actors__list_actors` | List all actors in the current level |
| `unreal_actors__spawn_actor` | Spawn an actor by class at a world position |
| `unreal_automation__mcp_self_check` | Validate the active MCP server without restarting it |
| `unreal_automation__list_automation_tests` | List native Unreal Automation tests |
| `unreal_automation__queue_automation_tests` | Queue native Unreal Automation tests from MCP |
| `unreal_fab_assets__prepare_free_asset_acquisition` | Prepare a license- and visual-gated Fab acquisition plan for the official UI workflow |
| `unreal_official_mcp__official_mcp` | Discover and call an installed UE 5.8+ Epic MCP endpoint without redistributing it |

---

## Skill Authoring Guide

Skills are directories containing a `SKILL.md` metadata file and a `scripts/`
subdirectory with Python files.

### Directory layout

```
my-unreal-skill/
├── SKILL.md
└── scripts/
    ├── my_tool.py
    └── another_tool.py
```

### SKILL.md format

```yaml
---
name: my-unreal-skill
description: "What this skill does"
license: "MIT"
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: unreal
    version: "1.0.0"
    layer: domain
    tags: "unreal, my-tag"
    tools: tools.yaml
---
```

Declare MCP tools in a sibling `tools.yaml`:

```yaml
tools:
  - name: my_tool
    description: Do something in the Unreal Editor.
    source_file: scripts/my_tool.py
    execution: sync
    affinity: main
    enforce_thread_affinity: false
    read_only: false
    destructive: false
    idempotent: false
    input_schema:
      type: object
      properties:
        param:
          type: string
```

### Script pattern (recommended)

```python
"""Short description of what this script does."""
from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success


@skill_entry
def my_tool(param: str = "default", **kwargs) -> dict:
    """Do something in Unreal Engine.

    Args:
        param: Description of param.
    """
    import unreal  # imported inside — @skill_entry catches ImportError automatically

    # ... do work using unreal module ...
    result_value = f"processed {param}"

    return skill_success(
        f"Completed: {result_value}",
        prompt="Verify the result in the Unreal Editor viewport.",
        result=result_value,
    )


def main(**kwargs) -> dict:
    """Entry point; delegates to my_tool."""
    return my_tool(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)
```

### Error handling

```python
from dcc_mcp_unreal.api import unreal_success, unreal_error, unreal_from_exception

def risky_operation(asset_path: str = "/Game/MyAsset", **kwargs) -> dict:
    try:
        import unreal
        asset = unreal.load_asset(asset_path)
        if asset is None:
            return unreal_error(
                f"Asset not found: {asset_path}",
                f"unreal.load_asset returned None for '{asset_path}'",
                prompt="Check the asset path in the Content Browser.",
                possible_solutions=[
                    "Verify the asset exists at the given path",
                    "Use the Content Browser to find the correct path",
                ],
            )
        # ... process asset ...
        return unreal_success("Asset processed", asset_path=asset_path)
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to process {asset_path}")
```

### Loading custom skills

```python
import dcc_mcp_unreal

handle = dcc_mcp_unreal.start_server(
    extra_skill_paths=["/my/studio/unreal-skills", "/shared/pipeline/skills"],
)
```

Or use the environment variable:

```bash
set DCC_MCP_UNREAL_SKILL_PATHS=C:\my\studio\unreal-skills;C:\shared\skills
```

---

## Architecture Overview

```
dcc-mcp-unreal
├── src/dcc_mcp_unreal/
│   ├── __init__.py          ← Public API: start_server, stop_server, helpers
│   ├── server.py            ← DccServerBase adapter, dispatcher, start/stop
│   ├── api.py               ← unreal_success/error/from_exception, with_unreal
│   └── skills/              ← Built-in skill packages
│       └── unreal-actors/
│           ├── SKILL.md
│           ├── tools.yaml
│           └── scripts/
│               ├── list_actors.py
│               └── spawn_actor.py
└── tests/
    └── test_server.py       ← Unit tests (no real UE required)
```

### Layered architecture

```
dcc-mcp-unreal          (this package)
    └── dcc-mcp-core    (Rust core: HTTP server, skill discovery, dispatch)
            └── unreal  (Unreal Engine Python API — only available inside UE)
```

`dcc-mcp-core` handles all MCP protocol plumbing. `dcc-mcp-unreal` only
provides:
1. Unreal-specific path resolution for the skills directory
2. Unreal main-thread dispatch for in-process skill execution
3. Convenience helpers (`unreal_success`, `@with_unreal`, etc.)
4. Built-in skills for common Unreal operations

---

## Roadmap

### v0.1.0 — Scaffold (current)
- [x] Project structure mirroring `dcc-mcp-maya`
- [x] `unreal_success` / `unreal_error` / `unreal_from_exception` helpers
- [x] `@with_unreal` decorator
- [x] `UnrealMcpServer` adapter built on `DccServerBase`
- [x] `unreal-actors` skill (list, spawn)
- [x] Unit tests (no real UE required)

### v0.2.0 — Core skills
- [ ] `unreal-assets` — Content Browser operations (import, export, list)
- [ ] `unreal-materials` — Material instance management
- [ ] `unreal-blueprints` — Blueprint variable get/set
- [ ] `unreal-level` — Level streaming, world settings
- [ ] `unreal-rendering` — Movie Render Queue integration

### v0.3.0 — Editor integration
- [ ] Unreal Editor toolbar button to start/stop MCP server
- [ ] UE5 plugin wrapper (`.uplugin`) for one-click installation
- [ ] Auto-start on editor startup via `EditorStartupScript`
- [ ] Level Sequence / Sequencer tools

### v1.0.0 — Production ready
- [ ] Full test suite with `unreal` mock
- [ ] CI via GitHub Actions (headless UE testing)
- [ ] PyPI release
- [ ] Comprehensive documentation

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-skill`
3. Add your skill under `src/dcc_mcp_unreal/skills/`
4. Add tests under `tests/`
5. Run `ruff check . && pytest`
6. Open a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

## Related Projects

| Project | Description |
|---------|-------------|
| [dcc-mcp-core](https://github.com/dcc-mcp/dcc-mcp-core) | Core MCP infrastructure (Rust + PyO3) |
| [dcc-mcp-maya](https://github.com/dcc-mcp/dcc-mcp-maya) | Maya MCP adapter |
| [dcc-mcp-photoshop](https://github.com/dcc-mcp/dcc-mcp-photoshop) | Photoshop MCP adapter (bridge) |
| [dcc-mcp-zbrush](https://github.com/dcc-mcp/dcc-mcp-zbrush) | ZBrush MCP adapter (HTTP bridge) |
